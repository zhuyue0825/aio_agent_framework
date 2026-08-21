from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from agent_framework.config import AgentConfig
from agent_framework.model import ModelCompletion, ModelUsage
from agent_framework.runtime import AgentRuntime
from agent_framework.tools import Tool, ToolRegistry, object_schema
from backend.main import AgentRunRequest, HistoryMessage, run_project_agent
from backend.redis_cancellation import RedisCancellationBridge
from backend.workspace import (
    WorkspaceError,
    WorkspaceTools,
    apply_workspace_changes,
    normalize_workspace_root,
    resolve_workspace_path,
)


class SequenceModel:
    def __init__(self, messages: list[dict[str, object]]) -> None:
        self.messages = iter(messages)

    def complete(self, *_args, **_kwargs) -> ModelCompletion:
        return ModelCompletion(
            message=next(self.messages),
            usage=ModelUsage(3, 2, 5),
            provider="remote",
            model_name="test-model",
            request_count=1,
            latency_ms=5,
        )


def test_invalid_tool_json_is_returned_to_model_instead_of_crashing() -> None:
    registry = ToolRegistry()
    registry.register(
        Tool(
            name="safe_tool",
            description="safe",
            parameters=object_schema({}, []),
            handler=lambda _args: {"success": True},
        )
    )
    model = SequenceModel(
        [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "bad-1", "function": {"name": "safe_tool", "arguments": "{"}}],
            },
            {"role": "assistant", "content": "已恢复"},
        ]
    )
    runtime = AgentRuntime(AgentConfig(model_api_key="key", max_steps=2), registry, model=model)  # type: ignore[arg-type]

    result = runtime.run("test")

    assert result.final_answer == "已恢复"
    assert result.model_request_count == 2
    assert any("invalid_tool_arguments" in str(message.get("content")) for message in result.messages)


def test_runtime_stops_at_configured_max_steps() -> None:
    registry = ToolRegistry()
    registry.register(
        Tool(
            name="safe_tool",
            description="safe",
            parameters=object_schema({}, []),
            handler=lambda _args: {"success": True},
        )
    )
    model = SequenceModel(
        [{"role": "assistant", "content": "", "tool_calls": [
            {"id": "call-1", "function": {"name": "safe_tool", "arguments": "{}"}}
        ]}]
    )

    result = AgentRuntime(AgentConfig(model_api_key="key", max_steps=1), registry, model=model).run("test")  # type: ignore[arg-type]

    assert result.steps == 1
    assert "Stopped after 1 steps" in result.final_answer


def test_workspace_symlink_cannot_escape_project(tmp_path: Path) -> None:
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "secret.txt").write_text("secret", encoding="utf-8")
    (root / "escape").symlink_to(outside, target_is_directory=True)

    try:
        resolve_workspace_path(root, "escape/secret.txt")
    except WorkspaceError as exc:
        assert "超出" in str(exc)
    else:
        raise AssertionError("symlink escape should be rejected")


def test_workspace_relative_path_rejects_absolute_and_parent_escape(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()

    for unsafe_path in (str(root / "inside.txt"), "../outside.txt"):
        try:
            resolve_workspace_path(root, unsafe_path, must_exist=False)
        except WorkspaceError:
            pass
        else:
            raise AssertionError(f"unsafe workspace path should be rejected: {unsafe_path}")


def test_workspace_root_rejects_sibling_with_same_prefix(tmp_path: Path, monkeypatch) -> None:
    allowed = tmp_path / "workspace"
    sibling = tmp_path / "workspace-private"
    allowed.mkdir()
    sibling.mkdir()
    monkeypatch.setenv("AIO_ALLOWED_WORKSPACE_ROOTS", str(allowed))

    try:
        normalize_workspace_root(str(sibling))
    except WorkspaceError as exc:
        assert "允许" in str(exc)
    else:
        raise AssertionError("a sibling that only shares the allowed prefix must be rejected")


def test_multi_tenant_workspace_rejects_another_owner_root(tmp_path: Path, monkeypatch) -> None:
    owner_a = "11111111-1111-1111-1111-111111111111"
    owner_b = "22222222-2222-2222-2222-222222222222"
    root_a = tmp_path / owner_a
    root_a.mkdir()
    monkeypatch.setenv("AIO_ALLOWED_WORKSPACE_ROOTS", str(tmp_path))
    monkeypatch.setenv("AIO_MULTI_TENANT_WORKSPACES", "true")

    assert normalize_workspace_root(str(root_a), owner_a) == root_a.resolve()
    try:
        normalize_workspace_root(str(root_a), owner_b)
    except WorkspaceError as exc:
        assert "允许" in str(exc)
    else:
        raise AssertionError("one tenant must not open another tenant's workspace")


def test_agent_changes_are_staged_until_hash_checked_confirmation(tmp_path: Path) -> None:
    target = tmp_path / "app.py"
    target.write_text("print('old')\n", encoding="utf-8")
    tools = WorkspaceTools(tmp_path)

    result = tools.apply_patch("app.py", "old", "new")

    assert result["success"] is True
    assert "-print('old')" in result["data"]["diff"]
    assert target.read_text(encoding="utf-8") == "print('old')\n"
    proposals = tools.proposals()
    assert apply_workspace_changes(tmp_path, proposals) == ["app.py"]
    assert target.read_text(encoding="utf-8") == "print('new')\n"


def test_staged_change_refuses_to_overwrite_a_newer_file(tmp_path: Path) -> None:
    target = tmp_path / "app.py"
    target.write_text("before\n", encoding="utf-8")
    tools = WorkspaceTools(tmp_path)
    tools.apply_patch("app.py", "before", "proposal")
    proposals = tools.proposals()
    target.write_text("changed elsewhere\n", encoding="utf-8")

    try:
        apply_workspace_changes(tmp_path, proposals)
    except WorkspaceError as exc:
        assert "发生变化" in str(exc)
    else:
        raise AssertionError("stale proposal should not overwrite a newer file")


def test_project_run_passes_trimmed_history_and_task_to_runtime(tmp_path: Path) -> None:
    request = AgentRunRequest(
        run_id=uuid4(),
        task="修改测试文件",
        mode="project",
        history=[HistoryMessage(role="user", content="先查看项目结构")],
        workspace_root=str(tmp_path),
    )
    runtime_result = SimpleNamespace(
        final_answer="完成",
        steps=1,
        model_provider="remote",
        model_name="test-model",
        model_request_count=1,
        input_tokens=10,
        output_tokens=2,
        model_latency_ms=5,
    )

    with (
        patch(
            "backend.main.model_settings.active_config",
            return_value=AgentConfig(model_api_key="test-key"),
        ),
        patch("backend.main.AgentRuntime.run", return_value=runtime_result) as run,
    ):
        result = run_project_agent(
            request,
            "trace-project",
            lambda: False,
            lambda _abort: lambda: None,
            lambda *_: None,
        )

    context = run.call_args.args[0]
    assert "先查看项目结构" in context
    assert "修改测试文件" in context
    assert result["final_answer"] == "完成"


def test_frontend_test_tool_installs_locked_dependencies_without_scripts(tmp_path: Path) -> None:
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "package.json").write_text(
        json.dumps({"scripts": {"test": "vitest run"}}),
        encoding="utf-8",
    )
    (frontend / "package-lock.json").write_text("{}\n", encoding="utf-8")

    commands = WorkspaceTools(tmp_path)._test_commands("frontend")

    assert commands[0] == (["npm", "ci", "--ignore-scripts", "--no-audit", "--no-fund"], "frontend")
    assert commands[1] == (["npm", "run", "test", "--", "--run"], "frontend")


def test_redis_password_is_passed_without_url_interpolation(monkeypatch) -> None:
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.setenv("REDIS_HOST", "redis")
    monkeypatch.setenv("REDIS_PORT", "6379")
    monkeypatch.setenv("REDIS_PASSWORD", "special@password/with+symbols")

    with (
        patch("backend.redis_cancellation.redis.Redis") as redis_client,
        patch("backend.redis_cancellation.Thread") as thread,
    ):
        bridge = RedisCancellationBridge(lambda _run_id: False)
        bridge.start()

    assert redis_client.call_args.kwargs["password"] == "special@password/with+symbols"
    thread.return_value.start.assert_called_once()
