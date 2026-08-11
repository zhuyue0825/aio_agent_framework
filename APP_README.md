# AIO Agent Local Web App

This is the structured local app version of the AIO Agent demo.

## Structure

```text
aio_agent_framework/
├── agent_framework/        # Reusable agent runtime library
├── backend/                # FastAPI backend
│   ├── main.py             # HTTP API
│   ├── db.py               # SQLite conversations/messages
│   ├── workspace.py        # Local project tree and bounded file access
│   ├── agent_runtime.py    # Runtime re-export
│   ├── tools.py            # Tool registry re-export
│   ├── sandbox_client.py   # AIO Sandbox client re-export
│   └── approval.py         # Approval policy re-export
├── frontend/               # React/Vite frontend
│   ├── src/App.tsx
│   ├── src/Chat.tsx
│   ├── src/Sidebar.tsx
│   ├── src/CodePreview.tsx
│   ├── src/FolderPicker.tsx
│   └── src/api.ts
├── data/                   # SQLite app data
├── traces/                 # Agent trace logs
└── docker-compose.yml
```

## Run locally

Start AIO Sandbox first:

```bash
docker run -d --name aio-sandbox-demo \
  --security-opt seccomp=unconfined \
  -p 127.0.0.1:8080:8080 \
  enterprise-public-cn-beijing.cr.volces.com/vefaas-public/all-in-one-sandbox:1.11.0
```

Install backend dependencies:

```bash
cd /Users/bytedance/Documents/aio_agent_framework
python3 -m pip install -r backend/requirements.txt
```

Start the backend:

```bash
cd /Users/bytedance/Documents/aio_agent_framework
export AIO_SANDBOX_URL=http://127.0.0.1:8080
export MODEL_API_BASE=https://openrouter.ai/api/v1
export MODEL_API_KEY=your_key
export MODEL_NAME=nvidia/nemotron-3-ultra-550b-a55b:free
export AGENT_MAX_STEPS=16
uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Start the frontend:

```bash
cd /Users/bytedance/Documents/aio_agent_framework/frontend
npm install
npm run dev
```

Open:

```text
http://127.0.0.1:5173
```

## API

- `GET /api/status`
- `GET /api/conversations`
- `POST /api/conversations`
- `GET /api/conversations/{id}/messages`
- `POST /api/conversations/{id}/run`
- `GET /api/workspace/directories`
- `POST /api/workspace/open`
- `GET /api/workspace/tree`
- `GET /api/workspace/file`
- `PUT /api/workspace/file`
- `POST /api/tool-demo`

## App modes

- `纯对话` only sends conversation messages to the model and never opens project tools.
- `项目工作` opens one explicit local folder. The left panel shows its file tree, the Agent receives path-bounded read/write/search tools, and the right panel previews or edits text files.
- Project paths are resolved against the opened root; `..`, absolute paths outside the root, symlink escapes, binary previews, and oversized previews are rejected.
- Files changed during an Agent run are returned as `changed_files`, marked in the tree, and opened in the preview automatically.

## Notes

- API keys are read by the backend from environment variables, not stored in the frontend.
- Conversations and messages are stored in SQLite at `data/app.sqlite3`.
- Agent traces are written to `traces/app.jsonl`.
- Tool execution quality still depends on the configured model. The 64M MiniMind model is suitable for pipeline experiments but may answer without issuing tool calls; the built-in editor remains available for direct changes.
