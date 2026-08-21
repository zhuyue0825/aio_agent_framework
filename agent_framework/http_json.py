from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
from random import uniform
from typing import Any, Callable


class HttpRequestError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int | None = None, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.retryable = retryable


def _http_error(method: str, url: str, status: int, detail: str) -> HttpRequestError:
    normalized_detail = detail.lower()
    if status in {401, 403}:
        code = "AUTHENTICATION_FAILED"
    elif status == 402 or (status == 429 and any(
        marker in normalized_detail for marker in ("insufficient_quota", "quota_exceeded", "billing")
    )):
        code = "QUOTA_EXCEEDED"
    elif status == 429:
        code = "RATE_LIMITED"
    elif status in {502, 503, 504}:
        code = "SERVICE_UNAVAILABLE"
    elif status >= 500:
        code = "UPSTREAM_ERROR"
    else:
        code = "INVALID_REQUEST"
    return HttpRequestError(
        code,
        f"{method} {url} failed: HTTP {status}: {detail[:500]}",
        status_code=status,
        retryable=status in {429, 502, 503, 504} and code != "QUOTA_EXCEEDED",
    )


def _retry_after(value: str | None) -> float | None:
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


def _wait(attempt: int, retry_after: float | None, should_cancel: Callable[[], bool]) -> None:
    delay = retry_after if retry_after is not None else min(0.25 * (2**attempt) * uniform(0.75, 1.25), 4.0)
    deadline = time.monotonic() + min(delay, 30.0)
    while time.monotonic() < deadline:
        if should_cancel():
            raise HttpRequestError("CANCELLED", "HTTP request cancelled")
        time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))


def post_json(
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str] | None = None,
    timeout: int = 60,
    max_retries: int = 0,
    should_cancel: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            **(headers or {}),
        },
    )
    cancel_check = should_cancel or (lambda: False)
    for attempt in range(max_retries + 1):
        if cancel_check():
            raise HttpRequestError("CANCELLED", "HTTP request cancelled")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            error = _http_error("POST", url, exc.code, detail)
            if error.retryable and attempt < max_retries:
                _wait(attempt, _retry_after(exc.headers.get("Retry-After")), cancel_check)
                continue
            raise error from exc
        except (TimeoutError, socket.timeout) as exc:
            error = HttpRequestError("TIMEOUT", f"POST {url} timed out", retryable=True)
            if attempt < max_retries:
                _wait(attempt, None, cancel_check)
                continue
            raise error from exc
        except urllib.error.URLError as exc:
            timed_out = isinstance(exc.reason, (TimeoutError, socket.timeout))
            error = HttpRequestError(
                "TIMEOUT" if timed_out else "SERVICE_UNAVAILABLE",
                f"POST {url} {'timed out' if timed_out else 'failed'}",
                retryable=True,
            )
            if attempt < max_retries:
                _wait(attempt, None, cancel_check)
                continue
            raise error from exc
    raise HttpRequestError("UPSTREAM_ERROR", f"POST {url} failed")


def get_bytes(
    url: str,
    headers: dict[str, str] | None = None,
    timeout: int = 60,
) -> tuple[bytes, dict[str, str]]:
    request = urllib.request.Request(
        url,
        method="GET",
        headers=headers or {},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read(), dict(response.headers.items())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise _http_error("GET", url, exc.code, detail) from exc
    except (TimeoutError, socket.timeout) as exc:
        raise HttpRequestError("TIMEOUT", f"GET {url} timed out", retryable=True) from exc
    except urllib.error.URLError as exc:
        timed_out = isinstance(exc.reason, (TimeoutError, socket.timeout))
        raise HttpRequestError(
            "TIMEOUT" if timed_out else "SERVICE_UNAVAILABLE",
            f"GET {url} {'timed out' if timed_out else 'failed'}",
            retryable=True,
        ) from exc
