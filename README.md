# AIO Sandbox Agent Framework

这是一个教学版 Agent 框架，用来说明 Claude Code / Codex 这类工具的核心骨架。

它不是把模型放进沙箱里，而是：

```text
Agent Runtime 跑在沙箱外
  -> 模型决定下一步
  -> Runtime 调用工具
  -> 工具通过 REST API 操作 AIO Sandbox
  -> 工具结果回填给模型
  -> 循环直到完成任务
```

## 文件结构

```text
aio_agent_framework/
├── cli.py
├── README.md
├── APP_README.md
├── business-service/        # Spring Boot 业务控制面
│   ├── mvnw
│   └── src/
├── backend/
│   ├── main.py              # FastAPI 内部 Agent API
│   └── workspace.py
├── frontend/
│   ├── src/App.tsx
│   ├── src/Chat.tsx
│   ├── src/Sidebar.tsx
│   └── src/api.ts
├── examples/
│   └── create_and_run_python.md
└── agent_framework/
    ├── __init__.py
    ├── approval.py
    ├── config.py
    ├── http_json.py
    ├── mcp.py
    ├── model.py
    ├── runtime.py
    ├── sandbox.py
    ├── trace.py
    ├── tools.py
    └── web.py
```

## 每个模块做什么

- `config.py`：从环境变量读取模型地址、key、模型名、沙箱地址。
- `http_json.py`：最小 HTTP JSON POST 封装。
- `sandbox.py`：AIO Sandbox REST API 客户端。
- `tools.py`：工具注册表，把 Python 函数包装成模型可调用的 tool。
- `model.py`：OpenAI-compatible Chat Completions 客户端。
- `runtime.py`：Agent 主循环，负责模型调用、工具执行、结果回填。
- `approval.py`：工具调用审批策略，拦截危险 shell 和越界写文件。
- `trace.py`：把每一步运行轨迹写成 JSONL。
- `mcp.py`：最小 MCP HTTP 客户端，把 `/v1/mcp` 暴露的工具接入 Agent。
- `web.py`：无依赖 Web UI，页面里输入任务并查看结果。
- `cli.py`：命令行入口。
- `business-service/`：Java 21 / Spring Boot 4.1 业务服务，负责认证、项目授权、会话消息、任务状态、PostgreSQL、SSE 和可观测性。
- `backend/`：FastAPI Agent 执行服务，只接收 Java 传入的任务与历史消息，不访问业务数据库。
- `backend/workspace.py`：本地项目目录树、文件预览、受项目根目录约束的读写与搜索能力。
- `frontend/`：React/Vite 前端，支持纯对话、项目文件树和右侧代码预览/编辑。
- `APP_README.md`：本地 Web App 的启动说明。

## 先验证沙箱工具

不需要模型 key：

```bash
cd /path/to/aio_agent_framework
python3 cli.py --demo
```

会验证：

- `shell_exec`
- `file_write`
- `file_read`
- `browser_navigate`

## 接模型运行

```bash
cd /path/to/aio_agent_framework

export MODEL_API_BASE="https://your-model-host/v1"
export MODEL_API_KEY="your-key"
export MODEL_NAME="your-model-name"
export AIO_SANDBOX_URL="http://127.0.0.1:8080"

python3 cli.py "在沙箱里创建 /home/gem/hello.py，运行它，然后告诉我输出"
```

## 权限审批

默认模式是：

```bash
--approval never
```

含义是：安全工具调用直接放行，明显危险的调用直接拒绝，比如：

- `rm -rf /`
- `sudo ...`
- `curl ... | sh`
- 写 `/home/gem` 以外的路径

也可以改成交互确认：

```bash
python3 cli.py --approval ask "删除 /home/gem/tmp.txt"
```

或者学习阶段全放行：

```bash
python3 cli.py --approval auto "..."
```

## Trace 日志

默认 trace 文件：

```bash
/path/to/aio_agent_framework/traces/latest.jsonl
```

每一行是一条 JSON 事件，包括：

- `run_start`
- `model_message`
- `tool_call`
- `approval`
- `tool_result`
- `run_end`

自定义 trace 路径：

```bash
python3 cli.py \
  --trace /path/to/aio_agent_framework/traces/run-001.jsonl \
  "在沙箱里列出当前目录"
```

查看 trace：

```bash
tail -n 20 /path/to/aio_agent_framework/traces/latest.jsonl
```

## MCP 工具模式

默认使用 REST 工具：

```bash
python3 cli.py --tools rest "..."
```

查看 AIO Sandbox 暴露了哪些 MCP 工具：

```bash
python3 cli.py --mcp-list
```

用 MCP 工具运行 Agent：

```bash
python3 cli.py --tools mcp "在沙箱里执行 pwd，并告诉我结果"
```

默认 MCP 地址是：

```bash
http://127.0.0.1:8080/v1/mcp
```

也可以手动指定：

```bash
python3 cli.py --tools mcp --mcp-url http://127.0.0.1:8080/v1/mcp "..."
```

REST 模式适合学习每个 API 怎么调；MCP 模式更接近“把沙箱能力挂给现成 Agent 框架”。

## Web UI

### 轻量教学版

启动无依赖页面：

```bash
cd /path/to/aio_agent_framework
python3 cli.py --web --port 8765
```

打开：

```bash
http://127.0.0.1:8765
```

页面里有两个按钮：

- `Run Tool Demo`：不需要模型 key，只验证沙箱工具。
- `Run Agent`：需要配置模型环境变量，让模型自己决定工具调用。

### 正规本地 Web App

这个版本拆成 React、Spring Boot 业务服务、FastAPI Agent 执行服务和 PostgreSQL。完整说明见 `APP_README.md`。

```bash
cd /path/to/aio_agent_framework
cp .env.example .env
# 填写 .env 中数据库密码、管理员密码、JWT Secret 和内部 Token
docker compose up -d --build
```

再启动前端：

```bash
cd /path/to/aio_agent_framework/frontend
npm install
npm run dev
```

打开：

```text
http://127.0.0.1:5173
```

当前版本支持：

- Spring Security 登录、JWT 和项目成员授权。
- PostgreSQL 保存会话、消息、项目、任务和事件，Flyway 管理表结构。
- 旧 `data/app.sqlite3` 只作为幂等迁移源，不再由 FastAPI 读写。
- 显式切换“纯对话”和“项目工作”，不再通过关键词猜测是否调用工具。
- 在应用内打开本地文件夹，左侧浏览目录树，右侧预览、编辑和保存文本代码文件。
- Agent 修改文件后刷新目录树、标记本次修改，并自动打开首个修改文件。
- 项目文件 API 会阻止 `..`、绝对路径和符号链接逃逸到已打开目录之外。
- Java 提供异步任务、幂等键、超时、取消、SSE、Trace ID、Actuator 和 Prometheus 指标。
- FastAPI 只提供带内部令牌的 Agent/工作区接口。
- 模型 Key 只保存在后端环境变量或本机配置文件中，不进入前端存储，也不会由设置接口回显。
- 管理员可在页面右上角切换本地模型与远程 API；Key 仅保存在 Git 忽略的后端本机配置文件中，不会由接口回显。
- 公网部署使用生产 Nginx/HTTPS 入口，仅发布 `443`；详见 `DEPLOYMENT.md`。
- 公开注册默认关闭，Python 服务以非 root 用户运行且只能访问配置的工作区根目录。
- 全服务 healthcheck、自动重启和日志轮转，PostgreSQL 定时备份，以及应用服务结构化日志和跨服务 `trace_id`。
- GitHub Actions 自动检查 Java、Python、前端构建与 Compose 配置。

## 当前内置工具

- `shell_exec(command)`：在 AIO Sandbox 里执行 shell 命令。
- `file_read(file)`：读取沙箱文件。
- `file_write(file, content)`：写入沙箱文件。
- `browser_navigate(url)`：让沙箱浏览器打开 URL。
- `browser_screenshot()`：给沙箱浏览器截图。

## 后续可以继续加的东西

- 权限审批：危险命令、联网、删除文件前先问用户。
- 任务 trace：把每一步工具调用保存成 JSONL。
- MCP 支持：不直接写 REST tools，而是接 `/v1/mcp`。
- Browser tools：click、type、get_text、screenshot 保存。
- 多工作区管理：保存最近打开目录，并支持为不同对话绑定不同项目。
- 成本统计：记录 token、模型调用次数、耗时。
- Web UI：页面输入任务，实时显示 tool call。
