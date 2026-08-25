from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import httpx

from agent_framework.config import AgentConfig
from backend.model_registry import ModelRegistry, ModelUnavailableError, public_model_name
from backend.model_settings import ModelSettingsStore


def make_settings(tmp_path: Path) -> ModelSettingsStore:
    return ModelSettingsStore(
        tmp_path / "settings.json",
        AgentConfig(
            model_provider="remote",
            model_api_base="https://api.deepseek.com",
            model_api_key=None,
            model_name="deepseek-chat",
        ),
    )


def test_scanner_marks_incomplete_hugging_face_model_unavailable(tmp_path: Path) -> None:
    model_dir = tmp_path / "Qwen3-4B-Instruct-2507"
    model_dir.mkdir()
    (model_dir / "config.json").write_text(
        json.dumps({"_name_or_path": "Qwen/Qwen3-4B-Instruct-2507", "architectures": ["Qwen3ForCausalLM"]}),
        encoding="utf-8",
    )
    (model_dir / "model.safetensors.index.json").write_text(
        json.dumps({"weight_map": {"a": "model-00001-of-00002.safetensors", "b": "model-00002-of-00002.safetensors"}}),
        encoding="utf-8",
    )
    (model_dir / "model-00001-of-00002.safetensors").write_bytes(b"first")

    registry = ModelRegistry(
        make_settings(tmp_path),
        scan_roots=[tmp_path],
        manifest_path=None,
        runtime_endpoints=[],
        cache_seconds=0,
    )

    qwen = next(model for model in registry.models() if model.source == "scan")
    assert qwen.display_name == "Qwen3-4B-Instruct-2507"
    assert qwen.installed is False
    assert qwen.available is False
    assert qwen.unavailable_reason == "模型分片尚未下载完整"


def test_runtime_models_are_selectable_without_exposing_paths_or_keys(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    registry = ModelRegistry(
        settings,
        scan_roots=[tmp_path],
        manifest_path=None,
        runtime_endpoints=["http://localhost:8001/v1"],
        cache_seconds=0,
    )

    with patch(
        "backend.model_registry.httpx.get",
        return_value=httpx.Response(
            200,
            json={"data": [{"id": "Qwen/Qwen3-4B-Instruct-2507"}]},
            request=httpx.Request("GET", "http://localhost:8001/v1/models"),
        ),
    ):
        public = registry.public_view()
        model = next(item for item in public["models"] if item["source"] == "runtime")
        config = registry.config_for(model["id"])

    assert model["id"] == "local:qwen-qwen3-4b-instruct-2507"
    assert model["available"] is True
    assert config.model_api_base == "http://localhost:8001/v1"
    assert config.model_name == "Qwen/Qwen3-4B-Instruct-2507"
    assert "api_base" not in model
    assert "api_key" not in model


def test_manifest_requires_weights_and_live_runtime(tmp_path: Path) -> None:
    manifest = tmp_path / "registry.json"
    manifest.write_text(
        json.dumps({
            "models": [{
                "id": "local:custom",
                "provider": "local",
                "display_name": "Custom",
                "model_name": "custom",
                "api_base": "http://localhost:8998/v1",
                "required_files": ["custom/model.pth"],
                "probe": True,
                "health_path": "/docs",
            }]
        }),
        encoding="utf-8",
    )
    model_file = tmp_path / "custom" / "model.pth"
    model_file.parent.mkdir()
    model_file.write_bytes(b"weights")
    registry = ModelRegistry(
        make_settings(tmp_path),
        scan_roots=[tmp_path],
        manifest_path=manifest,
        runtime_endpoints=[],
        cache_seconds=60,
    )

    with patch("backend.model_registry.httpx.get", side_effect=httpx.ConnectError("offline")):
        model = next(item for item in registry.models() if item.model_id == "local:custom")

    assert model.installed is True
    assert model.available is False
    assert model.unavailable_reason == "模型已安装，但推理服务未启动"
    try:
        registry.config_for("local:custom")
    except ModelUnavailableError:
        pass
    else:
        raise AssertionError("offline manifest model must not be selectable")


def test_public_model_name_hides_local_absolute_paths() -> None:
    assert public_model_name("/Users/alice/Models/Qwen3-4B") == "Qwen3-4B"
    assert public_model_name(r"C:\\Models\\Qwen3-4B") == "Qwen3-4B"
    assert public_model_name("Qwen/Qwen3-4B-Instruct-2507") == "Qwen/Qwen3-4B-Instruct-2507"
