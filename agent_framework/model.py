from __future__ import annotations

import json
from typing import Any

from .config import AgentConfig
from .http_json import post_json


class OpenAICompatibleModel:
    """Minimal Chat Completions client with tool-call support."""

    def __init__(self, config: AgentConfig) -> None:
        if config.model_provider == "remote" and not config.model_api_key:
            raise RuntimeError("Missing MODEL_API_KEY or OPENAI_API_KEY.")
        self.config = config

    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 512,
        temperature: float | None = None,
        top_p: float = 0.8,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.config.model_name,
            "messages": messages,
            "temperature": self.config.temperature if temperature is None else temperature,
            "top_p": top_p,
            "stream": False,
            "max_tokens": max_tokens,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        headers = {"Authorization": f"Bearer {self.config.model_api_key}"} if self.config.model_api_key else {}
        response = post_json(
            f"{self.config.model_api_base.rstrip('/')}/chat/completions",
            payload,
            headers=headers,
            timeout=120,
        )
        if "error" in response:
            raise RuntimeError(f"Model API error: {json.dumps(response['error'], ensure_ascii=False)}")
        choices = response.get("choices")
        if not choices:
            raise RuntimeError(f"Model API response missing choices: {json.dumps(response, ensure_ascii=False)[:2000]}")
        if "message" not in choices[0]:
            raise RuntimeError(f"Model API choice missing message: {json.dumps(choices[0], ensure_ascii=False)[:2000]}")
        return response["choices"][0]["message"]
