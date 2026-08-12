from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class TraceLogger:
    def __init__(self, path: str | None = None, context: dict[str, Any] | None = None) -> None:
        self.path = Path(path) if path else None
        self.context = dict(context or {})
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, event: str, payload: dict[str, Any]) -> None:
        if not self.path:
            return
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": event,
            **self.context,
            "payload": payload,
        }
        with self.path.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(record, ensure_ascii=False) + "\n")
