from __future__ import annotations

import json
import logging
import os
import re
import sys
from contextvars import ContextVar
from datetime import datetime, timezone
from uuid import uuid4


SERVICE_NAME = "aio-agent-execution-service"
SAFE_TRACE_ID = re.compile(r"^[A-Za-z0-9_-]{8,100}$")
TRACE_ID_CONTEXT: ContextVar[str] = ContextVar("trace_id", default="")
EXTRA_FIELDS = ("http_method", "path", "status", "duration_seconds", "run_id", "event")
SENSITIVE_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"(?i)(authorization[\"']?\s*[:=]\s*bearer\s+)[^\s,\"']+"),
    re.compile(r"(?i)(api[_ -]?key[\"']?\s*[:=]\s*)[^\s,}\"']+"),
)


def normalize_trace_id(value: str | None) -> str:
    if value and SAFE_TRACE_ID.fullmatch(value):
        return value
    return str(uuid4())


def current_trace_id() -> str:
    return TRACE_ID_CONTEXT.get()


def redact(value: str) -> str:
    redacted = value
    for pattern in SENSITIVE_PATTERNS:
        if pattern.groups:
            redacted = pattern.sub(r"\1[REDACTED]", redacted)
        else:
            redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "service": SERVICE_NAME,
            "trace_id": getattr(record, "trace_id", None) or current_trace_id(),
            "logger": record.name,
            "message": redact(record.getMessage()),
        }
        for field in EXTRA_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info:
            payload["exception"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def configure_logging() -> None:
    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonLogFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    for name in ("uvicorn", "uvicorn.error", "aio_agent.execution_service"):
        configured = logging.getLogger(name)
        configured.handlers.clear()
        configured.propagate = True
