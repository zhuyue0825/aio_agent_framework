from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from .http_json import get_bytes, post_json


class SandboxClient:
    """Small REST client for AIO Sandbox."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def shell_exec(self, command: str) -> dict[str, Any]:
        return post_json(
            f"{self.base_url}/v1/shell/exec",
            {"command": command},
            timeout=120,
        )

    def file_read(self, file: str) -> dict[str, Any]:
        return post_json(
            f"{self.base_url}/v1/file/read",
            {"file": file},
            timeout=30,
        )

    def file_write(self, file: str, content: str) -> dict[str, Any]:
        return post_json(
            f"{self.base_url}/v1/file/write",
            {"file": file, "content": content},
            timeout=30,
        )

    def browser_navigate(self, url: str) -> dict[str, Any]:
        return post_json(
            f"{self.base_url}/v1/browser/page/navigate",
            {"url": url, "wait_until": "load", "timeout": 30},
            timeout=60,
        )

    def browser_screenshot(self) -> dict[str, Any]:
        query = urlencode({"format": "png"})
        image, headers = get_bytes(
            f"{self.base_url}/v1/browser/page/screenshot?{query}",
            timeout=60,
        )
        screenshot_dir = Path(__file__).resolve().parents[1] / "screenshots"
        screenshot_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = screenshot_dir / f"browser-{stamp}.png"
        path.write_bytes(image)
        return {
            "success": True,
            "message": "Screenshot captured",
            "data": {
                "file": str(path),
                "bytes": len(image),
                "content_type": headers.get("content-type"),
                "image_width": headers.get("x-image-width"),
                "image_height": headers.get("x-image-height"),
                "screen_width": headers.get("x-screen-width"),
                "screen_height": headers.get("x-screen-height"),
            },
            "hint": None,
        }
