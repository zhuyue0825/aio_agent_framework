#!/usr/bin/env bash
set -euo pipefail

ROOT="/Users/bytedance/Documents/aio_agent_framework"
MODEL_ID="${1:-deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B}"
LOCAL_DIR="$ROOT/finetuning_lab/models/deepseek-r1-distill-qwen-1.5b"
HF_HOME_DIR="$ROOT/.hf-home"

mkdir -p "$LOCAL_DIR" "$HF_HOME_DIR" "$ROOT/.cache/matplotlib"

export HF_HOME="$HF_HOME_DIR"
export HF_HUB_DISABLE_XET=1
export MPLCONFIGDIR="$ROOT/.cache/matplotlib"

"$ROOT/.venv-train/bin/hf" download "$MODEL_ID" \
  --local-dir "$LOCAL_DIR"

echo "Model downloaded to: $LOCAL_DIR"
