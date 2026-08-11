# DeepSeek LoRA Smoke Run

Date: 2026-07-07

## Completed

- Installed LLaMA-Factory into the project virtual environment:
  - `/Users/bytedance/Documents/aio_agent_framework/.venv-train`
- Downloaded DeepSeek model weights:
  - model: `deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B`
  - path: `/Users/bytedance/Documents/aio_agent_framework/finetuning_lab/models/deepseek-r1-distill-qwen-1.5b`
  - main weight file: `model.safetensors`
- Ran a real LoRA SFT smoke training job:
  - config: `/Users/bytedance/Documents/aio_agent_framework/finetuning_lab/configs/deepseek_lora_sft_smoke.yaml`
  - command: `bash finetuning_lab/scripts/train_deepseek_lora.sh finetuning_lab/configs/deepseek_lora_sft_smoke.yaml`
  - device: CPU
  - max steps: 1
  - training samples used: 2
  - trainable LoRA params: 4,616,192
  - total model params: 1,781,704,192
  - train loss: 4.6391
  - runtime: 6 minutes 7 seconds

## Output

LoRA adapter output:

```text
/Users/bytedance/Documents/aio_agent_framework/finetuning_lab/outputs/deepseek-r1-distill-qwen-1.5b-lora-smoke
```

Important files:

```text
adapter_config.json
adapter_model.safetensors
trainer_log.jsonl
trainer_state.json
train_results.json
```

## Observation

PyTorch did not report MPS as available in this environment, so the smoke run used CPU. The run completed successfully, but even one step took about 6 minutes. A practical training run should use a GPU/MPS-enabled environment or a remote NVIDIA GPU machine.
