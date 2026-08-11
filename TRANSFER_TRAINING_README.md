# AIO Agent Training Bundle

This bundle is for moving the current local AIO Agent app and DeepSeek LoRA training setup to another machine.

## Included

- App/runtime code:
  - `agent_framework/`
  - `backend/`
  - `frontend/` without `node_modules`
- Training lab:
  - `finetuning_lab/configs/`
  - `finetuning_lab/data/`
  - `finetuning_lab/scripts/`
  - `finetuning_lab/notes/`
  - `finetuning_lab/models/deepseek-r1-distill-qwen-1.5b/`
  - `finetuning_lab/outputs/deepseek-r1-distill-qwen-1.5b-lora-mixed-chat-tool-mps/`
- Optional local state:
  - `data/`
  - `traces/`
  - `screenshots/`

## Not Included

- `.venv-train/`
- `frontend/node_modules/`
- `.cache/`
- `.hf-home/`
- `__pycache__/`

These are machine-local dependency/cache folders and should be recreated on the target machine.

## Setup On Target Machine

From the extracted project root:

```bash
python3 -m venv .venv-train
source .venv-train/bin/activate
pip install -r backend/requirements.txt
pip install torch transformers peft
```

If you want to continue training:

```bash
pip install llamafactory
```

Install frontend dependencies:

```bash
cd frontend
npm install
```

Start AIO Sandbox:

```bash
docker run -d --name aio-sandbox-demo \
  --security-opt seccomp=unconfined \
  -p 127.0.0.1:8080:8080 \
  enterprise-public-cn-beijing.cr.volces.com/vefaas-public/all-in-one-sandbox:1.11.0
```

Start the local DeepSeek OpenAI-compatible model service:

```bash
cd /path/to/aio_agent_framework
source .venv-train/bin/activate
python finetuning_lab/scripts/serve_deepseek_openai.py \
  --host 127.0.0.1 \
  --port 8010 \
  --model /path/to/aio_agent_framework/finetuning_lab/models/deepseek-r1-distill-qwen-1.5b \
  --adapter /path/to/aio_agent_framework/finetuning_lab/outputs/deepseek-r1-distill-qwen-1.5b-lora-mixed-chat-tool-mps \
  --name local-deepseek-r1-distill-qwen-1.5b
```

Start backend:

```bash
cd /path/to/aio_agent_framework
source .venv-train/bin/activate
export AIO_SANDBOX_URL=http://127.0.0.1:8080
export MODEL_API_BASE=http://127.0.0.1:8010/v1
export MODEL_API_KEY=local
export MODEL_NAME=local-deepseek-r1-distill-qwen-1.5b
export AGENT_MAX_STEPS=8
uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Start frontend:

```bash
cd /path/to/aio_agent_framework/frontend
npm run dev
```

Open:

```text
http://127.0.0.1:5173
```

## Continue Training

The current mixed training config is:

```text
finetuning_lab/configs/deepseek_lora_mixed_chat_tool_mps.yaml
```

Run:

```bash
cd /path/to/aio_agent_framework
source .venv-train/bin/activate
bash finetuning_lab/scripts/train_deepseek_lora.sh finetuning_lab/configs/deepseek_lora_mixed_chat_tool_mps.yaml
```

If the target path is not `/Users/bytedance/Documents/aio_agent_framework`, update absolute paths in the YAML configs before training.
