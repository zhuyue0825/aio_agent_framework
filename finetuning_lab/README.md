# DeepSeek Fine-Tuning Lab

This folder is for a first LoRA/SFT experiment based on DeepSeek open-weight models.

Default base model:

```text
deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B
```

Why this model first:

- It is small enough for a first pipeline test.
- It follows the DeepSeek R1 reasoning style.
- It is based on Qwen, so the tokenizer and chat format are widely supported by common training tools.
- Larger variants can be swapped in later after the data pipeline works.

## Folder Layout

```text
finetuning_lab/
├── configs/
│   ├── dataset_info.json
│   └── deepseek_lora_sft.yaml
├── data/
│   ├── raw/
│   └── processed/
├── notes/
├── outputs/
└── scripts/
    ├── convert_traces_to_sft.py
    ├── prepare_deepseek_dataset.sh
    └── train_deepseek_lora.sh
```

## Stage 1 Goal

Do not try to train a strong model immediately. The first goal is:

1. Convert successful AIO Agent traces into supervised fine-tuning samples.
2. Run a small LoRA training job on DeepSeek-R1-Distill-Qwen-1.5B.
3. Verify that the training command, dataset format, and output adapter path are correct.

## Data Format

The processed dataset uses JSONL with a `messages` field:

```json
{"messages":[{"role":"system","content":"..."},{"role":"user","content":"..."},{"role":"assistant","content":"..."}]}
```

For this first pass, tool calls are represented as plain text in the assistant answer. Later, if the target runtime expects native OpenAI-style tool calls, the dataset can be upgraded to a stricter tool-call schema.

## Prepare Data

From the project root:

```bash
cd /Users/bytedance/Documents/aio_agent_framework
bash finetuning_lab/scripts/prepare_deepseek_dataset.sh
```

This reads:

```text
traces/latest.jsonl
```

and writes:

```text
finetuning_lab/data/processed/aio_agent_sft.jsonl
```

## Train

This lab uses LLaMA-Factory for the first training path because it avoids writing low-level PEFT/TRL boilerplate by hand.

Install LLaMA-Factory separately, then run:

```bash
cd /Users/bytedance/Documents/aio_agent_framework
bash finetuning_lab/scripts/train_deepseek_lora.sh
```

The LoRA adapter will be written under:

```text
finetuning_lab/outputs/deepseek-r1-distill-qwen-1.5b-lora
```

## Important Notes

- A MacBook can prepare data and run very small experiments, but practical training is usually smoother on an NVIDIA GPU.
- This setup trains a LoRA adapter, not a full model.
- Do not put private API keys, production secrets, or sensitive user data into the training dataset.
- License terms still matter. If you switch to another DeepSeek distilled model, check the base model license too, especially Llama-based distill variants.
