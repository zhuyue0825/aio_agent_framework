from __future__ import annotations

from typing import Any, Iterable

from agent_framework.mcp import build_mcp_tools
from agent_framework.tools import ToolRegistry

from .qq_mail import QqMailMcpServer


def build_mcp_server_tools(configurations: Iterable[Any]) -> ToolRegistry:
    registry = ToolRegistry()
    for raw in configurations:
        configuration = raw.model_dump() if hasattr(raw, "model_dump") else dict(raw)
        kind = str(configuration.get("kind", ""))
        if kind != "qq_mail":
            continue
        config = dict(configuration.get("config") or {})
        credentials = dict(configuration.get("credentials") or {})
        server = QqMailMcpServer(
            email=str(config.get("email", "")),
            authorization_code=str(credentials.get("authorization_code", "")),
            imap_host=str(config.get("imap_host", "imap.qq.com")),
            imap_port=int(config.get("imap_port", 993)),
        )
        registry.extend(build_mcp_tools(server))
    return registry


def test_qq_mail_connection(
    *,
    email: str,
    authorization_code: str,
    imap_host: str,
    imap_port: int,
) -> dict[str, Any]:
    server = QqMailMcpServer(
        email=email,
        authorization_code=authorization_code,
        imap_host=imap_host,
        imap_port=imap_port,
    )
    message_count = server.test_connection()
    return {
        "ok": True,
        "message_count": message_count,
        "tools": [tool["name"] for tool in server.list_tools()],
    }
