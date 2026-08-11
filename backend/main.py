from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from agent_framework.config import AgentConfig
from agent_framework.model import OpenAICompatibleModel
from agent_framework.trace import TraceLogger

from .approval import ApprovalPolicy
from .agent_runtime import AgentRuntime
from .db import AppDB
from .sandbox_client import SandboxClient
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


config = AgentConfig.from_env()
db = AppDB()
app = FastAPI(title="AIO Agent App", version="0.1.0")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
TRACE_PATH = PROJECT_ROOT / "traces" / "app.jsonl"

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ConversationCreate(BaseModel):
    title: str = "新对话"


class ConversationTitleUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=80)


class RunRequest(BaseModel):
    task: str = Field(min_length=1)
    approval_mode: str = "auto"
    max_history_messages: int = Field(default=8, ge=0, le=30)
    mode: Literal["chat", "project"] = "chat"
    workspace_path: str | None = None


class WorkspaceOpenRequest(BaseModel):
    path: str = Field(min_length=1)


class WorkspaceFileWriteRequest(BaseModel):
    root: str = Field(min_length=1)
    path: str = Field(min_length=1)
    content: str


def ensure_conversation(conversation_id: str) -> dict[str, Any]:
    conversation = db.get_conversation(conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="conversation not found")
    return conversation


def build_project_context(conversation_id: str, task: str, max_history_messages: int) -> str:
    if max_history_messages <= 0:
        return task
    messages = db.list_messages(conversation_id)
    if messages and messages[-1]["role"] == "user":
        messages = messages[:-1]
    history: list[str] = []
    for message in messages[-max_history_messages:]:
        if message["role"] not in {"user", "assistant"}:
            continue
        content = str(message["content"])
        if message["role"] == "assistant" and ('"tool_call"' in content or "模型生成了无效工具调用" in content):
            continue
        if len(content) > 1200:
            content = content[:1200] + "...<已截断>"
        history.append(f"{'用户' if message['role'] == 'user' else '助手'}：{content}")
    if not history:
        return task
    return "\n".join(
        [
            "下面是当前 App 对话的最近上下文，请理解上下文后完成用户最新任务。",
            "",
            *history,
            "",
            f"用户最新任务：{task}",
        ]
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


def run_plain_chat(conversation_id: str, max_history_messages: int) -> dict[str, Any]:
    model = OpenAICompatibleModel(config)
    history = db.list_messages(conversation_id)
    if max_history_messages > 0:
        history = history[-max_history_messages:]
    else:
        history = history[-1:]
    messages: list[dict[str, str]] = [
        {
            "role": "system",
            "content": "你是 MiniMind，一个中文聊天助手。自然、清楚地回答用户；不知道时直接说明。",
        }
    ]
    for item in history:
        if item["role"] not in {"user", "assistant"}:
            continue
        messages.append({"role": item["role"], "content": str(item["content"])})
    message = model.complete(
        messages,
        tools=[],
        max_tokens=512,
        temperature=0.05,
        top_p=0.7,
    )
    return {
        "final_answer": trim_repetitive_answer(message.get("content") or ""),
        "steps": 1,
        "changed_files": [],
    }


def run_project_agent(
    conversation_id: str,
    task: str,
    max_history_messages: int,
    approval_mode: str,
    workspace_path: str,
) -> dict[str, Any]:
    root = normalize_workspace_root(workspace_path)
    before = snapshot_workspace(root)
    tools = build_workspace_tools(root)
    # Workspace handlers resolve every path against root before approval sees the call.
    runtime = AgentRuntime(
        config=config,
        tools=tools,
        approval=ApprovalPolicy(approval_mode, writable_prefixes=("",)),
        trace=TraceLogger(str(TRACE_PATH)),
        system_prompt=(
            "You are a coding agent working in one explicitly opened local project. "
            f"The project root is {root}. All tool paths must be relative to this root. "
            "Available tools are exactly: list_files, file_read, file_write, search_files. "
            "Inspect relevant files before editing. Use file_write only with complete file content. "
            "Never access paths outside the project, never invent tools, and only report changes confirmed by tool results. "
            "Answer the user in Chinese and mention the relative paths you changed."
        ),
    )
    result = runtime.run(build_project_context(conversation_id, task, max_history_messages))
    after = snapshot_workspace(root)
    return {
        "final_answer": result.final_answer,
        "steps": result.steps,
        "changed_files": changed_workspace_files(before, after),
    }


@app.get("/api/status")
def status() -> dict[str, Any]:
    return {
        "sandbox_url": config.sandbox_url,
        "model_api_base": config.model_api_base,
        "model_name": config.model_name,
        "max_steps": config.max_steps,
        "has_model_key": bool(config.model_api_key),
        "trace_path": str(TRACE_PATH),
        "db_path": str(db.path),
        "supports_projects": True,
    }


@app.get("/api/workspace/directories")
def workspace_directories(path: str | None = Query(default=None)) -> dict[str, Any]:
    try:
        return list_directories(path)
    except WorkspaceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/workspace/open")
def open_workspace(payload: WorkspaceOpenRequest) -> dict[str, Any]:
    try:
        root = normalize_workspace_root(payload.path)
        return {"workspace": build_workspace_tree(root)}
    except WorkspaceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/workspace/tree")
def workspace_tree(path: str = Query(min_length=1)) -> dict[str, Any]:
    try:
        root = normalize_workspace_root(path)
        return {"workspace": build_workspace_tree(root)}
    except WorkspaceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/workspace/file")
def workspace_file(root: str = Query(min_length=1), path: str = Query(min_length=1)) -> dict[str, Any]:
    try:
        workspace_root = normalize_workspace_root(root)
        return {"file": read_workspace_file(workspace_root, path)}
    except WorkspaceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.put("/api/workspace/file")
def save_workspace_file(payload: WorkspaceFileWriteRequest) -> dict[str, Any]:
    try:
        workspace_root = normalize_workspace_root(payload.root)
        return {"file": write_workspace_file(workspace_root, payload.path, payload.content)}
    except WorkspaceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/conversations")
def list_conversations() -> dict[str, Any]:
    conversations = db.list_conversations()
    if not conversations:
        conversations = [db.create_conversation()]
    return {"conversations": conversations}


@app.post("/api/conversations")
def create_conversation(payload: ConversationCreate) -> dict[str, Any]:
    conversation = db.create_conversation(payload.title)
    return {"conversation": conversation}


@app.patch("/api/conversations/{conversation_id}")
def update_conversation(conversation_id: str, payload: ConversationTitleUpdate) -> dict[str, Any]:
    ensure_conversation(conversation_id)
    db.update_conversation_title(conversation_id, payload.title)
    return {"conversation": db.get_conversation(conversation_id)}


@app.delete("/api/conversations/{conversation_id}")
def delete_conversation(conversation_id: str) -> dict[str, Any]:
    ensure_conversation(conversation_id)
    db.delete_conversation(conversation_id)
    return {"ok": True}


@app.get("/api/conversations/{conversation_id}/messages")
def list_messages(conversation_id: str) -> dict[str, Any]:
    ensure_conversation(conversation_id)
    return {"messages": db.list_messages(conversation_id)}


@app.post("/api/conversations/{conversation_id}/run")
def run_conversation(conversation_id: str, payload: RunRequest) -> dict[str, Any]:
    conversation = ensure_conversation(conversation_id)
    user_message = db.add_message(conversation_id, "user", payload.task)
    if conversation["title"] == "新对话":
        db.update_conversation_title(conversation_id, payload.task.strip().replace("\n", " ")[:40] or "新对话")

    try:
        if payload.mode == "project":
            if not payload.workspace_path:
                raise WorkspaceError("项目模式下请先打开一个文件夹")
            result = run_project_agent(
                conversation_id,
                payload.task,
                payload.max_history_messages,
                payload.approval_mode,
                payload.workspace_path,
            )
        else:
            result = run_plain_chat(conversation_id, payload.max_history_messages)
        assistant_message = db.add_message(
            conversation_id,
            "assistant",
            result["final_answer"],
            {
                "steps": result["steps"],
                "mode": payload.mode,
                "workspace_path": payload.workspace_path,
                "changed_files": result["changed_files"],
            },
        )
        return {
            "user_message": user_message,
            "assistant_message": assistant_message,
            "result": result,
        }
    except Exception as exc:
        error_message = db.add_message(
            conversation_id,
            "error",
            str(exc),
            {"error_type": exc.__class__.__name__},
        )
        raise HTTPException(
            status_code=500,
            detail={
                "message": str(exc),
                "error_message": error_message,
            },
        )


@app.post("/api/tool-demo")
def tool_demo() -> dict[str, Any]:
    sandbox = SandboxClient(config.sandbox_url)
    result = {
        "shell_exec": sandbox.shell_exec("pwd && ls -la | head"),
        "file_write": sandbox.file_write("/home/gem/app_demo.txt", "hello from aio agent app\n"),
        "file_read": sandbox.file_read("/home/gem/app_demo.txt"),
        "browser_navigate": sandbox.browser_navigate("https://example.com"),
    }
    return {"result": result, "result_json": json.dumps(result, ensure_ascii=False, indent=2)}
