#!/usr/bin/env bash
set -euo pipefail

ROOT="/Users/bytedance/Documents/aio_agent_framework"
TRACE_PATH="$ROOT/traces/latest.jsonl"
DATASET_PATH="$ROOT/finetuning_lab/data/processed/aio_agent_sft.jsonl"
CONFIG_PATH="$ROOT/finetuning_lab/configs/deepseek_lora_sft.yaml"
OUTPUT_DIR="$ROOT/finetuning_lab/outputs/deepseek-r1-distill-qwen-1.5b-lora"
SMOKE_OUTPUT_DIR="$ROOT/finetuning_lab/outputs/deepseek-r1-distill-qwen-1.5b-lora-smoke"
MODEL_DIR="$ROOT/finetuning_lab/models/deepseek-r1-distill-qwen-1.5b"
LOCAL_TRAINER="$ROOT/.venv-train/bin/llamafactory-cli"

echo "DeepSeek LoRA/SFT flow"
echo

echo "1. Source trace"
echo "   $TRACE_PATH"
if [[ -f "$TRACE_PATH" ]]; then
  echo "   OK: trace exists"
else
  echo "   MISSING: trace does not exist"
fi
echo

echo "2. Convert trace to SFT dataset"
echo "   bash $ROOT/finetuning_lab/scripts/prepare_deepseek_dataset.sh"
if [[ -f "$DATASET_PATH" ]]; then
  echo "   OK: dataset exists ($(wc -l < "$DATASET_PATH" | tr -d ' ') samples)"
else
  echo "   MISSING: dataset has not been generated"
fi
echo

echo "3. Training config"
echo "   $CONFIG_PATH"
if [[ -f "$CONFIG_PATH" ]]; then
  echo "   OK: config exists"
  echo "   Model: $(awk -F': ' '/^model_name_or_path:/ {print $2}' "$CONFIG_PATH")"
  echo "   Dataset: $(awk -F': ' '/^dataset:/ {print $2}' "$CONFIG_PATH")"
  echo "   Output: $(awk -F': ' '/^output_dir:/ {print $2}' "$CONFIG_PATH")"
else
  echo "   MISSING: config does not exist"
fi
echo

echo "4. Local DeepSeek weights"
echo "   $MODEL_DIR"
if [[ -f "$MODEL_DIR/config.json" ]]; then
  echo "   OK: model appears downloaded"
else
  echo "   NOT YET: run $ROOT/finetuning_lab/scripts/download_deepseek_model.sh"
fi
echo

echo "5. Trainer"
if [[ -x "$LOCAL_TRAINER" ]]; then
  echo "   OK: $LOCAL_TRAINER"
elif command -v llamafactory-cli >/dev/null 2>&1; then
  LOCAL_TRAINER="$(command -v llamafactory-cli)"
  echo "   OK: $LOCAL_TRAINER"
else
echo "   MISSING: llamafactory-cli is not installed"
fi
echo

echo "6. Real training command"
echo "   $LOCAL_TRAINER train $CONFIG_PATH"
echo "   Smoke run: $ROOT/finetuning_lab/scripts/train_deepseek_lora.sh $ROOT/finetuning_lab/configs/deepseek_lora_sft_smoke.yaml"
echo

echo "7. Expected LoRA adapter output"
echo "   $OUTPUT_DIR"
if [[ -d "$OUTPUT_DIR" ]]; then
  echo "   EXISTS: output directory is present"
else
  echo "   NOT YET: output directory will be created by training"
fi
echo

echo "8. Smoke LoRA adapter output"
echo "   $SMOKE_OUTPUT_DIR"
if [[ -f "$SMOKE_OUTPUT_DIR/adapter_model.safetensors" ]]; then
  echo "   OK: smoke adapter exists"
else
  echo "   NOT YET: run the smoke training command first"
fi
