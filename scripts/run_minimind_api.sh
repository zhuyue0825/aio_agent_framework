#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$ROOT_DIR/minimind/scripts"
exec "$ROOT_DIR/.venv-train/bin/python" serve_openai_api.py --weight full_sft --device cpu
