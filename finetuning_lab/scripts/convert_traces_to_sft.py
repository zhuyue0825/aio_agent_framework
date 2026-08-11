#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


SYSTEM_PROMPT = (
    "You are an AIO Sandbox agent. Solve user tasks by choosing safe file, "
    "shell, and browser operations. Summarize the result clearly."
)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fp:
        for line_no, line in enumerate(fp, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise SystemExit(f"{path}:{line_no}: invalid JSON: {exc}") from exc
    return records


def split_runs(records: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    runs: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []

    for record in records:
        event = record.get("event")
        if event == "run_start":
            if current:
                runs.append(current)
            current = [record]
        elif current:
            current.append(record)
            if event == "run_end":
                runs.append(current)
                current = []

    if current:
        runs.append(current)

    return runs


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n...[truncated]"


def result_summary(result: dict[str, Any], max_chars: int) -> str:
    if "error" in result:
        return "ERROR: " + str(result["error"])

    data = result.get("data")
    if isinstance(data, dict):
        if "output" in data:
            return truncate(str(data["output"]), max_chars)
        if "content" in data:
            return truncate(str(data["content"]), max_chars)

    message = result.get("message")
    if message:
        return truncate(str(message), max_chars)
    return truncate(compact_json(result), max_chars)


def run_to_sample(run: list[dict[str, Any]], max_observation_chars: int) -> dict[str, Any] | None:
    start = next((r for r in run if r.get("event") == "run_start"), None)
    end = next((r for r in reversed(run) if r.get("event") == "run_end"), None)
    if not start or not end:
        return None

    start_payload = start.get("payload", {})
    end_payload = end.get("payload", {})
    if end_payload.get("status") != "completed":
        return None

    task = start_payload.get("task")
    final_answer = end_payload.get("final_answer")
    if not task or not final_answer:
        return None

    lines: list[str] = ["Plan:", "Use the available tools only when they are needed.", "", "Tool trace:"]
    saw_tool = False

    for record in run:
        if record.get("event") != "tool_call":
            continue
        payload = record.get("payload", {})
        step = payload.get("step")
        name = payload.get("name")
        arguments = payload.get("arguments", {})
        result_record = next(
            (
                r
                for r in run
                if r.get("event") == "tool_result"
                and r.get("payload", {}).get("step") == step
                and r.get("payload", {}).get("name") == name
            ),
            None,
        )
        if not name:
            continue
        saw_tool = True
        lines.append(f"- step {step}: {name}({compact_json(arguments)})")
        if result_record:
            result = result_record.get("payload", {}).get("result", {})
            lines.append(f"  observation: {result_summary(result, max_observation_chars)}")

    if not saw_tool:
        lines.append("- no tool call needed")

    lines.extend(["", "Final answer:", str(final_answer)])

    return {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": str(task)},
            {"role": "assistant", "content": "\n".join(lines)},
        ]
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert AIO Agent trace JSONL to SFT JSONL.")
    parser.add_argument("--input", required=True, help="Input trace JSONL path.")
    parser.add_argument("--output", required=True, help="Output SFT JSONL path.")
    parser.add_argument("--max-observation-chars", type=int, default=2000)
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)
    records = load_jsonl(input_path)
    runs = split_runs(records)

    samples = [
        sample
        for run in runs
        if (sample := run_to_sample(run, args.max_observation_chars)) is not None
    ]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as fp:
        for sample in samples:
            fp.write(json.dumps(sample, ensure_ascii=False) + "\n")

    print(f"Converted {len(samples)} completed runs from {input_path} to {output_path}")


if __name__ == "__main__":
    main()
