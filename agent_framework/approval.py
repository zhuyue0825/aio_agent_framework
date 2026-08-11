from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ApprovalDecision:
    allowed: bool
    reason: str
    requires_confirmation: bool = False


class ApprovalPolicy:
    """Simple local approval policy for risky tool calls.

    Modes:
    - never: deny risky calls, allow safe calls
    - ask: ask on stdin for risky calls
    - auto: allow all calls
    """

    def __init__(self, mode: str = "never", writable_prefixes: tuple[str, ...] = ("/home/gem",)) -> None:
        if mode not in {"never", "ask", "auto"}:
            raise ValueError("approval mode must be never, ask, or auto")
        self.mode = mode
        self.writable_prefixes = writable_prefixes

    def check(self, tool_name: str, arguments: dict[str, Any]) -> ApprovalDecision:
        if self.mode == "auto":
            return ApprovalDecision(True, "approval mode auto")

        risk = self._risk_reason(tool_name, arguments)
        if not risk:
            return ApprovalDecision(True, "safe by local policy")

        if self.mode == "never":
            return ApprovalDecision(False, risk, requires_confirmation=True)

        prompt = f"Approve risky tool call? {tool_name} {arguments} risk={risk} [y/N] "
        if not sys.stdin.isatty():
            return ApprovalDecision(False, f"{risk}; stdin is not interactive", requires_confirmation=True)
        answer = input(prompt).strip().lower()
        if answer in {"y", "yes"}:
            return ApprovalDecision(True, "approved by user", requires_confirmation=True)
        return ApprovalDecision(False, "denied by user", requires_confirmation=True)

    def _risk_reason(self, tool_name: str, arguments: dict[str, Any]) -> str | None:
        if tool_name == "shell_exec":
            return self._shell_risk(arguments.get("command", ""))

        if tool_name == "file_write":
            file = str(arguments.get("file", ""))
            if not file.startswith(self.writable_prefixes):
                return f"file_write outside allowed prefixes {self.writable_prefixes}: {file}"

        return None

    def _shell_risk(self, command: str) -> str | None:
        lowered = command.lower()
        blocked_fragments = [
            "rm -rf /",
            "rm -rf ~",
            "mkfs",
            "dd if=",
            "shutdown",
            "reboot",
            "chmod -r 777",
            "chown -r",
            "curl ",
            "wget ",
            "| sh",
            "| bash",
            "sudo ",
        ]
        for fragment in blocked_fragments:
            if fragment in lowered:
                return f"risky shell fragment: {fragment}"
        return None
