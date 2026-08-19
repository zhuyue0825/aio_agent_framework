#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$ROOT_DIR"
exec "$ROOT_DIR/.venv-train/bin/python" finetuning_lab/scripts/serve_deepseek_openai.py \
  --host 0.0.0.0 \
  --port 8010 \
  --enable-tool-rules \
  "$@"
