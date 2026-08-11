#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT_DIR/local/minimind.env"

cd "$ROOT_DIR"
exec "$ROOT_DIR/.venv-train/bin/python" -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
