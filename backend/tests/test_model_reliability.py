from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import patch

import httpx
import pytest

from agent_framework.config import AgentConfig
from agent_framework.model import ModelApiError, ModelCancelledError, OpenAICompatibleModel
from backend.main import RunCancellation


def config(**overrides: object) -> AgentConfig:
    values = {
        "model_provider": "remote",
        "model_api_base": "https://model.example/v1",
        "model_api_key": "test-key",
        "model_name": "test-model",
        "model_max_retries": 2,
        "model_retry_initial_seconds": 0,
        "model_retry_max_seconds": 0,
    }
    values.update(overrides)
    return AgentConfig(**values)


def sse(*chunks: dict[str, object]) -> bytes:
    lines = [f"data: {json.dumps(chunk)}\n\n" for chunk in chunks]
    lines.append("data: [DONE]\n\n")
    return "".join(lines).encode()


@pytest.mark.parametrize("retry_status", [429, 502, 503, 504])
def test_model_retries_transient_status_and_records_stream_usage(retry_status: int) -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        request_body = json.loads(request.content)
        assert request_body["stream"] is True
        assert request_body["stream_options"] == {"include_usage": True}
        if attempts == 1:
            return httpx.Response(
                retry_status,
                headers={"Retry-After": "0"},
                json={"error": {"message": "slow down"}},
            )
        return httpx.Response(
            200,
            headers={"Content-Type": "text/event-stream"},
            content=sse(
                {"choices": [{"delta": {"role": "assistant", "content": "你"}}]},
                {"choices": [{"delta": {"content": "好"}}]},
                {"choices": [], "usage": {"prompt_tokens": 7, "completion_tokens": 2, "total_tokens": 9}},
            ),
        )

    transport = httpx.MockTransport(handler)
    real_client = httpx.Client
    tokens: list[str] = []
    with patch(
        "agent_framework.model.httpx.Client",
        side_effect=lambda **kwargs: real_client(transport=transport, **kwargs),
    ):
        result = OpenAICompatibleModel(config()).complete(
            [{"role": "user", "content": "你好"}],
            on_token=tokens.append,
        )

    assert result.message["content"] == "你好"
    assert tokens == ["你", "好"]
    assert result.request_count == 2
    assert result.usage.input_tokens == 7
    assert result.usage.output_tokens == 2


def test_model_does_not_retry_authentication_failure() -> None:
    attempts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(401, json={"error": {"message": "bad key"}})

    transport = httpx.MockTransport(handler)
    real_client = httpx.Client
    with (
        patch(
            "agent_framework.model.httpx.Client",
            side_effect=lambda **kwargs: real_client(transport=transport, **kwargs),
        ),
        pytest.raises(ModelApiError) as raised,
    ):
        OpenAICompatibleModel(config()).complete([{"role": "user", "content": "test"}])

    assert raised.value.code == "MODEL_AUTHENTICATION_FAILED"
    assert raised.value.retryable is False
    assert attempts == 1


def test_model_distinguishes_exhausted_quota_from_rate_limit() -> None:
    attempts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(
            429,
            json={"error": {"type": "insufficient_quota", "message": "billing limit reached"}},
        )

    transport = httpx.MockTransport(handler)
    real_client = httpx.Client
    with (
        patch(
            "agent_framework.model.httpx.Client",
            side_effect=lambda **kwargs: real_client(transport=transport, **kwargs),
        ),
        pytest.raises(ModelApiError) as raised,
    ):
        OpenAICompatibleModel(config()).complete([{"role": "user", "content": "test"}])

    assert raised.value.code == "MODEL_QUOTA_EXCEEDED"
    assert raised.value.retryable is False
    assert attempts == 1


def test_model_cancellation_stops_before_upstream_request() -> None:
    model = OpenAICompatibleModel(config())
    with pytest.raises(ModelCancelledError):
        model.complete([{"role": "user", "content": "test"}], should_cancel=lambda: True)


def test_active_model_request_is_closed_when_run_is_cancelled() -> None:
    request_started = Event()

    class BlockingResponse:
        status_code = 200
        headers = {"content-type": "text/event-stream"}

        def __init__(self, closed: Event) -> None:
            self.closed = closed

        def __enter__(self) -> "BlockingResponse":
            return self

        def __exit__(self, *_args: object) -> bool:
            return False

        def iter_lines(self):
            request_started.set()
            self.closed.wait(5)
            raise httpx.ReadError("connection closed")

    class BlockingClient:
        def __init__(self) -> None:
            self.closed = Event()

        def stream(self, *_args: object, **_kwargs: object) -> BlockingResponse:
            return BlockingResponse(self.closed)

        def close(self) -> None:
            self.closed.set()

    client = BlockingClient()
    cancellation = RunCancellation()
    model = OpenAICompatibleModel(config())
    with patch("agent_framework.model.httpx.Client", return_value=client):
        with ThreadPoolExecutor(max_workers=1) as executor:
            result = executor.submit(
                model.complete,
                [{"role": "user", "content": "test"}],
                None,
                512,
                None,
                0.8,
                should_cancel=cancellation.is_cancelled,
                register_abort=cancellation.register_abort,
            )
            assert request_started.wait(2)
            cancellation.cancel()
            with pytest.raises(ModelCancelledError):
                result.result(timeout=2)

    assert client.closed.is_set()
