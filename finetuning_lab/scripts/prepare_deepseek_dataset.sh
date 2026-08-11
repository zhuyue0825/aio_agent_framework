#!/usr/bin/env bash
set -euo pipefail

ROOT="/Users/bytedance/Documents/aio_agent_framework"
TRACE_PATH="${1:-$ROOT/traces/latest.jsonl}"
OUTPUT_PATH="$ROOT/finetuning_lab/data/processed/aio_agent_sft.jsonl"

python3 "$ROOT/finetuning_lab/scripts/convert_traces_to_sft.py" \
  --input "$TRACE_PATH" \
  --output "$OUTPUT_PATH"

echo "Dataset written to: $OUTPUT_PATH"
