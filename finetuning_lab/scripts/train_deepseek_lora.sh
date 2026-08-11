#!/usr/bin/env bash
set -euo pipefail

ROOT="/Users/bytedance/Documents/aio_agent_framework"
CONFIG="${1:-$ROOT/finetuning_lab/configs/deepseek_lora_sft.yaml}"
LOCAL_TRAINER="$ROOT/.venv-train/bin/llamafactory-cli"

if [[ -x "$LOCAL_TRAINER" ]]; then
  TRAINER="$LOCAL_TRAINER"
elif command -v llamafactory-cli >/dev/null 2>&1; then
  TRAINER="$(command -v llamafactory-cli)"
else
  echo "llamafactory-cli was not found."
  echo "Install LLaMA-Factory first, then rerun this script."
  echo "Project: https://github.com/hiyouga/LLaMA-Factory"
  exit 1
fi

mkdir -p "$ROOT/.cache/matplotlib" "$ROOT/.hf-home"

export HF_HOME="$ROOT/.hf-home"
export MPLCONFIGDIR="$ROOT/.cache/matplotlib"
export PYTORCH_ENABLE_MPS_FALLBACK=1

"$TRAINER" train "$CONFIG"
