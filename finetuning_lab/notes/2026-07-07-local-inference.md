# Local DeepSeek Inference

Date: 2026-07-07

## Completed

Added a local inference script:

```text
/Users/bytedance/Documents/aio_agent_framework/finetuning_lab/scripts/ask_deepseek.py
```

It can run either:

- the original local DeepSeek 1.5B model
- the original model plus a LoRA adapter

## Commands

Base model:

```bash
.venv-train/bin/python finetuning_lab/scripts/ask_deepseek.py \
  "你好，用一句话介绍你自己。" \
  --max-new-tokens 80
```

Base model plus smoke adapter:

```bash
.venv-train/bin/python finetuning_lab/scripts/ask_deepseek.py \
  "你好，用一句话介绍你自己。" \
  --use-smoke-adapter \
  --max-new-tokens 80
```

These commands need to run outside the Codex sandbox boundary if Apple MPS should be used.

## Tokenizer Fix

The downloaded local model directory had:

```json
"tokenizer_class": "LlamaTokenizerFast"
```

With this setting, `AutoTokenizer` did not tokenize Chinese text correctly in the current Transformers environment. The local `tokenizer_config.json` was patched to:

```json
"tokenizer_class": "Qwen2TokenizerFast"
```

The inference script also explicitly uses `Qwen2TokenizerFast`.

## Observation

The smoke LoRA adapter was trained for only one step, so its answer is currently almost identical to the base model. This is expected; the adapter is useful as a workflow proof, not as a quality improvement.
