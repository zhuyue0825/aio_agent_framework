from __future__ import annotations

import json
import stat
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from agent_framework.config import AgentConfig
from agent_framework.model import OpenAICompatibleModel
from backend.main import INTERNAL_SERVICE_TOKEN, app
from backend.model_settings import ModelSettingsStore


client = TestClient(app)
AUTH_HEADERS = {"X-Internal-Token": INTERNAL_SERVICE_TOKEN}


def make_store(path: Path) -> ModelSettingsStore:
    return ModelSettingsStore(
        path,
        AgentConfig(
            model_provider="remote",
            model_api_base="https://api.deepseek.com",
            model_api_key=None,
            model_name="deepseek-v4-flash",
        ),
    )


def settings_payload(**overrides: str) -> dict[str, str]:
    payload = {
        "active_provider": "remote",
        "remote_api_base": "https://api.deepseek.com",
        "remote_model_name": "deepseek-v4-flash",
        "remote_api_key": "sk-test-secret-never-return",
        "local_api_base": "http://host.docker.internal:8010/v1",
        "local_model_name": "local-deepseek",
    }
    payload.update(overrides)
    return payload


def test_store_persists_secret_without_exposing_it(tmp_path: Path) -> None:
    path = tmp_path / "model-settings.json"
    store = make_store(path)

    public = store.update(**settings_payload())

    assert public["active_provider"] == "remote"
    assert public["remote"]["api_key_configured"] is True
    assert "sk-test-secret-never-return" not in json.dumps(public)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600

    reloaded = make_store(path)
    assert reloaded.active_config().model_api_key == "sk-test-secret-never-return"


def test_internal_settings_endpoint_switches_to_keyless_local_model(tmp_path: Path) -> None:
    store = make_store(tmp_path / "model-settings.json")
    payload = settings_payload(active_provider="local")
    payload.pop("remote_api_key")

    with patch("backend.main.model_settings", store):
        response = client.put(
            "/internal/v1/model-settings",
            headers=AUTH_HEADERS,
            json=payload,
        )

    assert response.status_code == 200
    assert response.json()["active_provider"] == "local"
    assert store.active_config().model_provider == "local"
    assert store.active_config().model_api_key is None
    OpenAICompatibleModel(store.active_config())


def test_model_connection_test_does_not_return_credentials(tmp_path: Path) -> None:
    store = make_store(tmp_path / "model-settings.json")
    store.update(**settings_payload())

    with (
        patch("backend.main.model_settings", store),
        patch("backend.main.OpenAICompatibleModel.complete", return_value={"role": "assistant", "content": "OK"}),
    ):
        response = client.post("/internal/v1/model-settings/test", headers=AUTH_HEADERS)

    assert response.status_code == 200
    assert response.json()["response"] == "OK"
    assert "sk-test-secret-never-return" not in response.text
