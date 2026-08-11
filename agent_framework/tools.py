from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .sandbox import SandboxClient


ToolHandler = Callable[[dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler

    def as_openai_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"duplicate tool: {tool.name}")
        self._tools[tool.name] = tool

    def specs(self) -> list[dict[str, Any]]:
        return [tool.as_openai_tool() for tool in self._tools.values()]

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name not in self._tools:
            return {
                "success": False,
                "message": f"Unknown tool: {name}",
                "error": "unknown_tool",
                "data": {
                    "requested_tool": name,
                    "available_tools": sorted(self._tools),
                    "arguments": arguments,
                },
                "hint": "Use one of the available tools exactly as named.",
            }
        return self._tools[name].handler(arguments)


def object_schema(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def build_default_tools(sandbox: SandboxClient) -> ToolRegistry:
    registry = ToolRegistry()

    registry.register(
        Tool(
            name="shell_exec",
            description="Run a shell command inside AIO Sandbox.",
            parameters=object_schema(
                {"command": {"type": "string", "description": "Shell command to execute."}},
                ["command"],
            ),
            handler=lambda args: sandbox.shell_exec(args["command"]),
        )
    )

    registry.register(
        Tool(
            name="file_read",
            description="Read a text file inside AIO Sandbox.",
            parameters=object_schema(
                {"file": {"type": "string", "description": "Absolute file path inside the sandbox."}},
                ["file"],
            ),
            handler=lambda args: sandbox.file_read(args["file"]),
        )
    )

    registry.register(
        Tool(
            name="file_write",
            description="Write a text file inside AIO Sandbox.",
            parameters=object_schema(
                {
                    "file": {"type": "string", "description": "Absolute file path inside the sandbox."},
                    "content": {"type": "string", "description": "Text content to write."},
                },
                ["file", "content"],
            ),
            handler=lambda args: sandbox.file_write(args["file"], args["content"]),
        )
    )

    registry.register(
        Tool(
            name="browser_navigate",
            description="Open a URL in the sandbox browser and return page metadata.",
            parameters=object_schema(
                {"url": {"type": "string", "description": "URL to open."}},
                ["url"],
            ),
            handler=lambda args: sandbox.browser_navigate(args["url"]),
        )
    )

    registry.register(
        Tool(
            name="browser_screenshot",
            description="Take a screenshot from the sandbox browser.",
            parameters=object_schema({}, []),
            handler=lambda args: sandbox.browser_screenshot(),
        )
    )

    return registry
