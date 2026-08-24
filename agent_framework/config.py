from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class AgentConfig:
    sandbox_url: str = "http://127.0.0.1:8080"
    model_provider: str = "remote"
    model_api_base: str = "https://api.deepseek.com"
    model_api_key: str | None = None
    model_name: str = "deepseek-v4-flash"
    max_steps: int = 8
    temperature: float = 0.2
    model_timeout_seconds: float = 120.0
    model_max_retries: int = 3
    model_retry_initial_seconds: float = 0.5
    model_retry_max_seconds: float = 8.0
    history_token_budget: int = 8_000

    @classmethod
    def from_env(cls) -> "AgentConfig":
        return cls(
            sandbox_url=os.environ.get("AIO_SANDBOX_URL", cls.sandbox_url),
            model_provider=os.environ.get("MODEL_PROVIDER", cls.model_provider),
            model_api_base=os.environ.get("MODEL_API_BASE", cls.model_api_base),
            model_api_key=os.environ.get("MODEL_API_KEY") or os.environ.get("OPENAI_API_KEY"),
            model_name=os.environ.get("MODEL_NAME", cls.model_name),
            max_steps=int(os.environ.get("AGENT_MAX_STEPS", cls.max_steps)),
            temperature=float(os.environ.get("MODEL_TEMPERATURE", cls.temperature)),
            model_timeout_seconds=float(os.environ.get("MODEL_TIMEOUT_SECONDS", cls.model_timeout_seconds)),
            model_max_retries=int(os.environ.get("MODEL_MAX_RETRIES", cls.model_max_retries)),
            model_retry_initial_seconds=float(
                os.environ.get("MODEL_RETRY_INITIAL_SECONDS", cls.model_retry_initial_seconds)
            ),
            model_retry_max_seconds=float(os.environ.get("MODEL_RETRY_MAX_SECONDS", cls.model_retry_max_seconds)),
            history_token_budget=int(os.environ.get("AGENT_HISTORY_TOKEN_BUDGET", cls.history_token_budget)),
        )
