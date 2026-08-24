from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable

import httpx

from .config import AgentConfig


CancelCheck = Callable[[], bool]
AbortRegistrar = Callable[[Callable[[], None]], Callable[[], None]]
TokenCallback = Callable[[str], None]


@dataclass(frozen=True)
class ModelUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


@dataclass(frozen=True)
class ModelCompletion:
    message: dict[str, Any]
    usage: ModelUsage
    provider: str
    model_name: str
    request_count: int
    latency_ms: int


class ModelApiError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int | None = None, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.retryable = retryable


class ModelTimeoutError(ModelApiError):
    def __init__(self) -> None:
        super().__init__("MODEL_TIMEOUT", "Model API request timed out", retryable=True)


class ModelCancelledError(ModelApiError):
    def __init__(self) -> None:
        super().__init__("MODEL_CANCELLED", "Model API request was cancelled")


def _usage_from(payload: dict[str, Any]) -> ModelUsage:
    raw = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
    prompt = raw.get("prompt_tokens")
    completion = raw.get("completion_tokens")
    total = raw.get("total_tokens")
    return ModelUsage(
        input_tokens=prompt if isinstance(prompt, int) else None,
        output_tokens=completion if isinstance(completion, int) else None,
        total_tokens=total if isinstance(total, int) else None,
    )


def _retry_after_seconds(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return max(0.0, (parsed - datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None


def _classify_http_error(response: httpx.Response) -> ModelApiError:
    status = response.status_code
    try:
        body = response.json()
    except (json.JSONDecodeError, ValueError):
        body = {}
    raw_error = body.get("error") if isinstance(body, dict) else None
    detail = raw_error.get("message") if isinstance(raw_error, dict) else None
    provider_code = (
        str(raw_error.get("code") or raw_error.get("type") or "").lower()
        if isinstance(raw_error, dict)
        else ""
    )
    safe_detail = str(detail or "upstream request failed")[:500]
    quota_hint = f"{provider_code} {safe_detail.lower()}"
    if status in {401, 403}:
        return ModelApiError("MODEL_AUTHENTICATION_FAILED", safe_detail, status_code=status)
    if status == 402 or (
        status == 429
        and any(
            marker in quota_hint
            for marker in ("insufficient_quota", "insufficient_balance", "quota_exceeded", "billing")
        )
    ):
        return ModelApiError("MODEL_QUOTA_EXCEEDED", safe_detail, status_code=status)
    if status == 429:
        return ModelApiError("MODEL_RATE_LIMITED", safe_detail, status_code=status, retryable=True)
    if status in {502, 503, 504}:
        return ModelApiError("MODEL_SERVICE_UNAVAILABLE", safe_detail, status_code=status, retryable=True)
    if status >= 500:
        return ModelApiError("MODEL_SERVICE_ERROR", safe_detail, status_code=status)
    return ModelApiError("MODEL_INVALID_REQUEST", safe_detail, status_code=status)


class OpenAICompatibleModel:
    """OpenAI-compatible streaming client with retries, usage accounting and cancellation."""

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
        *,
        should_cancel: CancelCheck | None = None,
        register_abort: AbortRegistrar | None = None,
        on_token: TokenCallback | None = None,
    ) -> ModelCompletion:
        payload: dict[str, Any] = {
            "model": self.config.model_name,
            "messages": messages,
            "temperature": self.config.temperature if temperature is None else temperature,
            "top_p": top_p,
            "stream": True,
            "stream_options": {"include_usage": True},
            "max_tokens": max_tokens,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        headers = {"Authorization": f"Bearer {self.config.model_api_key}"} if self.config.model_api_key else {}
        cancel_check = should_cancel or (lambda: False)
        token_callback = on_token or (lambda _token: None)
        started = time.monotonic()
        attempts = self.config.model_max_retries + 1
        last_error: ModelApiError | None = None

        for attempt in range(attempts):
            self._raise_if_cancelled(cancel_check)
            emitted = False
            emitted_flag = [False]

            def emit_token(token: str) -> None:
                emitted_flag[0] = True
                token_callback(token)
            client = httpx.Client(
                timeout=httpx.Timeout(self.config.model_timeout_seconds),
                follow_redirects=False,
            )
            unregister = register_abort(client.close) if register_abort else (lambda: None)
            try:
                with client.stream(
                    "POST",
                    f"{self.config.model_api_base.rstrip('/')}/chat/completions",
                    json=payload,
                    headers=headers,
                ) as response:
                    if response.status_code >= 400:
                        response.read()
                        error = _classify_http_error(response)
                        retry_after = _retry_after_seconds(response.headers.get("Retry-After"))
                        if error.retryable and attempt + 1 < attempts:
                            last_error = error
                            self._wait_before_retry(attempt, retry_after, cancel_check)
                            continue
                        raise error

                    content_type = response.headers.get("content-type", "")
                    if "text/event-stream" not in content_type:
                        response.read()
                        try:
                            decoded = response.json()
                        except (json.JSONDecodeError, ValueError) as exc:
                            raise ModelApiError(
                                "MODEL_INVALID_RESPONSE",
                                "Model API returned invalid JSON",
                            ) from exc
                        if not isinstance(decoded, dict):
                            raise ModelApiError("MODEL_INVALID_RESPONSE", "Model API returned an invalid payload")
                        completion = self._parse_non_streaming(decoded)
                        return ModelCompletion(
                            message=completion.message,
                            usage=completion.usage,
                            provider=self.config.model_provider,
                            model_name=self.config.model_name,
                            request_count=attempt + 1,
                            latency_ms=round((time.monotonic() - started) * 1000),
                        )

                    message, usage, emitted = self._read_stream(response, cancel_check, emit_token)
                    return ModelCompletion(
                        message=message,
                        usage=usage,
                        provider=self.config.model_provider,
                        model_name=self.config.model_name,
                        request_count=attempt + 1,
                        latency_ms=round((time.monotonic() - started) * 1000),
                    )
            except ModelCancelledError:
                raise
            except httpx.TimeoutException as exc:
                emitted = emitted or emitted_flag[0]
                if cancel_check():
                    raise ModelCancelledError() from exc
                last_error = ModelTimeoutError()
                if emitted or attempt + 1 >= attempts:
                    raise last_error from exc
                self._wait_before_retry(attempt, None, cancel_check)
            except httpx.TransportError as exc:
                emitted = emitted or emitted_flag[0]
                if cancel_check():
                    raise ModelCancelledError() from exc
                last_error = ModelApiError(
                    "MODEL_SERVICE_UNAVAILABLE",
                    "Unable to reach model service",
                    retryable=True,
                )
                if emitted or attempt + 1 >= attempts:
                    raise last_error from exc
                self._wait_before_retry(attempt, None, cancel_check)
            finally:
                unregister()
                client.close()

        raise last_error or ModelApiError("MODEL_SERVICE_ERROR", "Model request failed")

    def _parse_non_streaming(self, payload: dict[str, Any]) -> ModelCompletion:
        if "error" in payload:
            raise ModelApiError("MODEL_SERVICE_ERROR", "Model API returned an error")
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise ModelApiError("MODEL_INVALID_RESPONSE", "Model API response missing choices")
        message = choices[0].get("message")
        if not isinstance(message, dict):
            raise ModelApiError("MODEL_INVALID_RESPONSE", "Model API choice missing message")
        return ModelCompletion(message=message, usage=_usage_from(payload), provider="", model_name="", request_count=1, latency_ms=0)

    def _read_stream(
        self,
        response: httpx.Response,
        should_cancel: CancelCheck,
        on_token: TokenCallback,
    ) -> tuple[dict[str, Any], ModelUsage, bool]:
        content_parts: list[str] = []
        role = "assistant"
        tool_calls: dict[int, dict[str, Any]] = {}
        usage = ModelUsage()
        emitted = False
        for line in response.iter_lines():
            self._raise_if_cancelled(should_cancel)
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if not data or data == "[DONE]":
                continue
            try:
                chunk = json.loads(data)
            except json.JSONDecodeError as exc:
                raise ModelApiError("MODEL_INVALID_RESPONSE", "Model stream contained invalid JSON") from exc
            next_usage = _usage_from(chunk)
            if next_usage.total_tokens is not None:
                usage = next_usage
            choices = chunk.get("choices")
            if not isinstance(choices, list) or not choices:
                continue
            delta = choices[0].get("delta") if isinstance(choices[0], dict) else None
            if not isinstance(delta, dict):
                continue
            if isinstance(delta.get("role"), str):
                role = delta["role"]
            content = delta.get("content")
            if isinstance(content, str) and content:
                emitted = True
                content_parts.append(content)
                on_token(content)
            for raw_call in delta.get("tool_calls") or []:
                if not isinstance(raw_call, dict):
                    continue
                index = raw_call.get("index", len(tool_calls))
                if not isinstance(index, int):
                    continue
                current = tool_calls.setdefault(
                    index,
                    {"id": "", "type": "function", "function": {"name": "", "arguments": ""}},
                )
                if isinstance(raw_call.get("id"), str):
                    current["id"] += raw_call["id"]
                function = raw_call.get("function")
                if isinstance(function, dict):
                    if isinstance(function.get("name"), str):
                        current["function"]["name"] += function["name"]
                    if isinstance(function.get("arguments"), str):
                        current["function"]["arguments"] += function["arguments"]

        if not content_parts and not tool_calls:
            raise ModelApiError("MODEL_INVALID_RESPONSE", "Model stream returned no assistant message")
        message: dict[str, Any] = {"role": role, "content": "".join(content_parts)}
        if tool_calls:
            message["tool_calls"] = [tool_calls[index] for index in sorted(tool_calls)]
        return message, usage, emitted

    def _wait_before_retry(self, attempt: int, retry_after: float | None, should_cancel: CancelCheck) -> None:
        base = min(
            self.config.model_retry_initial_seconds * (2**attempt),
            self.config.model_retry_max_seconds,
        )
        delay = retry_after if retry_after is not None else base * random.uniform(0.75, 1.25)
        deadline = time.monotonic() + min(delay, self.config.model_retry_max_seconds)
        while time.monotonic() < deadline:
            self._raise_if_cancelled(should_cancel)
            time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))

    def _raise_if_cancelled(self, should_cancel: CancelCheck) -> None:
        if should_cancel():
            raise ModelCancelledError()
