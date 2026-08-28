#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
lab_dir="$(cd "${script_dir}/.." && pwd)"
model_name="${QWEN_MLX_MODEL_NAME:-qwen3-4b-instruct-2507-mlx-4bit}"
max_tokens="${QWEN_MLX_MAX_TOKENS:-8192}"

cd "${lab_dir}/models"
exec "${lab_dir}/.venv-mlx/bin/python" -m mlx_lm.server \
  --model "${model_name}" \
  --host 0.0.0.0 \
  --port 8001 \
  --max-tokens "${max_tokens}" \
  --log-level INFO
