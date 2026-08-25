from __future__ import annotations

import logging
import os
import hashlib
import json
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from secrets import compare_digest
from threading import Event, RLock
from time import monotonic
from typing import Annotated, Any, Callable, Literal
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from agent_framework.http_json import post_json
from agent_framework.model import ModelApiError, ModelCancelledError, OpenAICompatibleModel
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
from .model_registry import ModelNotFoundError, ModelRegistry, ModelUnavailableError
from .model_settings import ModelSettingsStore
from .redis_cancellation import RedisCancellationBridge
from .workspace import (
    WorkspaceError,
    apply_workspace_changes,
    build_workspace_tools,
    build_workspace_tree,
    list_directories,
    normalize_workspace_root,
    read_workspace_file,
    write_workspace_file,
)


configure_logging()
logger = logging.getLogger("aio_agent.execution_service")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
TRACE_PATH = PROJECT_ROOT / "traces" / "app.jsonl"
model_settings = ModelSettingsStore.from_env(PROJECT_ROOT)
model_registry = ModelRegistry.from_env(PROJECT_ROOT, model_settings)


def required_internal_token() -> str:
    token = os.environ.get("INTERNAL_SERVICE_TOKEN", "").strip()
    if len(token) < 32:
        raise RuntimeError("INTERNAL_SERVICE_TOKEN must contain at least 32 characters")
    return token


INTERNAL_SERVICE_TOKEN = required_internal_token()


@asynccontextmanager
async def lifespan(_: FastAPI):
    redis_cancellations.start()
    try:
        yield
    finally:
        redis_cancellations.stop()


def require_internal_token(
    supplied: Annotated[str | None, Header(alias="X-Internal-Token")] = None,
) -> None:
    if supplied is None or not compare_digest(supplied, INTERNAL_SERVICE_TOKEN):
        raise HTTPException(status_code=401, detail={"code": "INVALID_INTERNAL_TOKEN", "message": "内部服务凭证无效"})


app = FastAPI(
    title="AIO Agent Execution Service",
    version="0.2.0",
    dependencies=[Depends(require_internal_token)],
    lifespan=lifespan,
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
    model_config = ConfigDict(extra="forbid")

    run_id: UUID
    task: str = Field(min_length=1, max_length=100_000)
    mode: Literal["chat", "project"] = "chat"
    model_provider: Literal["local", "remote"] = "local"
    model_id: str | None = Field(default=None, min_length=3, max_length=200, pattern=r"^[a-z0-9][a-z0-9:._/-]+$")
    history: list[HistoryMessage] = Field(default_factory=list, max_length=30)
    workspace_root: str | None = None
    approval_mode: str = "auto"
    max_steps: int = Field(default=8, ge=1, le=30)
    history_token_budget: int = Field(default=8_000, ge=512, le=64_000)
    trace_id: str | None = Field(default=None, max_length=128)
    callback_url: str | None = Field(default=None, max_length=2_000)
    requested_by_id: UUID | None = None
    workspace_owner_id: UUID | None = None


class WorkspaceOpenRequest(BaseModel):
    path: str = Field(min_length=1)
    owner_id: UUID | None = None


class WorkspaceFileWriteRequest(BaseModel):
    root: str = Field(min_length=1)
    path: str = Field(min_length=1)
    content: str
    owner_id: UUID | None = None


class ProposedWorkspaceChange(BaseModel):
    path: str = Field(min_length=1)
    original_sha256: str = Field(min_length=64, max_length=64)
    content: str


class WorkspaceChangesApplyRequest(BaseModel):
    root: str = Field(min_length=1)
    changes: list[ProposedWorkspaceChange] = Field(min_length=1, max_length=100)
    owner_id: UUID | None = None
    operation_id: UUID | None = None


class ModelSettingsUpdateRequest(BaseModel):
    active_provider: Literal["local", "remote"]
    remote_api_base: str = Field(min_length=1, max_length=2_000)
    remote_model_name: str = Field(min_length=1, max_length=200)
    remote_api_key: str | None = Field(default=None, max_length=2_000)
    local_api_base: str = Field(min_length=1, max_length=2_000)
    local_model_name: str = Field(min_length=1, max_length=200)


class RunCancellation:
    """Cancellation signal that can also close an active upstream HTTP connection."""

    def __init__(self) -> None:
        self._cancelled = Event()
        self._lock = RLock()
        self._aborters: set[Callable[[], None]] = set()

    def cancel(self) -> None:
        self._cancelled.set()
        with self._lock:
            aborters = list(self._aborters)
        for abort in aborters:
            try:
                abort()
            except Exception:
                logger.debug("model_abort_callback_failed", exc_info=True)

    def is_cancelled(self) -> bool:
        return self._cancelled.is_set()

    def register_abort(self, abort: Callable[[], None]) -> Callable[[], None]:
        with self._lock:
            if self._cancelled.is_set():
                abort()
                return lambda: None
            self._aborters.add(abort)

        def unregister() -> None:
            with self._lock:
                self._aborters.discard(abort)

        return unregister


class CancellationRegistry:
    """Tracks active runs and cancellation tombstones across FastAPI worker threads."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._active: dict[UUID, RunCancellation] = {}
        self._cancelled: dict[UUID, float] = {}

    def begin(self, run_id: UUID) -> RunCancellation:
        with self._lock:
            self._purge()
            if run_id in self._active:
                raise HTTPException(
                    status_code=409,
                    detail={"code": "RUN_ALREADY_ACTIVE", "message": "Agent run is already active"},
                )
            control = RunCancellation()
            if run_id in self._cancelled:
                control.cancel()
            self._active[run_id] = control
            return control

    def finish(self, run_id: UUID) -> None:
        with self._lock:
            self._active.pop(run_id, None)
            self._cancelled.pop(run_id, None)

    def cancel(self, run_id: UUID) -> bool:
        with self._lock:
            self._purge()
            control = self._active.get(run_id)
            active = control is not None
            self._cancelled[run_id] = monotonic()
        if control is not None:
            control.cancel()
        return active

    def is_cancelled(self, run_id: UUID) -> bool:
        with self._lock:
            control = self._active.get(run_id)
            return run_id in self._cancelled or (control is not None and control.is_cancelled())

    def _purge(self) -> None:
        cutoff = monotonic() - 600
        expired = [run_id for run_id, created_at in self._cancelled.items() if created_at < cutoff]
        for run_id in expired:
            self._cancelled.pop(run_id, None)


cancellations = CancellationRegistry()
redis_cancellations = RedisCancellationBridge(cancellations.cancel)


class WorkspaceApplyRegistry:
    """Deduplicates concurrent workspace writes by the business run id."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._results: dict[UUID, tuple[str, list[str]]] = {}
        self._inflight: dict[UUID, tuple[str, Event]] = {}

    def execute(self, operation_id: UUID, fingerprint: str, apply: Callable[[], list[str]]) -> list[str]:
        leader = False
        with self._lock:
            completed = self._results.get(operation_id)
            if completed is not None:
                if completed[0] != fingerprint:
                    raise WorkspaceError("相同操作编号对应了不同的修改内容")
                return list(completed[1])
            active = self._inflight.get(operation_id)
            if active is None:
                event = Event()
                self._inflight[operation_id] = (fingerprint, event)
                leader = True
            else:
                if active[0] != fingerprint:
                    raise WorkspaceError("相同操作编号对应了不同的修改内容")
                event = active[1]

        if not leader:
            if not event.wait(timeout=180):
                raise WorkspaceError("修改仍在处理中，请稍后重试")
            with self._lock:
                completed = self._results.get(operation_id)
                if completed is None:
                    raise WorkspaceError("上一次修改写入失败，请重试")
                return list(completed[1])

        try:
            result = apply()
            with self._lock:
                self._results[operation_id] = (fingerprint, list(result))
                if len(self._results) > 10_000:
                    self._results.pop(next(iter(self._results)))
            return result
        finally:
            with self._lock:
                active = self._inflight.pop(operation_id, None)
                if active is not None:
                    active[1].set()


workspace_apply_registry = WorkspaceApplyRegistry()


class ProgressReporter:
    def __init__(self, run_id: UUID, trace_id: str, callback_url: str | None) -> None:
        self.run_id = run_id
        self.trace_id = trace_id
        self.callback_url = callback_url
        self._lock = RLock()
        self._token_buffer = ""

    def emit(self, event_type: str, payload: dict[str, Any]) -> None:
        if not self.callback_url:
            return
        if event_type == "agent.token.delta":
            delta = payload.get("delta")
            if isinstance(delta, str):
                with self._lock:
                    self._token_buffer += delta
                    if len(self._token_buffer) < 80:
                        return
                    payload = {**payload, "delta": self._token_buffer}
                    self._token_buffer = ""
        else:
            self.flush_tokens()
        self._send(event_type, payload)

    def flush_tokens(self) -> None:
        with self._lock:
            if not self._token_buffer:
                return
            delta = self._token_buffer
            self._token_buffer = ""
        self._send("agent.token.delta", {"delta": delta})

    def _send(self, event_type: str, payload: dict[str, Any]) -> None:
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
    model_provider: Literal["local", "remote"],
    should_cancel: Any,
    register_abort: Any,
    on_event: Any,
    model_id: str | None = None,
) -> dict[str, Any]:
    should_raise_cancelled(should_cancel)
    on_event("agent.step.started", {"step": 1})
    active_config = model_registry.config_for(model_id, model_provider)
    model = OpenAICompatibleModel(active_config)
    trimmed_history = trim_history_to_token_budget(history, active_config.history_token_budget)
    messages: list[dict[str, str]] = [
        *[{"role": item.role, "content": item.content} for item in trimmed_history],
        {"role": "user", "content": task},
    ]
    try:
        completion = model.complete(
            messages,
            tools=[],
            temperature=0.05,
            top_p=0.7,
            should_cancel=should_cancel,
            register_abort=register_abort,
            on_token=lambda delta: on_event("agent.token.delta", {"step": 1, "delta": delta}),
        )
    except ModelCancelledError as exc:
        raise AgentRunCancelled("Agent run was cancelled") from exc
    should_raise_cancelled(should_cancel)
    on_event(
        "agent.model.completed",
        {
            "step": 1,
            "tool_call_count": 0,
            "provider": completion.provider,
            "model_name": completion.model_name,
            "request_count": completion.request_count,
            "input_tokens": completion.usage.input_tokens,
            "output_tokens": completion.usage.output_tokens,
            "latency_ms": completion.latency_ms,
        },
    )
    on_event("agent.completed", {"steps": 1})
    return {
        "final_answer": trim_repetitive_answer(completion.message.get("content") or ""),
        "steps": 1,
        "changed_files": [],
        "model_provider": completion.provider,
        "model_name": completion.model_name,
        "model_request_count": completion.request_count,
        "input_tokens": completion.usage.input_tokens,
        "output_tokens": completion.usage.output_tokens,
        "model_latency_ms": completion.latency_ms,
    }


def estimate_tokens(text: str) -> int:
    """Provider-neutral conservative estimate used before a provider tokenizer is available."""
    ascii_count = sum(1 for char in text if ord(char) < 128)
    non_ascii_count = len(text) - ascii_count
    return max(1, (ascii_count + 3) // 4 + non_ascii_count)


def trim_history_to_token_budget(history: list[HistoryMessage], budget: int) -> list[HistoryMessage]:
    selected: list[HistoryMessage] = []
    used = 0
    for message in reversed(history):
        cost = estimate_tokens(message.content) + 8
        if selected and used + cost > budget:
            break
        if cost > budget:
            allowed_chars = max(1, budget * 2)
            selected.append(HistoryMessage(role=message.role, content=message.content[-allowed_chars:]))
            break
        selected.append(message)
        used += cost
    selected.reverse()
    return selected


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
    register_abort: Any,
    on_event: Any,
) -> dict[str, Any]:
    if not request.workspace_root:
        raise WorkspaceError("项目模式下必须由业务服务传入项目工作区")
    root = normalize_workspace_root(
        request.workspace_root,
        str(request.workspace_owner_id) if request.workspace_owner_id else None,
    )
    tools, tool_session = build_workspace_tools(root)
    tool_names = [spec["function"]["name"] for spec in tools.specs()]
    active_config = model_registry.config_for(request.model_id, request.model_provider)
    runtime = AgentRuntime(
        config=replace(active_config, max_steps=request.max_steps),
        tools=tools,
        approval=ApprovalPolicy(request.approval_mode, writable_prefixes=("",)),
        trace=TraceLogger(str(TRACE_PATH), context={"trace_id": trace_id, "run_id": str(request.run_id)}),
        system_prompt=(
            "You are a coding agent working in one explicitly opened local project. "
            f"The project root is {root}. All tool paths must be relative to this root. "
            f"Available tools are exactly: {', '.join(tool_names)}. "
            "Inspect relevant files before editing. Prefer apply_patch for small changes. All writes are staged proposals; "
            "call git_diff before finishing and tell the user that confirmation is required. "
            "Never access paths outside the project, never invent tools, and only report changes confirmed by tool results. "
            "Answer the user in Chinese and mention the relative paths you changed."
        ),
    )
    result = runtime.run(
        build_project_context(
            trim_history_to_token_budget(request.history, request.history_token_budget),
            request.task,
        ),
        should_cancel=should_cancel,
        register_abort=register_abort,
        on_event=on_event,
    )
    proposals = tool_session.proposals()
    return {
        "final_answer": result.final_answer,
        "steps": result.steps,
        "changed_files": [],
        "proposed_changes": proposals,
        "model_provider": result.model_provider,
        "model_name": result.model_name,
        "model_request_count": result.model_request_count,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "model_latency_ms": result.model_latency_ms,
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


@app.get("/internal/v1/models")
def get_registered_models(refresh: bool = Query(default=False)) -> dict[str, Any]:
    return model_registry.public_view(refresh=refresh)


@app.put("/internal/v1/model-settings")
def update_model_settings(payload: ModelSettingsUpdateRequest) -> dict[str, Any]:
    try:
        result = model_settings.update(
            active_provider=payload.active_provider,
            remote_api_base=payload.remote_api_base,
            remote_model_name=payload.remote_model_name,
            remote_api_key=payload.remote_api_key,
            local_api_base=payload.local_api_base,
            local_model_name=payload.local_model_name,
        )
        model_registry.invalidate()
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "INVALID_MODEL_SETTINGS", "message": str(exc)}) from exc


@app.post("/internal/v1/model-settings/test")
def test_model_settings() -> dict[str, Any]:
    active_config = model_settings.active_config()
    try:
        completion = OpenAICompatibleModel(active_config).complete(
            [
                {"role": "system", "content": "You are a connectivity check. Reply with OK only."},
                {"role": "user", "content": "ping"},
            ],
            tools=[],
            max_tokens=32,
            temperature=0.1,
        )
        return {
            "ok": True,
            "provider": active_config.model_provider,
            "model_name": active_config.model_name,
            "response": (completion.message.get("content") or "").strip()[:200],
        }
    except Exception as exc:
        logger.warning(
            "model_connection_test_failed",
            extra={"event": "model_connection_test", "error_type": type(exc).__name__},
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
    cancellation = cancellations.begin(request.run_id)
    if redis_cancellations.was_cancelled(request.run_id):
        cancellation.cancel()
    context_token = TRACE_ID_CONTEXT.set(trace_id)
    try:
        logger.info("agent_run_started", extra={"run_id": str(request.run_id), "event": "agent_run_started"})
        reporter.emit("agent.request.accepted", {"mode": request.mode})
        should_cancel = cancellation.is_cancelled
        if request.mode == "project":
            result = run_project_agent(request, trace_id, should_cancel, cancellation.register_abort, reporter.emit)
        else:
            result = run_plain_chat(
                request.task,
                request.history,
                request.model_provider,
                should_cancel,
                cancellation.register_abort,
                reporter.emit,
                request.model_id,
            )
        reporter.emit("agent.response.ready", {"steps": result["steps"]})
        logger.info(
            "agent_run_completed",
            extra={
                "run_id": str(request.run_id),
                "event": "agent_run_completed",
                "model_provider": result.get("model_provider"),
                "model_name": result.get("model_name"),
                "model_request_count": result.get("model_request_count"),
                "input_tokens": result.get("input_tokens"),
                "output_tokens": result.get("output_tokens"),
                "model_latency_ms": result.get("model_latency_ms"),
            },
        )
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
    except ModelNotFoundError as exc:
        reporter.emit("agent.failed", {"code": "MODEL_NOT_FOUND"})
        raise HTTPException(
            status_code=409,
            detail={"code": "MODEL_NOT_FOUND", "message": str(exc), "trace_id": trace_id},
        ) from exc
    except ModelUnavailableError as exc:
        reporter.emit("agent.failed", {"code": "MODEL_UNAVAILABLE"})
        raise HTTPException(
            status_code=409,
            detail={"code": "MODEL_UNAVAILABLE", "message": str(exc), "trace_id": trace_id},
        ) from exc
    except ModelApiError as exc:
        reporter.emit("agent.failed", {"code": exc.code})
        logger.warning(
            "model_api_failed",
            extra={"run_id": str(request.run_id), "event": "model_api_failed", "error_code": exc.code},
        )
        raise HTTPException(
            status_code=502,
            detail={"code": exc.code, "message": "模型服务暂时不可用，请稍后重试", "trace_id": trace_id},
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
    active = cancellations.cancel(run_id)
    redis_cancellations.publish(run_id)
    return {"ok": True, "run_id": str(run_id), "active": active}


@app.get("/internal/v1/workspaces/directories")
def workspace_directories(
    path: str | None = Query(default=None),
    owner_id: UUID | None = Query(default=None),
) -> dict[str, Any]:
    try:
        return list_directories(path, str(owner_id) if owner_id else None)
    except WorkspaceError as exc:
        raise HTTPException(status_code=400, detail={"code": "WORKSPACE_ERROR", "message": str(exc)}) from exc


@app.post("/internal/v1/workspaces/open")
def open_workspace(payload: WorkspaceOpenRequest) -> dict[str, Any]:
    try:
        root = normalize_workspace_root(payload.path, str(payload.owner_id) if payload.owner_id else None)
        return {"workspace": build_workspace_tree(root)}
    except WorkspaceError as exc:
        raise HTTPException(status_code=400, detail={"code": "WORKSPACE_ERROR", "message": str(exc)}) from exc


@app.get("/internal/v1/workspaces/tree")
def workspace_tree(
    path: str = Query(min_length=1),
    owner_id: UUID | None = Query(default=None),
) -> dict[str, Any]:
    try:
        root = normalize_workspace_root(path, str(owner_id) if owner_id else None)
        return {"workspace": build_workspace_tree(root)}
    except WorkspaceError as exc:
        raise HTTPException(status_code=400, detail={"code": "WORKSPACE_ERROR", "message": str(exc)}) from exc


@app.get("/internal/v1/workspaces/file")
def workspace_file(
    root: str = Query(min_length=1),
    path: str = Query(min_length=1),
    owner_id: UUID | None = Query(default=None),
) -> dict[str, Any]:
    try:
        workspace_root = normalize_workspace_root(root, str(owner_id) if owner_id else None)
        return {"file": read_workspace_file(workspace_root, path)}
    except WorkspaceError as exc:
        raise HTTPException(status_code=400, detail={"code": "WORKSPACE_ERROR", "message": str(exc)}) from exc


@app.put("/internal/v1/workspaces/file")
def save_workspace_file(payload: WorkspaceFileWriteRequest) -> dict[str, Any]:
    try:
        workspace_root = normalize_workspace_root(payload.root, str(payload.owner_id) if payload.owner_id else None)
        return {"file": write_workspace_file(workspace_root, payload.path, payload.content)}
    except WorkspaceError as exc:
        raise HTTPException(status_code=400, detail={"code": "WORKSPACE_ERROR", "message": str(exc)}) from exc


@app.post("/internal/v1/workspaces/changes/apply")
def apply_proposed_workspace_changes(payload: WorkspaceChangesApplyRequest) -> dict[str, Any]:
    try:
        workspace_root = normalize_workspace_root(payload.root, str(payload.owner_id) if payload.owner_id else None)
        changes = [change.model_dump() for change in payload.changes]
        apply = lambda: apply_workspace_changes(workspace_root, changes)
        if payload.operation_id is None:
            changed = apply()
        else:
            fingerprint = hashlib.sha256(
                json.dumps(
                    {
                        "root": str(workspace_root),
                        "owner_id": str(payload.owner_id) if payload.owner_id else None,
                        "changes": changes,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ).encode("utf-8")
            ).hexdigest()
            changed = workspace_apply_registry.execute(payload.operation_id, fingerprint, apply)
        return {"ok": True, "changed_files": changed, "operation_id": payload.operation_id}
    except WorkspaceError as exc:
        raise HTTPException(status_code=409, detail={"code": "WORKSPACE_CHANGED", "message": str(exc)}) from exc
