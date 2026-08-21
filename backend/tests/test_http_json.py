from __future__ import annotations

import io
import socket
import urllib.error
from email.message import Message
from unittest.mock import patch

import pytest

from agent_framework.http_json import HttpRequestError, post_json


class JsonResponse:
    def __enter__(self) -> "JsonResponse":
        return self

    def __exit__(self, *_args: object) -> bool:
        return False

    def read(self) -> bytes:
        return b'{"ok":true}'


def http_error(status: int, body: str) -> urllib.error.HTTPError:
    headers = Message()
    headers["Retry-After"] = "0"
    return urllib.error.HTTPError(
        "https://service.example/callback",
        status,
        "upstream error",
        headers,
        io.BytesIO(body.encode()),
    )


@pytest.mark.parametrize("status", [429, 502, 503, 504])
def test_post_json_retries_transient_http_statuses(status: int) -> None:
    with patch(
        "agent_framework.http_json.urllib.request.urlopen",
        side_effect=[http_error(status, "busy"), JsonResponse()],
    ) as urlopen:
        result = post_json("https://service.example/callback", {"run": "1"}, max_retries=1)

    assert result == {"ok": True}
    assert urlopen.call_count == 2


def test_post_json_distinguishes_authentication_quota_and_timeout() -> None:
    with (
        patch(
            "agent_framework.http_json.urllib.request.urlopen",
            side_effect=http_error(401, "invalid token"),
        ),
        pytest.raises(HttpRequestError) as authentication,
    ):
        post_json("https://service.example/callback", {})
    assert authentication.value.code == "AUTHENTICATION_FAILED"

    with (
        patch(
            "agent_framework.http_json.urllib.request.urlopen",
            side_effect=http_error(429, "insufficient_quota"),
        ),
        pytest.raises(HttpRequestError) as quota,
    ):
        post_json("https://service.example/callback", {}, max_retries=2)
    assert quota.value.code == "QUOTA_EXCEEDED"

    with (
        patch("agent_framework.http_json.urllib.request.urlopen", side_effect=socket.timeout()),
        pytest.raises(HttpRequestError) as timeout,
    ):
        post_json("https://service.example/callback", {})
    assert timeout.value.code == "TIMEOUT"
