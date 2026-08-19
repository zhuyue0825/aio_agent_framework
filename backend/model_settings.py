from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace
from pathlib import Path
from threading import RLock
from typing import Any, Literal
from urllib.parse import urlsplit

from agent_framework.config import AgentConfig


ModelProvider = Literal["local", "remote"]

DEFAULT_REMOTE_API_BASE = "https://api.deepseek.com"
DEFAULT_REMOTE_MODEL = "deepseek-v4-flash"
DEFAULT_LOCAL_API_BASE = "http://host.docker.internal:8010/v1"
DEFAULT_LOCAL_MODEL = "local-deepseek-r1-distill-qwen-1.5b"


def normalize_api_base(value: str) -> str:
    normalized = value.strip().rstrip("/")
    parsed = urlsplit(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("模型接口地址必须是有效的 http:// 或 https:// URL")
    if parsed.username or parsed.password:
        raise ValueError("模型接口地址中不能包含用户名或密码")
    return normalized


def normalize_model_name(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("模型名称不能为空")
    if len(normalized) > 200:
        raise ValueError("模型名称不能超过 200 个字符")
    return normalized


@dataclass(frozen=True)
class ModelProfile:
    api_base: str
    model_name: str
    api_key: str | None = None


@dataclass(frozen=True)
class ModelSettings:
    active_provider: ModelProvider
    remote: ModelProfile
    local: ModelProfile


class ModelSettingsStore:
    def __init__(self, path: Path, base_config: AgentConfig | None = None) -> None:
        self.path = path
        self.base_config = base_config or AgentConfig.from_env()
        self._lock = RLock()
        self._settings = self._load_or_default()

    @classmethod
    def from_env(cls, project_root: Path) -> "ModelSettingsStore":
        configured_path = os.environ.get("MODEL_SETTINGS_PATH")
        path = Path(configured_path).expanduser() if configured_path else project_root / "data" / "model-settings.json"
        return cls(path=path)

    def _default_settings(self) -> ModelSettings:
        provider = os.environ.get("MODEL_PROVIDER", self.base_config.model_provider).strip().lower()
        active_provider: ModelProvider = "local" if provider == "local" else "remote"
        return ModelSettings(
            active_provider=active_provider,
            remote=ModelProfile(
                api_base=normalize_api_base(
                    os.environ.get("MODEL_REMOTE_API_BASE", self.base_config.model_api_base)
                ),
                model_name=normalize_model_name(
                    os.environ.get("MODEL_REMOTE_NAME", self.base_config.model_name)
                ),
                api_key=os.environ.get("MODEL_REMOTE_API_KEY") or self.base_config.model_api_key,
            ),
            local=ModelProfile(
                api_base=normalize_api_base(
                    os.environ.get("LOCAL_MODEL_API_BASE", DEFAULT_LOCAL_API_BASE)
                ),
                model_name=normalize_model_name(
                    os.environ.get("LOCAL_MODEL_NAME", DEFAULT_LOCAL_MODEL)
                ),
            ),
        )

    def _load_or_default(self) -> ModelSettings:
        defaults = self._default_settings()
        if not self.path.exists():
            return defaults
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            active_provider: ModelProvider = "local" if payload.get("active_provider") == "local" else "remote"
            remote = payload.get("remote") if isinstance(payload.get("remote"), dict) else {}
            local = payload.get("local") if isinstance(payload.get("local"), dict) else {}
            return ModelSettings(
                active_provider=active_provider,
                remote=ModelProfile(
                    api_base=normalize_api_base(str(remote.get("api_base") or defaults.remote.api_base)),
                    model_name=normalize_model_name(str(remote.get("model_name") or defaults.remote.model_name)),
                    api_key=str(remote["api_key"]).strip() if remote.get("api_key") else defaults.remote.api_key,
                ),
                local=ModelProfile(
                    api_base=normalize_api_base(str(local.get("api_base") or defaults.local.api_base)),
                    model_name=normalize_model_name(str(local.get("model_name") or defaults.local.model_name)),
                ),
            )
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return defaults

    def snapshot(self) -> ModelSettings:
        with self._lock:
            return self._settings

    def active_config(self) -> AgentConfig:
        settings = self.snapshot()
        profile = settings.local if settings.active_provider == "local" else settings.remote
        return replace(
            self.base_config,
            model_provider=settings.active_provider,
            model_api_base=profile.api_base,
            model_api_key=profile.api_key,
            model_name=profile.model_name,
        )

    def public_view(self) -> dict[str, Any]:
        settings = self.snapshot()
        active = settings.local if settings.active_provider == "local" else settings.remote
        return {
            "active_provider": settings.active_provider,
            "active_model_name": active.model_name,
            "remote": {
                "api_base": settings.remote.api_base,
                "model_name": settings.remote.model_name,
                "api_key_configured": bool(settings.remote.api_key),
            },
            "local": {
                "api_base": settings.local.api_base,
                "model_name": settings.local.model_name,
            },
        }

    def update(
        self,
        *,
        active_provider: ModelProvider,
        remote_api_base: str,
        remote_model_name: str,
        local_api_base: str,
        local_model_name: str,
        remote_api_key: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            current = self._settings
            next_key = remote_api_key.strip() if remote_api_key and remote_api_key.strip() else current.remote.api_key
            next_settings = ModelSettings(
                active_provider=active_provider,
                remote=ModelProfile(
                    api_base=normalize_api_base(remote_api_base),
                    model_name=normalize_model_name(remote_model_name),
                    api_key=next_key,
                ),
                local=ModelProfile(
                    api_base=normalize_api_base(local_api_base),
                    model_name=normalize_model_name(local_model_name),
                ),
            )
            self._persist(next_settings)
            self._settings = next_settings
            return self.public_view()

    def _persist(self, settings: ModelSettings) -> None:
        payload = {
            "version": 1,
            "active_provider": settings.active_provider,
            "remote": {
                "api_base": settings.remote.api_base,
                "model_name": settings.remote.model_name,
                "api_key": settings.remote.api_key,
            },
            "local": {
                "api_base": settings.local.api_base,
                "model_name": settings.local.model_name,
            },
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.chmod(temporary, 0o600)
        temporary.replace(self.path)
        os.chmod(self.path, 0o600)
