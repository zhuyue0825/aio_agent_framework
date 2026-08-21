from __future__ import annotations

import logging
import os
from dataclasses import replace
from pathlib import Path
from secrets import compare_digest
from threading import RLock
from time import monotonic
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from agent_framework.http_json import post_json
from agent_framework.model import OpenAICompatibleModel
from agent_framework.runtime import AgentRunCancelled
from agent_framework.trace import TraceLogger

from .approval import ApprovalPolicy
from .agent_runtime import AgentRuntime
from .logging_config import (
    TRACE_ID_CONTEXT,
    configure_logging,
    current_trace_id,
    normalize_trace_id,
)
from .model_settings import ModelSettingsStore
from .workspace import (
    WorkspaceError,
    build_workspace_tools,
    build_workspace_tree,
    changed_workspace_files,
    list_directories,
    normalize_workspace_root,
    read_workspace_file,
    snapshot_workspace,
    write_workspace_file,
)


configure_logging()
logger = logging.getLogger("aio_agent.execution_service")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
TRACE_PATH = PROJECT_ROOT / "traces" / "app.jsonl"
model_settings = ModelSettingsStore.from_env(PROJECT_ROOT)


def required_internal_token() -> str:
    token = os.environ.get("INTERNAL_SERVICE_TOKEN", "").strip()
    if len(token) < 32:
        raise RuntimeError("INTERNAL_SERVICE_TOKEN must contain at least 32 characters")
    return token


INTERNAL_SERVICE_TOKEN = required_internal_token()


def require_internal_token(
    supplied: Annotated[str | None, Header(alias="X-Internal-Token")] = None,
) -> None:
    if supplied is None or not compare_digest(supplied, INTERNAL_SERVICE_TOKEN):
        raise HTTPException(status_code=401, detail={"code": "INVALID_INTERNAL_TOKEN", "message": "内部服务凭证无效"})


app = FastAPI(
    title="AIO Agent Execution Service",
    version="0.2.0",
    dependencies=[Depends(require_internal_token)],
)


@app.middleware("http")
async def trace_request(request: Request, call_next: Any) -> Response:
    trace_id = normalize_trace_id(request.headers.get("X-Trace-Id"))
    context_token = TRACE_ID_CONTEXT.set(trace_id)
    started = monotonic()
    try:
        try:
            response = await call_next(request)
        except Exception:
            logger.exception(
                "unhandled_request_error",
                extra={"http_method": request.method, "path": request.url.path},
            )
            response = JSONResponse(
                status_code=500,
                content={
                    "detail": {
                        "code": "INTERNAL_ERROR",
                        "message": "服务内部错误，请稍后重试",
                        "trace_id": trace_id,
                    }
                },
            )
        response.headers["X-Trace-Id"] = trace_id
        logger.info(
            "request_completed",
            extra={
                "http_method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_seconds": round(monotonic() - started, 6),
            },
        )
        return response
    finally:
        TRACE_ID_CONTEXT.reset(context_token)


@app.exception_handler(HTTPException)
async def http_exception_handler(_: Request, exception: HTTPException) -> JSONResponse:
    detail = exception.detail if isinstance(exception.detail, dict) else {}
    code = str(detail.get("code") or "REQUEST_ERROR")
    if exception.status_code >= 500:
        message = str(detail.get("message") or "服务暂时不可用，请稍后重试")
    else:
        message = str(detail.get("message") or exception.detail or "请求处理失败")
    return JSONResponse(
        status_code=exception.status_code,
        content={
            "detail": {
                "code": code,
                "message": message,
                "trace_id": str(detail.get("trace_id") or current_trace_id()),
            }
        },
        headers=exception.headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(_: Request, exception: RequestValidationError) -> JSONResponse:
    details = [
        {
            "field": ".".join(str(part) for part in error.get("loc", ()) if part != "body"),
            "message": error.get("msg", "invalid value"),
        }
        for error in exception.errors()
    ]
    return JSONResponse(
        status_code=422,
        content={
            "detail": {
                "code": "VALIDATION_ERROR",
                "message": "请求参数不合法",
                "trace_id": current_trace_id(),
                "details": details,
            }
        },
    )


class HistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=100_000)


class AgentRunRequest(BaseModel):
    run_id: UUID
    task: str = Field(min_length=1, max_length=100_000)
    mode: Literal["chat", "project"] = "chat"
    history: list[HistoryMessage] = Field(default_factory=list, max_length=30)
    workspace_root: str | None = None
    approval_mode: str = "auto"
    max_steps: int = Field(default=8, ge=1, le=30)
    trace_id: str | None = Field(default=None, max_length=128)
    callback_url: str | None = Field(default=None, max_length=2_000)


class WorkspaceOpenRequest(BaseModel):
    path: str = Field(min_length=1)


class WorkspaceFileWriteRequest(BaseModel):
    root: str = Field(min_length=1)
    path: str = Field(min_length=1)
    content: str


class ModelSettingsUpdateRequest(BaseModel):
    active_provider: Literal["local", "remote"]
    remote_api_base: str = Field(min_length=1, max_length=2_000)
    remote_model_name: str = Field(min_length=1, max_length=200)
    remote_api_key: str | None = Field(default=None, max_length=2_000)
    local_api_base: str = Field(min_length=1, max_length=2_000)
    local_model_name: str = Field(min_length=1, max_length=200)


class CancellationRegistry:
    """Tracks active runs and cancellation tombstones across FastAPI worker threads."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._active: set[UUID] = set()
        self._cancelled: dict[UUID, float] = {}

    def begin(self, run_id: UUID) -> None:
        with self._lock:
            self._purge()
            if run_id in self._active:
                raise HTTPException(
                    status_code=409,
                    detail={"code": "RUN_ALREADY_ACTIVE", "message": "Agent run is already active"},
                )
            self._active.add(run_id)

    def finish(self, run_id: UUID) -> None:
        with self._lock:
            self._active.discard(run_id)
            self._cancelled.pop(run_id, None)

    def cancel(self, run_id: UUID) -> bool:
        with self._lock:
            self._purge()
            active = run_id in self._active
            self._cancelled[run_id] = monotonic()
            return active

    def is_cancelled(self, run_id: UUID) -> bool:
        with self._lock:
            return run_id in self._cancelled

    def _purge(self) -> None:
        cutoff = monotonic() - 600
        expired = [run_id for run_id, created_at in self._cancelled.items() if created_at < cutoff]
        for run_id in expired:
            self._cancelled.pop(run_id, None)


cancellations = CancellationRegistry()


class ProgressReporter:
    def __init__(self, run_id: UUID, trace_id: str, callback_url: str | None) -> None:
        self.run_id = run_id
        self.trace_id = trace_id
        self.callback_url = callback_url

    def emit(self, event_type: str, payload: dict[str, Any]) -> None:
        if not self.callback_url:
            return
        try:
            post_json(
                self.callback_url,
                {
                    "event_type": event_type,
                    "payload": {"run_id": str(self.run_id), "trace_id": self.trace_id, **payload},
                    "trace_id": self.trace_id,
                },
                headers={
                    "X-Internal-Token": INTERNAL_SERVICE_TOKEN,
                    "X-Trace-Id": self.trace_id,
                },
                timeout=3,
            )
        except Exception as exc:  # Progress reporting must not make the Agent run fail.
            logger.warning(
                "progress_callback_failed",
                extra={"run_id": str(self.run_id), "event": event_type},
                exc_info=True,
            )


def trim_repetitive_answer(text: str) -> str:
    paragraphs = [paragraph.strip() for paragraph in text.split("\n\n") if paragraph.strip()]
    if not paragraphs:
        return text.strip()

    kept: list[str] = []
    seen: set[str] = set()
    for paragraph in paragraphs:
        normalized = " ".join(paragraph.split())
        if normalized in seen:
            break
        seen.add(normalized)
        kept.append(paragraph)
        if len(kept) >= 3:
            break
    return "\n\n".join(kept).strip()


def run_plain_chat(
    task: str,
    history: list[HistoryMessage],
    should_cancel: Any,
    on_event: Any,
) -> dict[str, Any]:
    should_raise_cancelled(should_cancel)
    on_event("agent.step.started", {"step": 1})
    active_config = model_settings.active_config()
    model = OpenAICompatibleModel(active_config)
    messages: list[dict[str, str]] = [
        *[{"role": item.role, "content": item.content} for item in history],
        {"role": "user", "content": task},
    ]
    message = model.complete(messages, tools=[], max_tokens=512, temperature=0.05, top_p=0.7)
    should_raise_cancelled(should_cancel)
    on_event("agent.completed", {"steps": 1})
    return {
        "final_answer": trim_repetitive_answer(message.get("content") or ""),
        "steps": 1,
        "changed_files": [],
    }


def build_project_context(history: list[HistoryMessage], task: str) -> str:
    formatted: list[str] = []
    for message in history:
        content = message.content
        if message.role == "assistant" and ('"tool_call"' in content or "模型生成了无效工具调用" in content):
            continue
        if len(content) > 1_200:
            content = content[:1_200] + "...<已截断>"
        formatted.append(f"{'用户' if message.role == 'user' else '助手'}：{content}")
    if not formatted:
        return task
    return "\n".join(
        [
            "下面是当前 App 对话的最近上下文，请理解上下文后完成用户最新任务。",
            "",
            *formatted,
            "",
            f"用户最新任务：{task}",
        ]
    )


def run_project_agent(
    request: AgentRunRequest,
    trace_id: str,
    should_cancel: Any,
    on_event: Any,
) -> dict[str, Any]:
    if not request.workspace_root:
        raise WorkspaceError("项目模式下必须由业务服务传入项目工作区")
    root = normalize_workspace_root(request.workspace_root)
    before = snapshot_workspace(root)
    tools = build_workspace_tools(root)
    active_config = model_settings.active_config()
    runtime = AgentRuntime(
        config=replace(active_config, max_steps=request.max_steps),
        tools=tools,
        approval=ApprovalPolicy(request.approval_mode, writable_prefixes=("",)),
        trace=TraceLogger(str(TRACE_PATH), context={"trace_id": trace_id, "run_id": str(request.run_id)}),
        system_prompt=(
            "You are a coding agent working in one explicitly opened local project. "
            f"The project root is {root}. All tool paths must be relative to this root. "
            "Available tools are exactly: list_files, file_read, file_write, search_files. "
            "Inspect relevant files before editing. Use file_write only with complete file content. "
            "Never access paths outside the project, never invent tools, and only report changes confirmed by tool results. "
            "Answer the user in Chinese and mention the relative paths you changed."
        ),
    )
    result = runtime.run(
        build_project_context(request.history, request.task),
        should_cancel=should_cancel,
        on_event=on_event,
    )
    after = snapshot_workspace(root)
    return {
        "final_answer": result.final_answer,
        "steps": result.steps,
        "changed_files": changed_workspace_files(before, after),
    }


def should_raise_cancelled(should_cancel: Any) -> None:
    if should_cancel():
        raise AgentRunCancelled("Agent run was cancelled")


@app.get("/internal/v1/health")
def health() -> dict[str, Any]:
    active_config = model_settings.active_config()
    return {
        "ok": True,
        "service": "aio-agent-execution-service",
        "model_provider": active_config.model_provider,
        "model_name": active_config.model_name,
        "model_api_base": active_config.model_api_base,
        "api_key_configured": bool(active_config.model_api_key),
        "max_steps": active_config.max_steps,
        "supports_projects": True,
    }


@app.get("/internal/v1/model-settings")
def get_model_settings() -> dict[str, Any]:
    return model_settings.public_view()


@app.put("/internal/v1/model-settings")
def update_model_settings(payload: ModelSettingsUpdateRequest) -> dict[str, Any]:
    try:
        return model_settings.update(
            active_provider=payload.active_provider,
            remote_api_base=payload.remote_api_base,
            remote_model_name=payload.remote_model_name,
            remote_api_key=payload.remote_api_key,
            local_api_base=payload.local_api_base,
            local_model_name=payload.local_model_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "INVALID_MODEL_SETTINGS", "message": str(exc)}) from exc


@app.post("/internal/v1/model-settings/test")
def test_model_settings() -> dict[str, Any]:
    active_config = model_settings.active_config()
    try:
        message = OpenAICompatibleModel(active_config).complete(
            [
                {"role": "system", "content": "You are a connectivity check. Reply with OK only."},
                {"role": "user", "content": "ping"},
            ],
            tools=[],
            max_tokens=32,
            temperature=0,
        )
        return {
            "ok": True,
            "provider": active_config.model_provider,
            "model_name": active_config.model_name,
            "response": (message.get("content") or "").strip()[:200],
        }
    except Exception as exc:
        logger.warning(
            "model_connection_test_failed",
            extra={"event": "model_connection_test"},
            exc_info=True,
        )
        raise HTTPException(
            status_code=502,
            detail={"code": "MODEL_CONNECTION_FAILED", "message": "模型服务连接失败，请检查地址、模型名称和 API Key"},
        ) from exc


@app.post("/internal/v1/agent/runs")
def execute_agent_run(
    request: AgentRunRequest,
    header_trace_id: Annotated[str | None, Header(alias="X-Trace-Id")] = None,
) -> dict[str, Any]:
    trace_id = normalize_trace_id(request.trace_id or header_trace_id)
    reporter = ProgressReporter(request.run_id, trace_id, request.callback_url)
    cancellations.begin(request.run_id)
    context_token = TRACE_ID_CONTEXT.set(trace_id)
    try:
        logger.info("agent_run_started", extra={"run_id": str(request.run_id), "event": "agent_run_started"})
        reporter.emit("agent.request.accepted", {"mode": request.mode})
        should_cancel = lambda: cancellations.is_cancelled(request.run_id)
        if request.mode == "project":
            result = run_project_agent(request, trace_id, should_cancel, reporter.emit)
        else:
            result = run_plain_chat(request.task, request.history, should_cancel, reporter.emit)
        reporter.emit("agent.response.ready", {"steps": result["steps"]})
        logger.info("agent_run_completed", extra={"run_id": str(request.run_id), "event": "agent_run_completed"})
        return {**result, "trace_id": trace_id}
    except AgentRunCancelled as exc:
        reporter.emit("agent.cancelled", {})
        raise HTTPException(
            status_code=409,
            detail={"code": "RUN_CANCELLED", "message": "Agent 任务已取消", "trace_id": trace_id},
        ) from exc
    except WorkspaceError as exc:
        reporter.emit("agent.failed", {"code": "WORKSPACE_ERROR", "message": str(exc)})
        raise HTTPException(
            status_code=400,
            detail={"code": "WORKSPACE_ERROR", "message": str(exc), "trace_id": trace_id},
        ) from exc
    except Exception as exc:
        logger.exception(
            "agent_run_failed",
            extra={"run_id": str(request.run_id), "event": "agent_run_failed"},
        )
        reporter.emit("agent.failed", {"code": "AGENT_EXECUTION_ERROR", "message": "Agent 任务执行失败"})
        raise HTTPException(
            status_code=500,
            detail={"code": "AGENT_EXECUTION_ERROR", "message": "Agent 任务执行失败，请稍后重试", "trace_id": trace_id},
        ) from exc
    finally:
        cancellations.finish(request.run_id)
        TRACE_ID_CONTEXT.reset(context_token)


@app.delete("/internal/v1/agent/runs/{run_id}")
def cancel_agent_run(run_id: UUID) -> dict[str, Any]:
    return {"ok": True, "run_id": str(run_id), "active": cancellations.cancel(run_id)}


@app.get("/internal/v1/workspaces/directories")
def workspace_directories(path: str | None = Query(default=None)) -> dict[str, Any]:
    try:
        return list_directories(path)
    except WorkspaceError as exc:
        raise HTTPException(status_code=400, detail={"code": "WORKSPACE_ERROR", "message": str(exc)}) from exc


@app.post("/internal/v1/workspaces/open")
def open_workspace(payload: WorkspaceOpenRequest) -> dict[str, Any]:
    try:
        root = normalize_workspace_root(payload.path)
        return {"workspace": build_workspace_tree(root)}
    except WorkspaceError as exc:
        raise HTTPException(status_code=400, detail={"code": "WORKSPACE_ERROR", "message": str(exc)}) from exc


@app.get("/internal/v1/workspaces/tree")
def workspace_tree(path: str = Query(min_length=1)) -> dict[str, Any]:
    try:
        root = normalize_workspace_root(path)
        return {"workspace": build_workspace_tree(root)}
    except WorkspaceError as exc:
        raise HTTPException(status_code=400, detail={"code": "WORKSPACE_ERROR", "message": str(exc)}) from exc


@app.get("/internal/v1/workspaces/file")
def workspace_file(root: str = Query(min_length=1), path: str = Query(min_length=1)) -> dict[str, Any]:
    try:
        workspace_root = normalize_workspace_root(root)
        return {"file": read_workspace_file(workspace_root, path)}
    except WorkspaceError as exc:
        raise HTTPException(status_code=400, detail={"code": "WORKSPACE_ERROR", "message": str(exc)}) from exc


@app.put("/internal/v1/workspaces/file")
def save_workspace_file(payload: WorkspaceFileWriteRequest) -> dict[str, Any]:
    try:
        workspace_root = normalize_workspace_root(payload.root)
        return {"file": write_workspace_file(workspace_root, payload.path, payload.content)}
    except WorkspaceError as exc:
        raise HTTPException(status_code=400, detail={"code": "WORKSPACE_ERROR", "message": str(exc)}) from exc
