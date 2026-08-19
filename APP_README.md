# AIO Agent Web App

当前 Web App 已拆成“Java 业务控制面 + Python Agent 执行面”。浏览器只访问 Spring Boot；FastAPI 不再创建会话，也不再读写 SQLite。

```text
React / Vite :5173
        │ JWT + /api/v1
        ▼
Spring Boot :8081
  ├─ 登录、用户、项目成员授权
  ├─ 会话、消息、Agent 任务状态
  ├─ 幂等、超时、取消、SSE、Trace ID
  └─ PostgreSQL + Flyway + Actuator
        │ X-Internal-Token + /internal/v1
        ▼
FastAPI :8000
  ├─ 接收 task + history，不访问业务数据库
  ├─ AgentRuntime / 模型 / 工具循环
  └─ 受项目根目录约束的文件能力
```

## 目录

```text
aio_agent_framework/
├── business-service/       # Java 21 / Spring Boot 4.1 业务服务
│   ├── mvnw                # Maven Wrapper，不要求全局安装 Maven
│   └── src/
│       ├── main/java/      # auth/project/conversation/run/internal
│       ├── main/resources/db/migration/
│       └── test/           # JUnit + Testcontainers(PostgreSQL)
├── backend/                # FastAPI 内部 Agent 执行服务
│   ├── main.py             # /internal/v1 API
│   ├── workspace.py        # 文件树与越界保护
│   └── tests/              # Java↔Python 接口契约测试
├── agent_framework/        # 现有 AgentRuntime、模型与工具能力
├── frontend/               # React / Vite
├── data/app.sqlite3        # 只作为旧数据迁移源
├── traces/                 # 带 trace_id/run_id 的 Agent JSONL
└── docker-compose.yml
```

## 最快启动

1. 本机体验可以直接启动，无需先创建 `.env`。部署到服务器时，再复制生产配置模板（不要提交真实密钥）：

```bash
cp .env.example .env
```

服务器部署至少要修改管理员密码、JWT Secret 和内部服务 Token。模型 API Key 可以在管理员登录后的“模型设置”里填写；如果需要用环境变量自动初始化，也仍可设置 `MODEL_API_KEY`。

2. 启动 PostgreSQL、Sandbox、Python 与 Java：

```bash
docker compose up -d --build
docker compose ps
```

3. 启动前端：

```bash
cd frontend
npm install
npm run dev
```

打开 `http://127.0.0.1:5173`。若没有复制 `.env.example`，本地开发默认管理员为 `admin / aio-local-admin`；只用于本机演示。

Compose 会把仓库挂载到 Python 容器的 `/workspace/aio_agent_framework`。使用 Compose 时，在“项目工作”里打开这个容器路径；直接在宿主机运行 FastAPI 时，可以打开宿主机路径。

### 在页面里切换模型

使用管理员账号登录后，点击右上角当前模型即可打开“模型设置”：

- `远程 API`：填写 DeepSeek 或其他 OpenAI Chat Completions 兼容接口、模型名和 API Key。
- `本地模型`：填写宿主机上的 OpenAI 兼容地址，Compose 默认使用 `http://host.docker.internal:8010/v1`。
- “保存并应用”会让下一次对话使用新模型；“保存并测试”会额外发起一次最小模型请求。

API Key 只由浏览器发送给 Spring Boot，再通过内部令牌转发给 FastAPI。FastAPI 将它写入 Git 忽略的 `data/model-settings.json`，文件权限为 `600`；读取设置时只返回 `api_key_configured`，不会把 Key 回传到浏览器。

启动仓库内置的本地 DeepSeek 兼容服务：

```bash
./scripts/run_local_deepseek_api.sh
```

它在宿主机 `8010` 端口提供接口。当前 Compose 中的 Agent 容器通过 `host.docker.internal` 访问该服务；仅在可信网络中运行这个无鉴权的本地端口。

## 本地开发

Java 需要 JDK 21，Maven 使用仓库中的 Wrapper：

```bash
cd business-service
export JAVA_HOME=/path/to/jdk-21
./mvnw spring-boot:run
```

Python 环境应在每台电脑上重建，`.venv/` 不上传：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements-dev.txt
INTERNAL_SERVICE_TOKEN=local-internal-token-change-before-production \
  .venv/bin/uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

前端代理已指向 Spring Boot `8081`，不再指向 FastAPI `8000`。

## 业务 API

公开 API 均由 Spring Boot 提供：

- `POST /api/v1/auth/register`、`POST /api/v1/auth/login`、`GET /api/v1/auth/me`
- `GET|POST /api/v1/conversations`
- `GET /api/v1/conversations/{id}/messages`
- `POST /api/v1/conversations/{id}/runs`（要求 `Idempotency-Key`）
- `GET|DELETE /api/v1/runs/{id}`
- `GET /api/v1/runs/{id}/events`（SSE）
- `GET /api/v1/projects`、`POST /api/v1/projects/open`
- 项目成员与项目工作区文件 API
- `GET /actuator/health`、`/actuator/metrics`、`/actuator/prometheus`

FastAPI 只暴露带 `X-Internal-Token` 的 `/internal/v1/agent/*` 与 `/internal/v1/workspaces/*`，不向前端提供会话 API。

## 异步任务流程

1. Java 校验 JWT、会话所有权和项目成员关系。
2. Java 保存用户消息和 `PENDING` 任务；数据库唯一约束保证同一会话只能有一个活动任务。
3. Java 异步调用 Python，传入历史消息、受信任项目路径、Trace ID 和回调地址。
4. Python 在模型步和工具步之间检查取消标记，并把进度回调给 Java。
5. Java 持久化事件并通过 SSE 推给前端；成功、失败、取消和超时都是明确终态。
6. 前端可查询或取消任务，SSE 断开时自动退回轮询。

## SQLite 迁移

`AIO_LEGACY_IMPORT_ENABLED=true` 时，Java 启动后会只读扫描 `data/app.sqlite3`，把会话和消息导入 PostgreSQL，并在 `legacy_imports` 记录导入结果。再次启动不会重复导入。Hibernate 使用 `ddl-auto=validate`，建表与变更只由 Flyway SQL 管理。

当前实机迁移验证结果：35 个会话、176 条消息。

## 验证

```bash
# Java：真实 PostgreSQL Testcontainers、JWT、幂等、项目授权、SQLite 导入
cd business-service
export JAVA_HOME=/path/to/jdk-21
./mvnw test

# Python 内部接口契约
cd ..
.venv/bin/python -m pytest -q backend/tests

# React 类型检查与生产构建
cd frontend
npm run build
```

停止服务但保留 PostgreSQL 数据：

```bash
docker compose down
```

`docker compose down -v` 会删除 PostgreSQL 卷，只应在明确要清空数据时使用。
