#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, Qwen2TokenizerFast


ROOT = Path("/Users/bytedance/Documents/aio_agent_framework")
DEFAULT_MODEL = ROOT / "finetuning_lab/models/deepseek-r1-distill-qwen-1.5b"
DEFAULT_ADAPTER = ROOT / "finetuning_lab/outputs/deepseek-r1-distill-qwen-1.5b-lora-mps-smoke"


def pick_device() -> str:
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def main() -> None:
    parser = argparse.ArgumentParser(description="Ask the local DeepSeek 1.5B model.")
    parser.add_argument("prompt", help="Question or task for the model.")
    parser.add_argument("--model", default=str(DEFAULT_MODEL), help="Local base model path.")
    parser.add_argument("--adapter", default=None, help="Optional LoRA adapter path.")
    parser.add_argument("--use-smoke-adapter", action="store_true", help="Load the MPS smoke LoRA adapter.")
    parser.add_argument("--max-new-tokens", type=int, default=256)
    args = parser.parse_args()

    device = pick_device()
    dtype = torch.float16 if device == "mps" else torch.float32

    tokenizer = Qwen2TokenizerFast.from_pretrained(args.model, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        args.model,
        dtype=dtype,
        low_cpu_mem_usage=True,
        trust_remote_code=True,
    )

    adapter_path = str(DEFAULT_ADAPTER) if args.use_smoke_adapter else args.adapter
    if adapter_path:
        model = PeftModel.from_pretrained(model, adapter_path)

    model.to(device)
    model.eval()

    messages = [{"role": "user", "content": args.prompt}]
    prompt_text = tokenizer.apply_chat_template(
        messages,
        add_generation_prompt=True,
        tokenize=False,
    )
    inputs = tokenizer(prompt_text, return_tensors="pt").to(device)

    with torch.no_grad():
        output_ids = model.generate(
            **inputs,
            max_new_tokens=args.max_new_tokens,
            do_sample=False,
            pad_token_id=tokenizer.eos_token_id,
        )

    new_tokens = output_ids[0, inputs["input_ids"].shape[-1] :]
    print(tokenizer.decode(new_tokens, skip_special_tokens=True).strip())


if __name__ == "__main__":
    main()
