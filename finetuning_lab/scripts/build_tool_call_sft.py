#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path("/Users/bytedance/Documents/aio_agent_framework")
OUT = ROOT / "finetuning_lab/data/processed/aio_agent_tool_call_sft.jsonl"

SYSTEM_PROMPT = (
    "You are an AIO Sandbox agent. You can use tools by returning exactly one compact JSON object. "
    "When a task requires shell, file, or browser access, respond only as "
    '{"tool_call":{"name":"TOOL_NAME","arguments":{...}}}. '
    "Do not explain before or after the JSON. If no tool is needed, answer normally."
)


def compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def sample(user: str, tool: str | None = None, arguments: dict[str, Any] | None = None, answer: str | None = None) -> dict[str, Any]:
    if tool:
        content = compact({"tool_call": {"name": tool, "arguments": arguments or {}}})
    else:
        content = answer or "我可以直接回答这个问题，不需要调用工具。"
    return {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user},
            {"role": "assistant", "content": content},
        ]
    }


def build_samples() -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []

    shell_cases = [
        ("列出 /home/gem 下的文件，并按用途分类", "find /home/gem -maxdepth 2 -print"),
        ("看一下 /home/gem 目录里有什么", "ls -la /home/gem"),
        ("请在 sandbox 里执行 pwd", "pwd"),
        ("运行命令 ls -la /home/gem", "ls -la /home/gem"),
        ("帮我查找 /home/gem 下的 Python 文件", "find /home/gem -name '*.py' -print"),
        ("统计 /home/gem/data.txt 有多少行", "wc -l /home/gem/data.txt"),
        ("查看 /home/gem 下 txt 文件", "find /home/gem -maxdepth 1 -name '*.txt' -print"),
        ("列出当前目录", "pwd && ls -la"),
        ("执行命令：cat /home/gem/data.txt", "cat /home/gem/data.txt"),
        ("在终端里看看 /home/gem/result.txt", "cat /home/gem/result.txt"),
    ]
    for user, command in shell_cases:
        samples.append(sample(user, "shell_exec", {"command": command}))

    read_cases = [
        ("读取 /home/gem/data.txt", "/home/gem/data.txt"),
        ("帮我打开 /home/gem/result.txt 看内容", "/home/gem/result.txt"),
        ("查看文件 /home/gem/page.txt", "/home/gem/page.txt"),
        ("读出 /home/gem/app_demo.txt", "/home/gem/app_demo.txt"),
        ("把 /home/gem/framework_demo.txt 的内容给我", "/home/gem/framework_demo.txt"),
    ]
    for user, file in read_cases:
        samples.append(sample(user, "file_read", {"file": file}))

    write_cases = [
        ("帮我生成一个test", "/home/gem/test.txt", "test\n"),
        ("帮我生成一个 test.txt 文件", "/home/gem/test.txt", "test\n"),
        ("帮我生成一个test.txt文件同时告诉我，这个文件生成在哪里了", "/home/gem/test.txt", "test\n"),
        ("新建 test.txt，内容写 test", "/home/gem/test.txt", "test\n"),
        ("创建 /home/gem/tool_train_demo.txt，内容是 hello tool training", "/home/gem/tool_train_demo.txt", "hello tool training\n"),
        ("写入 /home/gem/note.txt 内容：agent can use tools", "/home/gem/note.txt", "agent can use tools\n"),
        ("保存到 /home/gem/todo.txt：1. learn tool calls", "/home/gem/todo.txt", "1. learn tool calls\n"),
        ("帮我新建文件 /home/gem/demo.json，内容是 {}", "/home/gem/demo.json", "{}\n"),
        ("创建文件 /home/gem/answer.txt 写入 done", "/home/gem/answer.txt", "done\n"),
    ]
    for user, file, content in write_cases:
        samples.append(sample(user, "file_write", {"file": file, "content": content}))

    browser_cases = [
        ("打开 https://example.com 并看看页面", "https://example.com"),
        ("访问 https://example.com", "https://example.com"),
        ("用浏览器打开 https://www.iana.org/domains/example", "https://www.iana.org/domains/example"),
        ("浏览网页 https://example.com", "https://example.com"),
        ("进入 https://example.com 页面", "https://example.com"),
    ]
    for user, url in browser_cases:
        samples.append(sample(user, "browser_navigate", {"url": url}))

    screenshot_cases = [
        "给当前浏览器页面截图",
        "截一张网页图",
        "browser screenshot",
        "保存当前页面截图",
        "请截图确认页面状态",
    ]
    for user in screenshot_cases:
        samples.append(sample(user, "browser_screenshot", {}))

    no_tool_cases = [
        ("你好", "你好，我是本地 AIO Sandbox agent。"),
        ("你是什么模型", "我是本地 DeepSeek-R1-Distill-Qwen-1.5B 模型。"),
        ("解释一下什么是 LoRA", "LoRA 是一种只训练少量低秩适配参数的高效微调方法。"),
        ("用一句话说明 smoke run", "smoke run 是为了验证训练链路能跑通的小规模测试。"),
        ("工具调用是什么意思", "工具调用是模型先请求外部工具执行操作，再基于工具结果回答。"),
    ]
    for user, answer in no_tool_cases:
        samples.append(sample(user, answer=answer))

    augmented: list[dict[str, Any]] = []
    for item in samples:
        augmented.append(item)
        messages = item["messages"]
        user = messages[1]["content"]
        assistant = messages[2]["content"]
        if assistant.startswith('{"tool_call":'):
            augmented.append(
                {
                    "messages": [
                        messages[0],
                        {"role": "user", "content": f"下面这个任务需要你自己决定是否调用工具：{user}"},
                        messages[2],
                    ]
                }
            )
    return augmented


def main() -> None:
    samples = build_samples()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as fp:
        for row in samples:
            fp.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"Wrote {len(samples)} tool-call SFT samples to {OUT}")


if __name__ == "__main__":
    main()
