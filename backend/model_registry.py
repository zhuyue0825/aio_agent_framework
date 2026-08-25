from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, replace
from pathlib import Path
from threading import RLock
from time import monotonic
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from agent_framework.config import AgentConfig

from .model_settings import ModelProvider, ModelSettingsStore, normalize_api_base, normalize_model_name


DEFAULT_LOCAL_MODEL_ID = "local:minimind-64m"
DEFAULT_REMOTE_MODEL_ID = "remote:deepseek"


def public_model_name(value: str) -> str:
    """Keep repository-style IDs while hiding absolute/local filesystem paths."""
    normalized = value.strip().replace("\\", "/")
    if (
        normalized.startswith(("/", "~/", "../", "./"))
        or re.match(r"^[a-zA-Z]:/", normalized)
        or "/../" in normalized
    ):
        return normalized.rstrip("/").rsplit("/", 1)[-1] or "local-model"
    return normalized


class ModelRegistryError(ValueError):
    pass


class ModelNotFoundError(ModelRegistryError):
    pass


class ModelUnavailableError(ModelRegistryError):
    pass


@dataclass(frozen=True)
class RegisteredModel:
    model_id: str
    provider: ModelProvider
    display_name: str
    model_name: str
    source: str
    available: bool
    installed: bool
    unavailable_reason: str | None = None
    architecture: str | None = None
    api_base: str | None = None
    api_key: str | None = None

    def public_view(self) -> dict[str, Any]:
        return {
            "id": self.model_id,
            "provider": self.provider,
            "display_name": self.display_name,
            "model_name": public_model_name(self.model_name),
            "source": self.source,
            "available": self.available,
            "installed": self.installed,
            "unavailable_reason": self.unavailable_reason,
            "architecture": self.architecture,
        }


class ModelRegistry:
    """Server-side registry for configured, discovered and downloaded models.

    Only configured roots are scanned. Paths and credentials never leave this service.
    A downloaded model is visible, but it is selectable only when a compatible
    OpenAI-style runtime has registered it (or a trusted manifest supplies one).
    """

    def __init__(
        self,
        settings: ModelSettingsStore,
        *,
        scan_roots: list[Path],
        manifest_path: Path | None,
        runtime_endpoints: list[str],
        cache_seconds: float = 5.0,
        probe_timeout_seconds: float = 0.35,
        max_models: int = 200,
    ) -> None:
        self.settings = settings
        self.scan_roots = tuple(self._safe_roots(scan_roots))
        self.manifest_path = manifest_path
        self.runtime_endpoints = tuple(runtime_endpoints)
        self.cache_seconds = max(0.0, cache_seconds)
        self.probe_timeout_seconds = max(0.05, probe_timeout_seconds)
        self.max_models = max(1, max_models)
        self._lock = RLock()
        self._cached_at = 0.0
        self._cached: tuple[RegisteredModel, ...] = ()

    @classmethod
    def from_env(cls, project_root: Path, settings: ModelSettingsStore) -> "ModelRegistry":
        raw_roots = os.environ.get("MODEL_SCAN_ROOTS", "").strip()
        if raw_roots:
            roots = [Path(item).expanduser() for item in raw_roots.split(os.pathsep) if item.strip()]
        else:
            roots = [project_root / "minimind" / "out", Path.home() / "Models"]

        configured_manifest = os.environ.get("MODEL_REGISTRY_MANIFEST", "").strip()
        manifest = (
            Path(configured_manifest).expanduser()
            if configured_manifest
            else project_root / "backend" / "model-registry.default.json"
        )
        runtime_endpoints = [
            item.strip()
            for item in os.environ.get("MODEL_RUNTIME_ENDPOINTS", "").split(",")
            if item.strip()
        ]
        return cls(
            settings,
            scan_roots=roots,
            manifest_path=manifest,
            runtime_endpoints=runtime_endpoints,
            cache_seconds=float(os.environ.get("MODEL_REGISTRY_CACHE_SECONDS", "5")),
            probe_timeout_seconds=float(os.environ.get("MODEL_REGISTRY_PROBE_TIMEOUT_SECONDS", "0.35")),
            max_models=int(os.environ.get("MODEL_SCAN_MAX_MODELS", "200")),
        )

    def public_view(self, *, refresh: bool = False) -> dict[str, Any]:
        models = self.models(refresh=refresh)
        return {
            "models": [model.public_view() for model in models],
            "default_model_ids": {
                "local": DEFAULT_LOCAL_MODEL_ID,
                "remote": DEFAULT_REMOTE_MODEL_ID,
            },
            "scan_root_count": len(self.scan_roots),
        }

    def models(self, *, refresh: bool = False) -> tuple[RegisteredModel, ...]:
        now = monotonic()
        with self._lock:
            if not refresh and self._cached and now - self._cached_at < self.cache_seconds:
                return self._cached
            models = self._discover()
            self._cached = tuple(sorted(models.values(), key=self._sort_key))
            self._cached_at = now
            return self._cached

    def invalidate(self) -> None:
        with self._lock:
            self._cached_at = 0.0
            self._cached = ()

    def config_for(self, model_id: str | None, fallback_provider: ModelProvider = "local") -> AgentConfig:
        selected_id = model_id or self.default_model_id(fallback_provider)
        model = next((item for item in self.models() if item.model_id == selected_id), None)
        if model is None:
            raise ModelNotFoundError("所选模型不存在，请刷新模型列表后重试")
        if not model.available or not model.api_base:
            raise ModelUnavailableError(model.unavailable_reason or "所选模型当前不可用")
        return replace(
            self.settings.base_config,
            model_provider=model.provider,
            model_api_base=model.api_base,
            model_api_key=model.api_key,
            model_name=model.model_name,
        )

    def default_model_id(self, provider: ModelProvider) -> str:
        return DEFAULT_LOCAL_MODEL_ID if provider == "local" else DEFAULT_REMOTE_MODEL_ID

    def _discover(self) -> dict[str, RegisteredModel]:
        settings = self.settings.snapshot()
        models: dict[str, RegisteredModel] = {
            DEFAULT_LOCAL_MODEL_ID: RegisteredModel(
                model_id=DEFAULT_LOCAL_MODEL_ID,
                provider="local",
                display_name="MiniMind 64M",
                model_name=settings.local.model_name,
                source="configured",
                available=True,
                installed=True,
                api_base=settings.local.api_base,
            ),
            DEFAULT_REMOTE_MODEL_ID: RegisteredModel(
                model_id=DEFAULT_REMOTE_MODEL_ID,
                provider="remote",
                display_name="DeepSeek",
                model_name=settings.remote.model_name,
                source="configured",
                available=bool(settings.remote.api_key),
                installed=True,
                unavailable_reason=None if settings.remote.api_key else "管理员尚未配置 API Key",
                api_base=settings.remote.api_base,
                api_key=settings.remote.api_key,
            ),
        }
        for model in self._manifest_models():
            models[model.model_id] = model
        for model in self._runtime_models():
            models.setdefault(model.model_id, model)
        running_names = {
            model.model_name.casefold()
            for model in models.values()
            if model.available and model.api_base
        }
        for model in self._downloaded_models(existing_ids=set(models)):
            if model.model_name.casefold() not in running_names:
                models.setdefault(model.model_id, model)
        return models

    def _manifest_models(self) -> list[RegisteredModel]:
        if self.manifest_path is None or not self.manifest_path.is_file():
            return []
        try:
            payload = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return []
        entries = payload.get("models") if isinstance(payload, dict) else None
        if not isinstance(entries, list):
            return []

        settings = self.settings.snapshot()
        result: list[RegisteredModel] = []
        for raw in entries[: self.max_models]:
            if not isinstance(raw, dict):
                continue
            try:
                model_id = self._model_id(raw.get("id"))
                provider: ModelProvider = "remote" if raw.get("provider") == "remote" else "local"
                profile = raw.get("profile")
                if profile == "local":
                    api_base = settings.local.api_base
                    model_name = settings.local.model_name
                    api_key = None
                elif profile == "remote":
                    api_base = settings.remote.api_base
                    model_name = settings.remote.model_name
                    api_key = settings.remote.api_key
                else:
                    api_base_env = str(raw.get("api_base_env") or "").strip()
                    configured_api_base = os.environ.get(api_base_env) if api_base_env else None
                    api_base = normalize_api_base(
                        os.path.expandvars(str(configured_api_base or raw.get("api_base") or "")),
                        allow_private=provider == "local",
                        allowed_hosts=(
                            self.settings.local_allowed_hosts
                            if provider == "local"
                            else self.settings.remote_allowed_hosts
                        ),
                    )
                    model_name = normalize_model_name(str(raw.get("model_name") or ""))
                    key_env = str(raw.get("api_key_env") or "").strip()
                    api_key = os.environ.get(key_env) if key_env else None

                missing = self._missing_required_files(raw.get("required_files"))
                available = not missing and (provider == "local" or bool(api_key))
                reason = None
                if missing:
                    reason = "未找到完整模型权重"
                elif provider == "remote" and not api_key:
                    reason = "管理员尚未配置 API Key"
                elif available and bool(raw.get("probe", False)):
                    health_path = str(raw.get("health_path") or "/models")
                    if not self._probe(api_base, health_path):
                        available = False
                        reason = "模型已安装，但推理服务未启动"
                result.append(RegisteredModel(
                    model_id=model_id,
                    provider=provider,
                    display_name=normalize_model_name(str(raw.get("display_name") or model_name)),
                    model_name=model_name,
                    source="manifest",
                    available=available,
                    installed=not missing,
                    unavailable_reason=reason,
                    architecture=self._optional_text(raw.get("architecture")),
                    api_base=api_base,
                    api_key=api_key,
                ))
            except (ValueError, TypeError):
                continue
        return result

    def _runtime_models(self) -> list[RegisteredModel]:
        result: list[RegisteredModel] = []
        used_ids: set[str] = set()
        for raw_endpoint in self.runtime_endpoints:
            try:
                api_base = normalize_api_base(
                    raw_endpoint,
                    allowed_hosts=self.settings.local_allowed_hosts,
                )
                response = httpx.get(
                    api_base.rstrip("/") + "/models",
                    timeout=self.probe_timeout_seconds,
                    follow_redirects=False,
                )
                response.raise_for_status()
                payload = response.json()
                entries = payload.get("data") if isinstance(payload, dict) else None
                if not isinstance(entries, list):
                    continue
                for entry in entries[: self.max_models - len(result)]:
                    if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
                        continue
                    model_name = normalize_model_name(entry["id"])
                    public_name = public_model_name(model_name)
                    base_id = "local:" + self._slug(public_name)
                    model_id = self._unique_id(base_id, used_ids)
                    used_ids.add(model_id)
                    result.append(RegisteredModel(
                        model_id=model_id,
                        provider="local",
                        display_name=public_name,
                        model_name=model_name,
                        source="runtime",
                        available=True,
                        installed=True,
                        api_base=api_base,
                    ))
            except (httpx.HTTPError, ValueError, TypeError, json.JSONDecodeError):
                continue
        return result

    def _downloaded_models(self, *, existing_ids: set[str]) -> list[RegisteredModel]:
        result: list[RegisteredModel] = []
        used_ids = set(existing_ids)
        for root in self.scan_roots:
            if not root.is_dir():
                continue
            try:
                config_paths = root.rglob("config.json")
                for config_path in config_paths:
                    if len(result) >= self.max_models:
                        return result
                    model = self._hugging_face_model(config_path.parent, config_path, used_ids)
                    if model is not None:
                        used_ids.add(model.model_id)
                        result.append(model)
                for gguf_path in root.rglob("*.gguf"):
                    if len(result) >= self.max_models:
                        return result
                    if not gguf_path.is_file():
                        continue
                    base_id = "downloaded:" + self._slug(gguf_path.stem)
                    model_id = self._unique_id(base_id, used_ids)
                    used_ids.add(model_id)
                    result.append(RegisteredModel(
                        model_id=model_id,
                        provider="local",
                        display_name=gguf_path.stem,
                        model_name=gguf_path.stem,
                        source="scan",
                        available=False,
                        installed=True,
                        unavailable_reason="已检测到 GGUF 权重，请先启动兼容的本地推理服务",
                        architecture="GGUF",
                    ))
            except OSError:
                continue
        return result

    def _hugging_face_model(
        self,
        directory: Path,
        config_path: Path,
        used_ids: set[str],
    ) -> RegisteredModel | None:
        try:
            if config_path.stat().st_size > 2_000_000:
                return None
            config = json.loads(config_path.read_text(encoding="utf-8"))
            if not isinstance(config, dict):
                return None
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return None
        raw_name = config.get("_name_or_path")
        model_name = public_model_name(normalize_model_name(
            raw_name if isinstance(raw_name, str) and raw_name.strip() else directory.name
        ))
        architecture = None
        architectures = config.get("architectures")
        if isinstance(architectures, list) and architectures and isinstance(architectures[0], str):
            architecture = architectures[0][:200]

        complete, reason = self._weights_complete(directory)
        base_id = "downloaded:" + self._slug(model_name)
        model_id = self._unique_id(base_id, used_ids)
        return RegisteredModel(
            model_id=model_id,
            provider="local",
            display_name=directory.name,
            model_name=model_name,
            source="scan",
            available=False,
            installed=complete,
            unavailable_reason=(
                "模型已下载，请先启动兼容的本地推理服务"
                if complete
                else reason
            ),
            architecture=architecture,
        )

    def _weights_complete(self, directory: Path) -> tuple[bool, str]:
        try:
            if next(directory.rglob("*.incomplete"), None) is not None:
                return False, "模型仍在下载中"
            index_path = directory / "model.safetensors.index.json"
            if index_path.is_file():
                payload = json.loads(index_path.read_text(encoding="utf-8"))
                weight_map = payload.get("weight_map") if isinstance(payload, dict) else None
                if not isinstance(weight_map, dict) or not weight_map:
                    return False, "模型分片索引无效"
                shards = {str(value) for value in weight_map.values()}
                if all((directory / shard).is_file() for shard in shards):
                    return True, ""
                return False, "模型分片尚未下载完整"
            if (directory / "model.safetensors").is_file() or (directory / "pytorch_model.bin").is_file():
                return True, ""
            if (directory / "adapter_config.json").is_file():
                return False, "仅检测到 LoRA 适配器，还需要对应基础模型"
            return False, "未找到完整模型权重"
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return False, "无法验证模型权重完整性"

    def _missing_required_files(self, raw_files: Any) -> list[str]:
        if not isinstance(raw_files, list):
            return []
        missing: list[str] = []
        for raw in raw_files:
            if not isinstance(raw, str) or not raw.strip():
                missing.append("invalid")
                continue
            relative = Path(os.path.expandvars(raw.strip()))
            if relative.is_absolute() or ".." in relative.parts:
                missing.append(raw)
                continue
            if not any((root / relative).is_file() for root in self.scan_roots):
                missing.append(raw)
        return missing

    def _probe(self, api_base: str, health_path: str) -> bool:
        parsed = urlsplit(api_base)
        if health_path.startswith("/"):
            url = urlunsplit((parsed.scheme, parsed.netloc, health_path, "", ""))
        else:
            url = api_base.rstrip("/") + "/" + health_path
        try:
            response = httpx.get(url, timeout=self.probe_timeout_seconds, follow_redirects=False)
            return response.status_code < 500
        except httpx.HTTPError:
            return False

    def _safe_roots(self, roots: list[Path]) -> list[Path]:
        result: list[Path] = []
        seen: set[Path] = set()
        for root in roots:
            try:
                resolved = root.resolve(strict=False)
            except OSError:
                continue
            if resolved == Path(resolved.anchor):
                continue
            if resolved not in seen:
                seen.add(resolved)
                result.append(resolved)
        return result

    def _model_id(self, value: Any) -> str:
        if not isinstance(value, str) or not re.fullmatch(r"[a-z0-9][a-z0-9:._/-]{2,199}", value):
            raise ValueError("invalid model id")
        return value

    def _slug(self, value: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
        if not slug:
            slug = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
        return slug[:160]

    def _unique_id(self, base_id: str, used_ids: set[str]) -> str:
        if base_id not in used_ids:
            return base_id
        suffix = 2
        while f"{base_id}-{suffix}" in used_ids:
            suffix += 1
        return f"{base_id}-{suffix}"

    def _optional_text(self, value: Any) -> str | None:
        return value[:200] if isinstance(value, str) and value.strip() else None

    def _sort_key(self, model: RegisteredModel) -> tuple[int, int, str]:
        provider_order = 1 if model.provider == "remote" else 0
        source_order = {"manifest": 0, "configured": 1, "runtime": 2, "scan": 3}.get(model.source, 4)
        return provider_order, source_order, model.display_name.lower()
