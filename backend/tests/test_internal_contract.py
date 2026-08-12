from __future__ import annotations

from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

from backend.main import INTERNAL_SERVICE_TOKEN, app, cancellations


client = TestClient(app)
AUTH_HEADERS = {"X-Internal-Token": INTERNAL_SERVICE_TOKEN}


def test_internal_health_requires_service_token() -> None:
    assert client.get("/internal/v1/health").status_code == 401

    response = client.get("/internal/v1/health", headers=AUTH_HEADERS)
    assert response.status_code == 200
    assert response.json()["service"] == "aio-agent-execution-service"
    assert response.json()["supports_projects"] is True


def test_agent_run_accepts_history_and_propagates_trace_id() -> None:
    run_id = uuid4()
    request = {
        "run_id": str(run_id),
        "task": "继续回答",
        "mode": "chat",
        "history": [{"role": "user", "content": "上一轮问题"}],
        "approval_mode": "auto",
        "max_steps": 8,
        "trace_id": "trace-contract-001",
    }
    result = {"final_answer": "契约正常", "steps": 1, "changed_files": []}

    with patch("backend.main.run_plain_chat", return_value=result) as run_plain_chat:
        response = client.post("/internal/v1/agent/runs", json=request, headers=AUTH_HEADERS)

    assert response.status_code == 200
    assert response.json() == {**result, "trace_id": "trace-contract-001"}
    args = run_plain_chat.call_args.args
    assert args[0] == "继续回答"
    assert [(message.role, message.content) for message in args[1]] == [("user", "上一轮问题")]


def test_cancel_endpoint_sets_cooperative_flag() -> None:
    run_id = uuid4()
    cancellations.begin(run_id)
    try:
        response = client.delete(f"/internal/v1/agent/runs/{run_id}", headers=AUTH_HEADERS)
        assert response.status_code == 200
        assert response.json()["active"] is True
        assert cancellations.is_cancelled(run_id) is True
    finally:
        cancellations.finish(run_id)


def test_workspace_contract_uses_internal_paths(tmp_path: Path) -> None:
    (tmp_path / "demo.py").write_text("print('before')\n", encoding="utf-8")

    opened = client.post(
        "/internal/v1/workspaces/open",
        json={"path": str(tmp_path)},
        headers=AUTH_HEADERS,
    )
    assert opened.status_code == 200
    assert opened.json()["workspace"]["root"] == str(tmp_path.resolve())

    saved = client.put(
        "/internal/v1/workspaces/file",
        json={"root": str(tmp_path), "path": "demo.py", "content": "print('after')\n"},
        headers=AUTH_HEADERS,
    )
    assert saved.status_code == 200
    assert saved.json()["file"]["content"] == "print('after')\n"
    assert (tmp_path / "demo.py").read_text(encoding="utf-8") == "print('after')\n"
