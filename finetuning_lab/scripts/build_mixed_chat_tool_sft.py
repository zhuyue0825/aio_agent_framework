#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from build_tool_call_sft import SYSTEM_PROMPT, build_samples as build_tool_samples


ROOT = Path("/Users/bytedance/Documents/aio_agent_framework")
OUT = ROOT / "finetuning_lab/data/processed/aio_agent_mixed_chat_tool_sft.jsonl"


def chat(user: str, answer: str) -> dict[str, object]:
    return {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user},
            {"role": "assistant", "content": answer},
        ]
    }


TOOL_RESULT_SYSTEM_PROMPT = (
    "The previous tool call has returned results. Use the tool result to answer the user clearly in Chinese. "
    "Include important paths, URLs, command output, and error details. Do not expose raw English tool status messages."
)


def tool_result_answer(user: str, result: dict[str, object], answer: str) -> dict[str, object]:
    return {
        "messages": [
            {"role": "system", "content": TOOL_RESULT_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": user + "\n\nTool result:\n" + json.dumps(result, ensure_ascii=False, separators=(",", ":")),
            },
            {"role": "assistant", "content": answer},
        ]
    }


def success(message: str, data: dict[str, object]) -> dict[str, object]:
    return {"success": True, "message": message, "data": data, "hint": None}


def failure(message: str, data: dict[str, object]) -> dict[str, object]:
    return {"success": False, "message": message, "data": data, "hint": None}


def build_tool_result_answer_samples() -> list[dict[str, object]]:
    samples: list[dict[str, object]] = []

    file_write_cases = [
        (
            "帮我生成一个test.txt文件同时告诉我，这个文件生成在哪里了",
            success("File written successfully", {"file": "/home/gem/test.txt", "bytes_written": 5}),
            "文件已写入成功：`/home/gem/test.txt`\n写入字节数：5。",
        ),
        (
            "创建 /home/gem/note.txt，内容是 hello",
            success("File written successfully", {"file": "/home/gem/note.txt", "bytes_written": 6}),
            "文件已写入成功：`/home/gem/note.txt`\n写入字节数：6。",
        ),
        (
            "把结果保存到 /home/gem/result.txt",
            success("File written successfully", {"file": "/home/gem/result.txt", "bytes_written": 18}),
            "文件已写入成功：`/home/gem/result.txt`\n写入字节数：18。",
        ),
        (
            "新建 test.txt，内容写 test",
            success("File written successfully", {"file": "/home/gem/test.txt", "bytes_written": 5}),
            "文件已写入成功：`/home/gem/test.txt`\n写入字节数：5。",
        ),
    ]
    for user, result, answer in file_write_cases:
        samples.append(tool_result_answer(user, result, answer))

    file_read_cases = [
        (
            "读取 /home/gem/data.txt",
            success("File read successfully", {"content": "apple 3\nbanana 5\napple 7", "file": "/home/gem/data.txt"}),
            "已读取文件：`/home/gem/data.txt`\n\n文件内容：\n```text\napple 3\nbanana 5\napple 7\n```",
        ),
        (
            "打开 /home/gem/result.txt 看内容",
            success("File read successfully", {"content": "done\n", "file": "/home/gem/result.txt"}),
            "已读取文件：`/home/gem/result.txt`\n\n文件内容：\n```text\ndone\n```",
        ),
        (
            "帮我看看 /home/gem/app_demo.txt",
            success("File read successfully", {"content": "hello from aio agent app\n", "file": "/home/gem/app_demo.txt"}),
            "已读取文件：`/home/gem/app_demo.txt`\n\n文件内容：\n```text\nhello from aio agent app\n```",
        ),
    ]
    for user, result, answer in file_read_cases:
        samples.append(tool_result_answer(user, result, answer))

    shell_cases = [
        (
            "请在 sandbox 里执行 pwd",
            success("Command executed", {"command": "pwd", "status": "completed", "output": "/home/gem\n", "exit_code": 0}),
            "命令已执行：`pwd`\n\n输出：\n```text\n/home/gem\n```",
        ),
        (
            "列出 /home/gem 下的文件，并按用途分类",
            success(
                "Command executed",
                {
                    "command": "find /home/gem -maxdepth 1 -print",
                    "status": "completed",
                    "output": "/home/gem\n/home/gem/analyze.py\n/home/gem/data.txt\n/home/gem/result.txt\n/home/gem/.cache\n/home/gem/Downloads",
                    "exit_code": 0,
                },
            ),
            "已通过 sandbox 工具读取目录，按用途粗分如下：\n\n脚本/代码：\n- `/home/gem/analyze.py`\n\n数据/文本：\n- `/home/gem/data.txt`\n- `/home/gem/result.txt`\n\n配置/缓存：\n- `/home/gem/.cache`\n\n目录：\n- `/home/gem`\n- `/home/gem/Downloads`",
        ),
        (
            "帮我把当前 sandbox 文件目录按分级目录列出来",
            success(
                "Command executed",
                {
                    "command": "find /home/gem -maxdepth 2 -print",
                    "status": "completed",
                    "output": "/home/gem\n/home/gem/.cache\n/home/gem/.cache/browser\n/home/gem/data.txt\n/home/gem/result.txt",
                    "exit_code": 0,
                },
            ),
            "已通过 sandbox 工具读取目录，分级目录如下：\n\n```text\n/home/gem\n├── .cache/\n│   └── browser\n├── data.txt\n└── result.txt\n```",
        ),
        (
            "运行命令 true",
            success("Command executed", {"command": "true", "status": "completed", "output": "", "exit_code": 0}),
            "命令已执行成功：`true`，没有输出。",
        ),
    ]
    for user, result, answer in shell_cases:
        samples.append(tool_result_answer(user, result, answer))

    browser_cases = [
        (
            "打开 https://example.com 并看看页面",
            success(
                "Operation successful",
                {"url": "https://example.com/", "title": "Example Domain", "status": 200, "load_time_ms": 644.0},
            ),
            "浏览器已打开：`https://example.com/`\n页面标题：Example Domain\nHTTP 状态：200",
        ),
        (
            "访问 https://www.iana.org/domains/example",
            success(
                "Operation successful",
                {"url": "https://www.iana.org/domains/example", "title": "Example Domains", "status": 200},
            ),
            "浏览器已打开：`https://www.iana.org/domains/example`\n页面标题：Example Domains\nHTTP 状态：200",
        ),
        (
            "给当前浏览器页面截图",
            success(
                "Screenshot captured",
                {
                    "file": "/Users/bytedance/Documents/aio_agent_framework/screenshots/browser-20260707T120000Z.png",
                    "bytes": 12345,
                    "content_type": "image/png",
                    "image_width": "1280",
                    "image_height": "720",
                },
            ),
            "截图已保存：`/Users/bytedance/Documents/aio_agent_framework/screenshots/browser-20260707T120000Z.png`\n图片尺寸：1280 x 720\n文件大小：12345 bytes",
        ),
    ]
    for user, result, answer in browser_cases:
        samples.append(tool_result_answer(user, result, answer))

    failure_cases = [
        (
            "帮我打开 /home/gem/Downloads 看内容",
            failure(
                "Failed to read file: [Errno 21] Is a directory: '/home/gem/Downloads'",
                {
                    "path": "/home/gem/Downloads",
                    "operation": "read",
                    "message": "Failed to read file: [Errno 21] Is a directory: '/home/gem/Downloads'",
                    "error_type": "invalid_target",
                    "errno_name": "EISDIR",
                },
            ),
            "读取失败：/home/gem/Downloads 是目录，不是可直接读取的文件。\n目标：`/home/gem/Downloads`",
        ),
        (
            "读取 /home/gem/missing.txt",
            failure(
                "Failed to read file: [Errno 2] No such file or directory: '/home/gem/missing.txt'",
                {
                    "path": "/home/gem/missing.txt",
                    "operation": "read",
                    "message": "Failed to read file: [Errno 2] No such file or directory: '/home/gem/missing.txt'",
                    "error_type": "not_found",
                    "errno_name": "ENOENT",
                },
            ),
            "读取失败：/home/gem/missing.txt 不存在。\n目标：`/home/gem/missing.txt`",
        ),
        (
            "执行命令 cat /home/gem/missing.txt",
            failure(
                "Command failed",
                {
                    "command": "cat /home/gem/missing.txt",
                    "status": "failed",
                    "output": "cat: /home/gem/missing.txt: No such file or directory",
                    "exit_code": 1,
                },
            ),
            "命令执行失败：Command failed\n目标：`cat /home/gem/missing.txt`",
        ),
    ]
    for user, result, answer in failure_cases:
        samples.append(tool_result_answer(user, result, answer))

    return samples


def build_chat_anchor_samples() -> list[dict[str, object]]:
    samples: list[dict[str, object]] = []

    greetings = [
        "你好",
        "你好呀",
        "hi",
        "hello",
        "早上好",
        "晚上好",
        "sandbox你好",
        "你好 sandbox",
        "在吗",
        "你好吗",
        "谢谢",
        "辛苦了",
        "再见",
        "先随便聊一句",
        "我只是打个招呼",
        "不要调用工具，回复你好",
        "只回答一句：你好",
        "用中文和我打招呼",
        "请简短回复",
        "hello agent",
    ]
    greeting_answer = "你好，我是本地 AIO Sandbox agent。这个问题不需要调用工具。"
    for user in greetings:
        samples.append(chat(user, greeting_answer))

    identity_cases = [
        ("你是谁", "我是本地 AIO Sandbox agent，底层是本地 DeepSeek-R1-Distill-Qwen-1.5B 的 LoRA 微调实验模型。"),
        ("你是什么模型", "我是本地 DeepSeek-R1-Distill-Qwen-1.5B 模型，通过 OpenAI-style 接口接入这个 Web App。"),
        ("你现在用的是什么模型", "当前是本地 DeepSeek-R1-Distill-Qwen-1.5B LoRA 实验模型。"),
        ("你是 Bard 吗", "不是。我是本地 DeepSeek-R1-Distill-Qwen-1.5B 实验模型，不是 Bard。"),
        ("你是 DeepSeek 吗", "底层基座是 DeepSeek-R1-Distill-Qwen-1.5B，本地通过 LoRA 做了实验性微调。"),
        ("你能做什么", "我可以普通对话，也可以在需要时通过工具访问 sandbox 文件、shell 或浏览器。"),
        ("什么情况下你会调用工具", "只有当任务需要读取文件、执行命令、写文件或操作浏览器时，我才应该调用工具。"),
        ("什么情况下你不应该调用工具", "普通问候、解释概念、翻译、改写、总结已给出的文本时，不需要调用工具。"),
        ("如果我只是问你好，你要调用工具吗", "不需要。问候类问题直接回答即可。"),
        ("如果问题里出现 sandbox 这个词，就一定要调用工具吗", "不一定。只有明确要求查看或操作 sandbox 内容时才需要工具。"),
        ("你会不会自己乱读文件", "不应该。只有用户明确要求读取文件或目录时才应该使用文件或 shell 工具。"),
        ("请说明你的能力边界", "我能处理普通文本任务，也能在明确需要时调用工具；但我不会凭空访问文件或执行命令。"),
    ]
    for user, answer in identity_cases:
        samples.append(chat(user, answer))

    concepts = [
        ("LoRA", "LoRA 是一种高效微调方法，只训练少量低秩适配参数，从而降低显存和训练成本。"),
        ("SFT", "SFT 是 supervised fine-tuning，即用人工或构造好的输入输出样本继续训练模型。"),
        ("smoke run", "smoke run 是小规模冒烟测试，用来验证流程能跑通，不代表最终效果。"),
        ("tool_call", "tool_call 是模型按约定输出工具名和参数，让外部系统执行工具。"),
        ("tool_result", "tool_result 是工具执行后的结果，模型应基于这个结果组织最终回答。"),
        ("OpenAI-style tool_calls", "OpenAI-style tool_calls 是一种结构化协议，模型返回 tool_calls 字段，后端再执行对应函数。"),
        ("adapter", "adapter 是微调得到的小参数包，推理时叠加在基座模型上生效。"),
        ("基座模型", "基座模型是预训练好的通用模型，微调通常是在它上面继续学习特定行为。"),
        ("过拟合", "过拟合是模型过度记住训练样本，导致泛化能力变差。"),
        ("训练集混合比例", "训练集混合比例决定模型更偏向普通对话、工具调用还是某类特定任务。"),
        ("MPS", "MPS 是 PyTorch 在 Apple Silicon 上使用 Apple GPU/Metal 的后端。"),
        ("显存", "显存是 GPU 用来存放模型权重、激活值和训练状态的内存。"),
        ("量化", "量化是用更低精度表示模型参数，以减少内存占用和提升推理效率。"),
        ("学习率", "学习率控制每次参数更新的步长，过大可能不稳定，过小可能学得慢。"),
        ("epoch", "epoch 表示模型完整看过一遍训练集。"),
        ("max_steps", "max_steps 表示训练最多更新多少步，达到后就停止。"),
        ("loss", "loss 是训练误差指标，通常下降说明模型在训练样本上拟合得更好。"),
        ("数据清洗", "数据清洗是去掉格式错误、重复、低质量或不符合目标行为的样本。"),
        ("负样本", "负样本在这里指明确训练模型不要调用工具、而要普通回答的样本。"),
        ("上下文窗口", "上下文窗口是模型一次能读取的输入 token 上限。"),
    ]
    for term, answer in concepts:
        samples.append(chat(f"用一句话解释什么是{term}", answer))
        samples.append(chat(f"{term}是什么意思", answer))

    plain_tasks = [
        ("把“今天模型训练完成了”翻译成英文", "The model training was completed today."),
        ("把“tool calling requires structured outputs”翻译成中文", "工具调用需要结构化输出。"),
        ("把这句话改得更正式：这个模型现在有点乱", "这个模型当前的输出行为还不够稳定，需要进一步优化。"),
        ("把这句话改得更口语：当前系统无法稳定触发工具调用", "现在这个系统还不能稳定地自己决定什么时候用工具。"),
        ("给“模型微调实验”起 3 个小标题", "1. 数据准备\n2. LoRA 训练\n3. 推理验证"),
        ("用三点总结 LoRA 微调流程", "1. 准备训练样本。\n2. 在基座模型上训练 LoRA adapter。\n3. 加载 adapter 做推理验证。"),
        ("写一句测试 Web App 的问题", "请读取 /home/gem/data.txt，并告诉我里面有什么。"),
        ("给这个项目写一句简介", "这是一个本地 AIO Agent 实验项目，用来验证模型对话、工具调用和 LoRA 微调流程。"),
        ("解释为什么需要混合训练集", "因为只训练工具调用样本会让模型过度偏向调用工具，混入普通对话样本可以保住基础聊天能力。"),
        ("简单说明 1.5B 小模型的局限", "1.5B 小模型容量有限，复杂推理和稳定工具调用都需要更严格的数据、模板和评测。"),
        ("给我一个两步测试计划", "1. 先测试你好、你是谁等普通对话。\n2. 再测试读取文件、列目录等工具任务。"),
        ("请只回答“收到”", "收到"),
        ("只用一句话回答：训练数据为什么重要", "训练数据决定模型学习到什么行为和输出格式。"),
        ("我想先保障基础对话，应该怎么做", "先混入足够多的普通对话和 no-tool 负样本，再控制工具样本比例做联合训练。"),
        ("为什么现在问你好会返回文件内容", "因为训练样本过度偏向工具调用，模型把普通问题也误判成需要读取文件。"),
        ("怎么判断一个问题不需要工具", "如果用户只是问概念、闲聊、翻译、改写或处理已提供文本，就不需要工具。"),
        ("怎么判断一个问题需要工具", "如果用户要求查看真实文件、执行命令、写入文件或访问网页，就需要工具。"),
        ("把“模型不要乱调用工具”翻译成英文", "The model should not call tools unnecessarily."),
        ("帮我写一句提交说明", "新增混合对话与工具调用训练样本，降低普通对话误触发工具的概率。"),
        ("一句话说明这个实验的目标", "这个实验的目标是让本地小模型同时保留基础对话能力和结构化工具调用能力。"),
    ]
    for user, answer in plain_tasks:
        samples.append(chat(user, answer))

    inline_data_cases = [
        (
            "下面是数据，不要读文件，直接统计 apple 总数：\napple 3\nbanana 5\napple 7",
            "apple 的总数是 10。",
        ),
        (
            "这段文本已经在消息里了，帮我总结：LoRA 可以降低微调成本，只训练少量 adapter 参数。",
            "总结：LoRA 通过只训练少量 adapter 参数来降低微调成本。",
        ),
        (
            "直接根据这三行分类，不要调用工具：a.py\nb.txt\nconfig.json",
            "分类结果：\n- 代码：a.py\n- 文本：b.txt\n- 配置：config.json",
        ),
        (
            "我给你内容：hello world。请统计有几个单词",
            "共有 2 个单词。",
        ),
        (
            "请根据这句话回答，不要访问浏览器：DeepSeek 是一个开源模型系列。",
            "这句话说明 DeepSeek 是一个开源模型系列。",
        ),
        (
            "下面不是文件路径，只是例子：/home/gem/data.txt。请解释什么是路径",
            "路径是用来标识文件或目录位置的字符串，例如 /home/gem/data.txt。",
        ),
        (
            "如果用户把文件内容直接贴出来，你应该读文件吗",
            "不应该。内容已经在对话里时，直接基于消息回答即可。",
        ),
        (
            "如果用户说“不要调用工具”，你应该怎么做",
            "应尽量直接回答，除非任务本身没有工具就无法完成，并且需要先说明限制。",
        ),
    ]
    for user, answer in inline_data_cases:
        samples.append(chat(user, answer))

    math_cases = [
        ("17 + 25 等于多少", "42"),
        ("100 以内 1 到 10 的和是多少", "55"),
        ("3 个 apple 加 7 个 apple 是几个 apple", "10 个 apple。"),
        ("把 0.125 转成百分比", "12.5%。"),
        ("2 的 8 次方是多少", "256"),
        ("如果训练集有 65 条工具样本和 195 条对话样本，对话样本占比多少", "总数 260 条，对话样本占比 75%。"),
        ("300 steps 和 600 steps 哪个训练更久", "通常 600 steps 更久，因为参数更新次数更多。"),
        ("4GB 显存能轻松全量微调 1.5B 模型吗", "一般不轻松；更适合 LoRA、量化或更小 batch 的实验。"),
    ]
    for user, answer in math_cases:
        samples.append(chat(user, answer))

    clarification_cases = [
        ("帮我处理一下", "可以，请告诉我具体要处理的内容或目标。"),
        ("这个怎么弄", "需要先明确“这个”指的是哪一步或哪个文件。"),
        ("继续", "可以继续，但我需要知道你想从哪一步继续。"),
        ("效果不好怎么办", "先定位是数据、模板、训练参数还是推理解析问题，再逐项修正。"),
        ("帮我优化一下", "可以，请说明要优化的是模型效果、前端界面、训练配置还是工具调用流程。"),
        ("你自己决定", "我可以给出建议，但需要先根据目标选择更合适的方案。"),
        ("这个结果靠谱吗", "要看验证样例和失败样例；建议同时测普通对话和工具任务。"),
        ("是否可以商用", "需要看具体模型、数据集和 adapter 的许可证，不能只看“开源”两个字。"),
    ]
    for user, answer in clarification_cases:
        samples.append(chat(user, answer))

    tool_boundary_cases = [
        ("读取文件是什么意思", "读取文件是从指定路径拿到真实文件内容；如果只是解释概念，不需要调用工具。"),
        ("执行命令是什么意思", "执行命令是在 shell 里运行程序或命令；只有用户明确要求真实执行时才需要工具。"),
        ("浏览器工具有什么用", "浏览器工具用于打开网页、截图或检查页面状态；普通知识问答不需要浏览器。"),
        ("文件写入工具有什么风险", "文件写入会修改 sandbox 中的真实文件，所以应在用户明确要求时使用。"),
        ("普通聊天为什么不能总是调用工具", "因为工具调用会访问外部环境，普通聊天调用工具会产生错误结果和不必要的副作用。"),
        ("请回答：你好。不要读取 /home/gem/data.txt", "你好。"),
        ("请回答：你是谁。不要列目录", "我是本地 AIO Sandbox agent。"),
        ("请解释 /home/gem/data.txt 这个字符串，不要打开它", "/home/gem/data.txt 看起来是一个 Unix 风格的文件路径字符串。"),
        ("如果我问“什么是文件”，不要查文件", "文件是用于存储数据的命名对象，可以包含文本、图片、程序等内容。"),
        ("如果我问“什么是 shell”，不要执行命令", "shell 是命令行解释器，用来接收命令并与操作系统交互。"),
    ]
    for user, answer in tool_boundary_cases:
        samples.append(chat(user, answer))

    return samples


def main() -> None:
    chat_samples = build_chat_anchor_samples()
    tool_samples = build_tool_samples()
    result_samples = build_tool_result_answer_samples()

    # Weight tool samples enough to keep the JSON tool-call protocol, while the
    # larger chat anchor set keeps greetings and normal text tasks from drifting.
    # Result-answer samples teach the model how to turn tool_result payloads into
    # useful final answers instead of echoing raw English tool status messages.
    mixed = chat_samples + result_samples + tool_samples + tool_samples + result_samples

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as fp:
        for row in mixed:
            fp.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"Wrote {len(mixed)} mixed SFT samples to {OUT}")
    print(f"  chat_anchor={len(chat_samples)}")
    print(f"  tool_call_weighted={len(tool_samples) * 2}")
    print(f"  tool_result_answer_weighted={len(result_samples) * 2}")


if __name__ == "__main__":
    main()
