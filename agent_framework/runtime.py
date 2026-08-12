from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from typing import Any, Callable

from .approval import ApprovalPolicy
from .config import AgentConfig
from .model import OpenAICompatibleModel
from .tools import ToolRegistry
from .trace import TraceLogger


@dataclass
class AgentResult:
    final_answer: str
    steps: int
    messages: list[dict[str, Any]]


class AgentRunCancelled(RuntimeError):
    """Raised when the control plane asks a cooperative Agent run to stop."""


CancelCheck = Callable[[], bool]
EventCallback = Callable[[str, dict[str, Any]], None]


class AgentRuntime:
    def __init__(
        self,
        config: AgentConfig,
        tools: ToolRegistry,
        model: OpenAICompatibleModel | None = None,
        approval: ApprovalPolicy | None = None,
        trace: TraceLogger | None = None,
        system_prompt: str | None = None,
    ) -> None:
        self.config = config
        self.tools = tools
        self.model = model or OpenAICompatibleModel(config)
        self.approval = approval or ApprovalPolicy("never")
        self.trace = trace or TraceLogger()
        self.system_prompt = system_prompt

    def run(
        self,
        task: str,
        *,
        should_cancel: CancelCheck | None = None,
        on_event: EventCallback | None = None,
    ) -> AgentResult:
        cancel_check = should_cancel or (lambda: False)
        event_callback = on_event or (lambda _event, _payload: None)
        self._raise_if_cancelled(cancel_check)
        self.trace.log("run_start", {"task": task, "max_steps": self.config.max_steps})
        event_callback("agent.started", {"max_steps": self.config.max_steps})
        tool_names = [spec["function"]["name"] for spec in self.tools.specs()]
        default_system_prompt = (
            "You are a coding agent. Use the provided tools for file and project work. "
            f"Available tool names are exactly: {', '.join(tool_names)}. "
            "Never invent tool names. Do not claim work is done until tool output confirms it. "
            "Keep the final answer concise and include key evidence."
        )
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": self.system_prompt or default_system_prompt,
            },
            {"role": "user", "content": task},
        ]

        for step in range(1, self.config.max_steps + 1):
            self._raise_if_cancelled(cancel_check)
            event_callback("agent.step.started", {"step": step})
            try:
                assistant_message = self.model.complete(messages, self.tools.specs())
            except Exception as exc:
                self.trace.log("model_error", {"step": step, "error": str(exc)})
                event_callback("agent.model.failed", {"step": step, "error": str(exc)})
                raise
            self._raise_if_cancelled(cancel_check)
            self.trace.log(
                "model_message",
                {
                    "step": step,
                    "content": assistant_message.get("content"),
                    "tool_calls": assistant_message.get("tool_calls") or [],
                },
            )
            tool_calls = assistant_message.get("tool_calls") or []
            event_callback(
                "agent.model.completed",
                {"step": step, "tool_call_count": len(tool_calls)},
            )

            if not tool_calls:
                final_answer = assistant_message.get("content") or ""
                messages.append(assistant_message)
                self.trace.log("run_end", {"status": "completed", "steps": step, "final_answer": final_answer})
                event_callback("agent.completed", {"steps": step})
                return AgentResult(final_answer=final_answer, steps=step, messages=messages)

            messages.append(assistant_message)
            for tool_call in tool_calls:
                self._raise_if_cancelled(cancel_check)
                name = tool_call["function"]["name"]
                raw_arguments = tool_call["function"].get("arguments") or "{}"
                arguments = json.loads(raw_arguments)

                self._trace_tool_call(step, name, arguments)
                self.trace.log("tool_call", {"step": step, "name": name, "arguments": arguments})
                event_callback("agent.tool.started", {"step": step, "tool": name})

                decision = self.approval.check(name, arguments)
                self.trace.log(
                    "approval",
                    {
                        "step": step,
                        "name": name,
                        "allowed": decision.allowed,
                        "reason": decision.reason,
                        "requires_confirmation": decision.requires_confirmation,
                    },
                )
                if not decision.allowed:
                    result = {
                        "success": False,
                        "message": "Tool call denied by approval policy",
                        "error": decision.reason,
                    }
                    self._trace_tool_result(result)
                    self.trace.log("tool_result", {"step": step, "name": name, "result": result})
                    event_callback(
                        "agent.tool.completed",
                        {"step": step, "tool": name, "success": False, "denied": True},
                    )
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call["id"],
                            "content": json.dumps(result, ensure_ascii=False),
                        }
                    )
                    continue

                result = self.tools.call(name, arguments)
                self._raise_if_cancelled(cancel_check)
                self._trace_tool_result(result)
                self.trace.log("tool_result", {"step": step, "name": name, "result": result})
                event_callback(
                    "agent.tool.completed",
                    {"step": step, "tool": name, "success": bool(result.get("success"))},
                )

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call["id"],
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )

        final_answer = f"Stopped after {self.config.max_steps} steps without a final answer."
        self.trace.log("run_end", {"status": "max_steps", "steps": self.config.max_steps, "final_answer": final_answer})
        event_callback("agent.max_steps", {"steps": self.config.max_steps})
        return AgentResult(final_answer=final_answer, steps=self.config.max_steps, messages=messages)

    def _raise_if_cancelled(self, should_cancel: CancelCheck) -> None:
        if should_cancel():
            self.trace.log("run_end", {"status": "cancelled"})
            raise AgentRunCancelled("Agent run was cancelled")

    def _trace_tool_call(self, step: int, name: str, arguments: dict[str, Any]) -> None:
        print(
            f"[step {step}] call {name}: {json.dumps(arguments, ensure_ascii=False)}",
            file=sys.stderr,
        )

    def _trace_tool_result(self, result: dict[str, Any]) -> None:
        compact = json.dumps(result, ensure_ascii=False)
        if len(compact) > 1200:
            compact = compact[:1200] + "...<truncated>"
        print(f"[tool result] {compact}", file=sys.stderr)
