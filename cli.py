#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from agent_framework import AgentConfig, AgentRuntime, ApprovalPolicy, SandboxClient, TraceLogger, build_default_tools
from agent_framework.mcp import MCPClient, build_mcp_tools
from agent_framework.web import run_web_server


def run_demo(config: AgentConfig) -> None:
    sandbox = SandboxClient(config.sandbox_url)
    checks = [
        ("shell_exec", lambda: sandbox.shell_exec("pwd && ls -la | head")),
        ("file_write", lambda: sandbox.file_write("/home/gem/framework_demo.txt", "hello from agent framework\n")),
        ("file_read", lambda: sandbox.file_read("/home/gem/framework_demo.txt")),
        ("browser_navigate", lambda: sandbox.browser_navigate("https://example.com")),
    ]
    for name, fn in checks:
        print(f"\n## {name}")
        print(json.dumps(fn(), ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Tiny AIO Sandbox agent framework")
    parser.add_argument("task", nargs="*", help="Task for the agent")
    parser.add_argument("--demo", action="store_true", help="Check sandbox tools without calling a model")
    parser.add_argument("--max-steps", type=int, default=None)
    parser.add_argument("--approval", choices=["never", "ask", "auto"], default="never")
    default_trace = str(Path(__file__).resolve().parent / "traces" / "latest.jsonl")
    parser.add_argument("--trace", default=default_trace)
    parser.add_argument("--tools", choices=["rest", "mcp"], default="rest")
    parser.add_argument("--mcp-url", default=None)
    parser.add_argument("--mcp-list", action="store_true", help="List MCP tools exposed by AIO Sandbox")
    parser.add_argument("--web", action="store_true", help="Start the local Web UI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    config = AgentConfig.from_env()
    if args.max_steps is not None:
        config = AgentConfig(
            sandbox_url=config.sandbox_url,
            model_api_base=config.model_api_base,
            model_api_key=config.model_api_key,
            model_name=config.model_name,
            max_steps=args.max_steps,
            temperature=config.temperature,
        )

    if args.demo:
        run_demo(config)
        return

    if args.web:
        run_web_server(config, args.host, args.port, args.trace, args.approval)
        return

    if args.mcp_list:
        mcp = MCPClient(args.mcp_url or f"{config.sandbox_url.rstrip('/')}/v1/mcp")
        mcp.initialize()
        print(json.dumps(mcp.list_tools(), ensure_ascii=False, indent=2))
        return

    task = " ".join(args.task).strip()
    if not task:
        parser.error("provide a task, or use --demo/--web/--mcp-list")

    if args.tools == "mcp":
        mcp = MCPClient(args.mcp_url or f"{config.sandbox_url.rstrip('/')}/v1/mcp")
        tools = build_mcp_tools(mcp)
    else:
        sandbox = SandboxClient(config.sandbox_url)
        tools = build_default_tools(sandbox)

    runtime = AgentRuntime(
        config=config,
        tools=tools,
        approval=ApprovalPolicy(args.approval),
        trace=TraceLogger(args.trace),
    )
    result = runtime.run(task)
    print(result.final_answer)


if __name__ == "__main__":
    main()
