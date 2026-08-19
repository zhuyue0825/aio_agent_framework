#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import shlex
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL = ROOT / "finetuning_lab/models/deepseek-r1-distill-qwen-1.5b"
DEFAULT_ADAPTER = ROOT / "finetuning_lab/outputs/deepseek-r1-distill-qwen-1.5b-lora-mps-smoke"
IDENTITY_PROMPT = (
    "You are the local DeepSeek-R1-Distill-Qwen-1.5B model served through the AIO Agent App. "
    "If asked what model you are, answer that directly. You are not Bard, Gemini, ChatGPT, or Claude. "
    "Keep final answers concise and do not expose hidden reasoning."
)
TOOL_RESULT_PROMPT = (
    "The previous tool call has returned results. Use the tool result to answer the user. "
    "Do not call another tool unless the result is clearly insufficient."
)
TOOL_CALL_PROMPT = (
    "You are an AIO Sandbox agent. You can use tools by returning exactly one compact JSON object. "
    "Never wrap tool calls in markdown fences. Never output ```json. "
    "When a task requires shell, file, or browser access, respond only as "
    '{"tool_call":{"name":"TOOL_NAME","arguments":{...}}}. '
    "Do not explain before or after the JSON. If no tool is needed, answer normally. "
    "Never invent tool names."
)


def pick_device() -> str:
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def tokenizer_path_for(model_path: str, adapter_path: str | None) -> str:
    if adapter_path and (Path(adapter_path) / "tokenizer_config.json").exists():
        return adapter_path
    return model_path


def load_model(model_path: str, adapter_path: str | None) -> tuple[Any, Any, str]:
    device = pick_device()
    dtype = torch.float16 if device == "mps" else torch.float32
    tokenizer = AutoTokenizer.from_pretrained(tokenizer_path_for(model_path, adapter_path), trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        model_path,
        dtype=dtype,
        low_cpu_mem_usage=True,
        trust_remote_code=True,
    )
    if adapter_path:
        model = PeftModel.from_pretrained(model, adapter_path)
    model.to(device)
    model.eval()
    return tokenizer, model, device


def response_json(handler: BaseHTTPRequestHandler, status: int, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def available_tool_names(tools: list[dict[str, Any]]) -> set[str]:
    names: set[str] = set()
    for tool in tools:
        function = tool.get("function") or {}
        name = function.get("name")
        if isinstance(name, str):
            names.add(name)
    return names


def latest_user_content(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user" and isinstance(message.get("content"), str):
            return message["content"]
    return ""


def extract_latest_task(text: str) -> str:
    marker = "用户最新任务："
    if marker in text:
        return text.rsplit(marker, 1)[1].strip()
    return text.strip()


def extract_path(text: str, default: str = "/home/gem") -> str:
    match = re.search(r"(/[\w./-]+)", text)
    if match:
        return match.group(1).rstrip("。,.，")
    return default


def extract_url(text: str) -> str | None:
    match = re.search(r"https?://[^\s，。)）]+", text)
    return match.group(0) if match else None


def infer_tool_call(messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> tuple[str, dict[str, Any]] | None:
    names = available_tool_names(tools)
    task = extract_latest_task(latest_user_content(messages))
    lower_task = task.lower()

    url = extract_url(task)
    if url and "browser_navigate" in names and any(word in task for word in ["打开", "访问", "浏览", "页面", "网页"]):
        return "browser_navigate", {"url": url}

    if any(word in task for word in ["截图", "screenshot"]) and "browser_screenshot" in names and not url:
        return "browser_screenshot", {}

    if any(word in task for word in ["读取", "读出", "查看文件", "cat "]) and "file_read" in names:
        return "file_read", {"file": extract_path(task)}

    if any(word in task for word in ["写入", "创建文件", "新建文件", "保存到", "生成"]) and "file_write" in names:
        default_path = "/home/gem/test.txt" if "test" in lower_task else "/home/gem/app_demo.txt"
        path = extract_path(task, default_path)
        if path == "/home/gem" and "test" in lower_task:
            path = "/home/gem/test.txt"
        content = task
        content_match = re.search(r"(?:内容|写入)[:：](.+)$", task, re.S)
        if content_match:
            content = content_match.group(1).strip()
        elif "test" in lower_task:
            content = "test"
        return "file_write", {"file": path, "content": content + "\n"}

    if (
        "shell_exec" in names
        and (
            any(word in task for word in ["列出", "目录", "文件", "执行命令", "运行命令", "shell", "终端"])
            or any(word in lower_task for word in ["ls ", "pwd", "find ", "cat "])
        )
    ):
        path = extract_path(task)
        if "pwd" in lower_task or "当前目录" in task:
            command = "pwd"
        elif any(word in task for word in ["分类", "按用途"]):
            command = f"find {path} -maxdepth 2 -print"
        else:
            command = f"ls -la {path}"
        return "shell_exec", {"command": command}

    return None


def make_tool_call_message(model_name: str, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model_name,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": f"call_{uuid.uuid4().hex[:12]}",
                            "type": "function",
                            "function": {
                                "name": tool_name,
                                "arguments": json.dumps(arguments, ensure_ascii=False),
                            },
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
    }


def parse_model_tool_call(content: str, tools: list[dict[str, Any]]) -> tuple[str, dict[str, Any]] | None:
    names = available_tool_names(tools)
    text = strip_thinking(content).strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()
    search_from = 0
    while search_from < len(text):
        start = text.find("{", search_from)
        if start == -1:
            return None
        try:
            payload, end = json.JSONDecoder().raw_decode(text[start:])
        except json.JSONDecodeError:
            search_from = start + 1
            continue
        tool_call = payload.get("tool_call") if isinstance(payload, dict) else None
        if isinstance(tool_call, dict):
            name = tool_call.get("name")
            arguments = tool_call.get("arguments")
            if isinstance(name, str) and name in names and isinstance(arguments, dict):
                return name, arguments
        search_from = start + max(end, 1)
    return None


def make_text_message(model_name: str, content: str) -> dict[str, Any]:
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model_name,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
    }


def has_tool_result(messages: list[dict[str, Any]]) -> bool:
    return any(message.get("role") == "tool" for message in messages)


def latest_tool_payload(messages: list[dict[str, Any]]) -> dict[str, Any] | None:
    for message in reversed(messages):
        if message.get("role") != "tool" or not isinstance(message.get("content"), str):
            continue
        try:
            payload = json.loads(message["content"])
        except json.JSONDecodeError:
            return {"success": True, "message": "Tool returned text", "data": {"output": message["content"]}}
        if isinstance(payload, dict):
            return payload
    return None


def wants_tree_listing(messages: list[dict[str, Any]]) -> bool:
    task = latest_user_content(messages)
    return any(word in task for word in ["分级", "层级", "树状", "目录树", "tree", "文件目录"])


def format_path_tree(output: str) -> str:
    paths = []
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("/"):
            paths.append(line.rstrip("/"))
    if not paths:
        return f"目录输出：\n```text\n{output.strip()}\n```"

    root = min(paths, key=lambda item: item.count("/"))
    children: dict[str, set[str]] = {}
    labels: dict[str, str] = {root: root.rsplit("/", 1)[-1] or root}
    for path in sorted(paths):
        if path == root or not path.startswith(root + "/"):
            continue
        parent = root
        current = root
        for part in path[len(root) + 1 :].split("/"):
            current = f"{current}/{part}"
            children.setdefault(parent, set()).add(current)
            labels[current] = part
            parent = current
    children.setdefault(root, set())

    lines = [root]

    def render(node: str, prefix: str = "") -> None:
        items = sorted(children.get(node, set()), key=lambda item: (item not in children, labels[item].lower()))
        for index, child in enumerate(items):
            is_last = index == len(items) - 1
            branch = "└── " if is_last else "├── "
            child_label = labels[child] + ("/" if child in children else "")
            lines.append(f"{prefix}{branch}{child_label}")
            if child in children:
                render(child, prefix + ("    " if is_last else "│   "))

    render(root)
    return "已通过 sandbox 工具读取目录，分级目录如下：\n\n```text\n" + "\n".join(lines) + "\n```"


def extract_ls_base(command: str | None) -> str | None:
    if not command or not command.startswith("ls "):
        return None
    try:
        parts = shlex.split(command.split("|", 1)[0])
    except ValueError:
        return None
    candidates = [part for part in parts[1:] if not part.startswith("-")]
    return candidates[-1].rstrip("/") if candidates else None


def iter_output_paths(output: str, command: str | None = None) -> list[str]:
    base = extract_ls_base(command)
    paths: list[str] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("total "):
            continue
        if line.startswith("/"):
            paths.append(line.rstrip("/"))
            continue
        if base and re.match(r"^[bcdlps-][rwxStTs-]{9}\s+", line):
            name = line.split(None, 8)[-1]
            name = name.split(" -> ", 1)[0]
            if name in {".", ".."}:
                continue
            paths.append(f"{base}/{name}".rstrip("/"))
            continue
        paths.append(line)
    return paths


def categorize_paths(output: str, command: str | None = None) -> str:
    paths = iter_output_paths(output, command)
    if not paths:
        return "目录输出为空。"

    buckets: dict[str, list[str]] = {
        "脚本/代码": [],
        "数据/文本": [],
        "配置/缓存": [],
        "目录": [],
        "其他": [],
    }
    for path in paths:
        name = path.rsplit("/", 1)[-1]
        if name.endswith(".py"):
            buckets["脚本/代码"].append(path)
        elif name.endswith((".txt", ".json", ".csv", ".md")):
            buckets["数据/文本"].append(path)
        elif name.startswith(".") or "/." in path:
            buckets["配置/缓存"].append(path)
        elif "." not in name:
            buckets["目录"].append(path)
        else:
            buckets["其他"].append(path)

    lines = ["已通过 sandbox 工具读取目录，按用途粗分如下："]
    for title, items in buckets.items():
        if not items:
            continue
        sample = "\n".join(f"- `{item}`" for item in items[:12])
        extra = f"\n- ... 另有 {len(items) - 12} 项" if len(items) > 12 else ""
        lines.append(f"\n{title}：\n{sample}{extra}")
    return "\n".join(lines)


def format_tool_failure(payload: dict[str, Any], data: dict[str, Any]) -> str:
    command = data.get("command")
    target = data.get("file") or data.get("path") or data.get("url") or command
    operation = data.get("operation")
    message = str(data.get("message") or payload.get("message") or "未知错误")

    if data.get("errno_name") == "EISDIR" and target:
        message = f"{target} 是目录，不是可直接读取的文件。"
    elif data.get("errno_name") == "ENOENT" and target:
        message = f"{target} 不存在。"

    if command:
        title = "命令执行失败"
    elif operation == "read":
        title = "读取失败"
    elif operation == "write":
        title = "写入失败"
    else:
        title = "工具执行失败"

    if target:
        return f"{title}：{message}\n目标：`{target}`"
    return f"{title}：{message}"


def answer_from_tool_result(messages: list[dict[str, Any]]) -> str | None:
    payload = latest_tool_payload(messages)
    if not payload:
        return None
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    if payload.get("success") is False:
        return format_tool_failure(payload, data)

    output = data.get("output")
    command = data.get("command")
    if isinstance(command, str) and isinstance(output, str):
        if command.startswith(("find ", "ls ")):
            if wants_tree_listing(messages) and command.startswith("find "):
                return format_path_tree(output)
            return categorize_paths(output, command)
        if not output.strip():
            return f"命令已执行成功：`{command}`，没有输出。"
        return f"命令已执行：`{command}`\n\n输出：\n```text\n{output.strip()}\n```"

    if isinstance(data.get("file"), str) and "bytes_written" in data:
        return f"文件已写入成功：`{data['file']}`\n写入字节数：{data['bytes_written']}。"

    if isinstance(data.get("content"), str):
        path = data.get("file") or data.get("path")
        prefix = f"已读取文件：`{path}`\n\n" if isinstance(path, str) else ""
        return f"{prefix}文件内容：\n```text\n{data['content'].strip()}\n```"

    if isinstance(data.get("url"), str):
        lines = [f"浏览器已打开：`{data['url']}`"]
        if data.get("title"):
            lines.append(f"页面标题：{data['title']}")
        if data.get("status"):
            lines.append(f"HTTP 状态：{data['status']}")
        return "\n".join(lines)

    if isinstance(data.get("file"), str) and "content_type" in data:
        lines = [f"截图已保存：`{data['file']}`"]
        if data.get("image_width") and data.get("image_height"):
            lines.append(f"图片尺寸：{data['image_width']} x {data['image_height']}")
        if data.get("bytes"):
            lines.append(f"文件大小：{data['bytes']} bytes")
        return "\n".join(lines)

    if payload.get("success") is True and payload.get("message"):
        message = str(payload["message"])
        translations = {
            "Operation successful": "操作已完成。",
            "File written successfully": "文件已写入成功。",
            "File read successfully": "文件已读取成功。",
            "Command executed": "命令已执行成功。",
            "Screenshot captured": "截图已保存。",
        }
        return translations.get(message, message)
    return None


def tool_specs_text(tools: list[dict[str, Any]]) -> str:
    compact_tools = []
    for tool in tools:
        function = tool.get("function") or {}
        compact_tools.append(
            {
                "name": function.get("name"),
                "description": function.get("description"),
                "parameters": function.get("parameters"),
            }
        )
    return "Available tools:\n" + json.dumps(compact_tools, ensure_ascii=False, separators=(",", ":"))


def tool_call_prompt_for(tools: list[dict[str, Any]]) -> str:
    names = sorted(available_tool_names(tools))
    examples = []
    if "shell_exec" in names:
        examples.append(
            'For listing sandbox files, directory trees, hierarchical directories, or "sandbox 列表", '
            'use exactly {"tool_call":{"name":"shell_exec","arguments":{"command":"find /home/gem -maxdepth 2 -print"}}}.'
        )
    if "file_read" in names:
        examples.append(
            'For reading one specific text file, use exactly {"tool_call":{"name":"file_read","arguments":{"file":"/home/gem/data.txt"}}}.'
        )
    if "file_write" in names:
        examples.append(
            'For writing, creating, generating, or saving a file, use exactly '
            '{"tool_call":{"name":"file_write","arguments":{"file":"/home/gem/name.txt","content":"text\\n"}}}. '
            'If the user asks to generate test/test.txt without a path, write /home/gem/test.txt.'
        )
    if "browser_navigate" in names:
        examples.append(
            'For opening a webpage, use exactly {"tool_call":{"name":"browser_navigate","arguments":{"url":"https://example.com"}}}.'
        )
    if "browser_screenshot" in names:
        examples.append(
            'For taking a current browser screenshot, use exactly {"tool_call":{"name":"browser_screenshot","arguments":{}}}.'
        )
    return "\n".join(
        [
            TOOL_CALL_PROMPT,
            f"Valid tool names: {', '.join(names)}.",
            "Use only these exact names. Any other tool name is invalid.",
            "If the user asks about the current sandbox without a path, use /home/gem.",
            *examples,
        ]
    )


def build_prompt_messages(messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> list[dict[str, str]]:
    if tools and not has_tool_result(messages):
        prompt_messages: list[dict[str, str]] = [{"role": "system", "content": tool_call_prompt_for(tools)}]
    else:
        prompt_messages = [{"role": "system", "content": IDENTITY_PROMPT}]
    if has_tool_result(messages):
        prompt_messages.append({"role": "system", "content": TOOL_RESULT_PROMPT})
    for message in messages:
        role = message.get("role")
        content = message.get("content")
        if role == "system":
            continue
        if role in {"user", "assistant"} and isinstance(content, str) and content.strip():
            prompt_messages.append({"role": role, "content": content})
        elif role == "tool" and isinstance(content, str) and content.strip():
            prompt_messages.append({"role": "user", "content": f"Tool result:\n{content}"})
    return prompt_messages or [{"role": "user", "content": ""}]


def strip_thinking(content: str) -> str:
    if "</think>" not in content:
        return content.strip()
    return content.split("</think>", 1)[1].strip()


def strip_generated_chat_markers(content: str) -> str:
    text = content.strip()
    for marker in ("<|im_end|>", "<|im_start|>", "<｜end▁of▁sentence｜>", "<｜User｜>", "<｜Assistant｜>"):
        if marker in text:
            text = text.split(marker, 1)[0].strip()
    return text


def strip_unknown_tool_json_prefix(content: str, tools: list[dict[str, Any]]) -> str:
    text = content.strip()
    names = available_tool_names(tools)
    for _ in range(16):
        if not text.startswith("{"):
            return text
        try:
            payload, end = json.JSONDecoder().raw_decode(text)
        except json.JSONDecodeError:
            return text
        tool_call = payload.get("tool_call") if isinstance(payload, dict) else None
        if not isinstance(tool_call, dict):
            return text
        name = tool_call.get("name")
        if isinstance(name, str) and name in names:
            return text
        text = text[end:].strip()
    return text


def strip_inline_generation_artifacts(content: str) -> str:
    text = content.strip()
    for marker in (
        '{"tool_call"',
        "```json",
        "<|im_start|>",
        "<|im_end|>",
        "<｜tool",
        "你是否需要继续回答这个问题",
    ):
        if marker in text and not text.lstrip().startswith(marker):
            text = text.split(marker, 1)[0].strip()
    if "这个问题不需要调用工具。" in text:
        text = text.split("这个问题不需要调用工具。", 1)[0] + "这个问题不需要调用工具。"

    sentence_match = re.search(r"([。！？.!?])([^。！？.!?]*)$", text)
    if sentence_match and re.search(r"[{}<>/]|!!|```", sentence_match.group(2)):
        text = text[: sentence_match.start(2)].strip()
    text = re.sub(r"\s+[!{}<>/]+$", "", text).strip()

    parts = re.split(r"(?<=[。！？!?])\s+", text)
    deduped: list[str] = []
    seen: set[str] = set()
    for part in parts:
        normalized = part.strip()
        if not normalized:
            continue
        if normalized in seen:
            break
        seen.add(normalized)
        deduped.append(normalized)
    return " ".join(deduped).strip() if deduped else text


def clean_text_response(content: str, tools: list[dict[str, Any]]) -> str:
    text = strip_generated_chat_markers(strip_thinking(content))
    text = strip_unknown_tool_json_prefix(text, tools)
    text = strip_generated_chat_markers(text)
    text = strip_inline_generation_artifacts(text)
    text = text.strip()
    if text in {"```", "```json"} or text.startswith("```json"):
        return "模型生成了无效工具调用，未执行工具。请把要创建的文件名和内容说清楚后重试。"
    if text.startswith('{"tool_call"'):
        return "模型生成了无效工具调用，未执行工具。请重试这个任务。"
    return text


def render_qwen_prompt(messages: list[dict[str, str]]) -> str:
    rendered: list[str] = []
    for message in messages:
        role = message["role"]
        content = message["content"]
        rendered.append(f"<|im_start|>{role}\n{content}<|im_end|>\n")
    rendered.append("<|im_start|>assistant\n")
    return "".join(rendered)


def make_handler(
    tokenizer: Any,
    model: Any,
    device: str,
    model_name: str,
    enable_tool_rules: bool,
):
    class DeepSeekOpenAIHandler(BaseHTTPRequestHandler):
        server_version = "DeepSeekOpenAI/0.1"

        def do_GET(self) -> None:
            if self.path in {"/health", "/v1/health"}:
                response_json(self, 200, {"ok": True, "model": model_name, "device": device})
                return
            if self.path == "/v1/models":
                response_json(self, 200, {"object": "list", "data": [{"id": model_name, "object": "model"}]})
                return
            response_json(self, 404, {"error": {"message": "not found"}})

        def do_POST(self) -> None:
            if self.path != "/v1/chat/completions":
                response_json(self, 404, {"error": {"message": "not found"}})
                return

            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                raw_messages = payload.get("messages") or []
                tools = payload.get("tools") or []
                if enable_tool_rules and tools and not has_tool_result(raw_messages):
                    inferred_tool_call = infer_tool_call(raw_messages, tools)
                    if inferred_tool_call:
                        tool_name, arguments = inferred_tool_call
                        response_json(self, 200, make_tool_call_message(model_name, tool_name, arguments))
                        return

                tool_answer = answer_from_tool_result(raw_messages)
                if tool_answer:
                    response_json(self, 200, make_text_message(model_name, tool_answer))
                    return

                messages = build_prompt_messages(raw_messages, tools)
                max_new_tokens = int(payload.get("max_tokens") or payload.get("max_completion_tokens") or 256)
                max_new_tokens = max(1, min(max_new_tokens, 512))

                prompt_text = render_qwen_prompt(messages)
                inputs = tokenizer(prompt_text, return_tensors="pt").to(device)

                with torch.no_grad():
                    output_ids = model.generate(
                        **inputs,
                        max_new_tokens=max_new_tokens,
                        do_sample=False,
                        eos_token_id=[tokenizer.eos_token_id],
                        pad_token_id=tokenizer.pad_token_id or tokenizer.eos_token_id,
                    )

                new_tokens = output_ids[0, inputs["input_ids"].shape[-1] :]
                content = strip_thinking(tokenizer.decode(new_tokens, skip_special_tokens=True))
                model_tool_call = None
                if tools and not has_tool_result(raw_messages):
                    model_tool_call = parse_model_tool_call(content, tools)
                if model_tool_call:
                    tool_name, arguments = model_tool_call
                    response_json(self, 200, make_tool_call_message(model_name, tool_name, arguments))
                    return
                content = clean_text_response(content, tools)
                response_json(
                    self,
                    200,
                    {
                        "id": f"chatcmpl-{uuid.uuid4().hex}",
                        "object": "chat.completion",
                        "created": int(time.time()),
                        "model": model_name,
                        "choices": [
                            {
                                "index": 0,
                                "message": {"role": "assistant", "content": content},
                                "finish_reason": "stop",
                            }
                        ],
                    },
                )
            except Exception as exc:
                response_json(self, 500, {"error": {"message": str(exc), "type": exc.__class__.__name__}})

        def log_message(self, format: str, *args: Any) -> None:
            print(f"[{self.log_date_time_string()}] {self.address_string()} {format % args}")

    return DeepSeekOpenAIHandler


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve local DeepSeek through a small OpenAI-compatible API.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8010)
    parser.add_argument("--model", default=str(DEFAULT_MODEL))
    parser.add_argument("--adapter", default=None)
    parser.add_argument("--use-smoke-adapter", action="store_true")
    parser.add_argument("--name", default="local-deepseek-r1-distill-qwen-1.5b")
    parser.add_argument(
        "--enable-tool-rules",
        action="store_true",
        help="Enable rule-based fallback that converts obvious user tasks into OpenAI tool_calls.",
    )
    args = parser.parse_args()

    adapter_path = str(DEFAULT_ADAPTER) if args.use_smoke_adapter else args.adapter
    tokenizer, model, device = load_model(args.model, adapter_path)
    server = ThreadingHTTPServer(
        (args.host, args.port),
        make_handler(tokenizer, model, device, args.name, args.enable_tool_rules),
    )
    print(
        f"Serving {args.name} on http://{args.host}:{args.port}/v1/chat/completions "
        f"device={device} tool_rules={'on' if args.enable_tool_rules else 'off'}",
        flush=True,
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
