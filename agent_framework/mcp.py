from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from .tools import Tool, ToolRegistry


class MCPClient:
    """Minimal Streamable HTTP MCP client for AIO Sandbox.

    This is intentionally small: it supports initialize, tools/list, and
    tools/call, which are enough to expose sandbox capabilities to the agent.
    """

    def __init__(self, endpoint: str) -> None:
        self.endpoint = endpoint
        self._next_id = 1

    def initialize(self) -> dict[str, Any]:
        return self.rpc(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "aio-agent-framework", "version": "0.1.0"},
            },
        )

    def list_tools(self) -> list[dict[str, Any]]:
        response = self.rpc("tools/list", {})
        return response.get("result", {}).get("tools", [])

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return self.rpc("tools/call", {"name": name, "arguments": arguments})

    def rpc(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        request_id = self._next_id
        self._next_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        }
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self.endpoint,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                raw = response.read().decode("utf-8", errors="replace")
                content_type = response.headers.get("Content-Type", "")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"MCP {method} failed: HTTP {exc.code}: {detail}") from exc

        if "text/event-stream" in content_type or raw.startswith("event:"):
            return self._parse_sse_json(raw)
        return json.loads(raw)

    def _parse_sse_json(self, raw: str) -> dict[str, Any]:
        data_lines: list[str] = []
        for line in raw.splitlines():
            if line.startswith("data:"):
                data_lines.append(line.removeprefix("data:").strip())
        if not data_lines:
            raise RuntimeError(f"MCP response did not contain data lines: {raw[:200]}")
        return json.loads("\n".join(data_lines))


def build_mcp_tools(client: MCPClient, initialize: bool = True) -> ToolRegistry:
    if initialize:
        client.initialize()

    registry = ToolRegistry()
    for mcp_tool in client.list_tools():
        name = mcp_tool["name"]
        registry.register(
            Tool(
                name=name,
                description=mcp_tool.get("description") or f"MCP tool {name}",
                parameters=mcp_tool.get("inputSchema") or {"type": "object", "properties": {}},
                handler=lambda args, tool_name=name: client.call_tool(tool_name, args),
            )
        )
    return registry
