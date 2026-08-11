# Apple MPS Smoke Run

Date: 2026-07-07

## Problem

Inside the default Codex sandbox, PyTorch reported:

```text
torch.backends.mps.is_built() = True
torch.backends.mps.is_available() = False
```

This meant the installed PyTorch build supported MPS, but the sandboxed process could not see the Apple Metal device.

## Fix

Run the training process outside the sandbox permission boundary. The same virtual environment then reported:

```text
mps built True
mps available True
```

A direct tensor test also succeeded on `mps:0`.

The training script now sets:

```text
PYTORCH_ENABLE_MPS_FALLBACK=1
```

This allows unsupported MPS ops to fall back to CPU instead of failing immediately.

## Completed MPS Training

Command:

```bash
bash finetuning_lab/scripts/train_deepseek_lora.sh \
  finetuning_lab/configs/deepseek_lora_sft_mps_smoke.yaml
```

Result:

```text
device: mps
compute dtype: torch.float16
max steps: 1
trainable LoRA params: 4,616,192
total model params: 1,781,704,192
train loss: 4.6437
runtime: 5.45 seconds
```

Output:

```text
/Users/bytedance/Documents/aio_agent_framework/finetuning_lab/outputs/deepseek-r1-distill-qwen-1.5b-lora-mps-smoke
```

Important file:

```text
adapter_model.safetensors
```

## Comparison

The previous CPU smoke run took about 6 minutes 7 seconds for 1 step.

The MPS smoke run took about 5.45 seconds for 1 step.

The speed difference confirms that Apple GPU acceleration is working when the training command is run outside the sandbox boundary.
