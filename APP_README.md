# AIO Agent Web App

当前 Web App 已拆成“Java 业务控制面 + Python Agent 执行面”。浏览器只访问 Spring Boot；FastAPI 不再创建会话，也不再读写 SQLite。

```text
React / Vite :5173
        │ JWT + /api/v1
        ▼
Spring Boot :8081
  ├─ 登录、Refresh Token、限流、用户与项目授权
  ├─ 会话、消息、Agent 任务状态
  ├─ 幂等、恢复、取消、SSE、Trace ID
  └─ PostgreSQL + Redis + Flyway + Actuator
        │ X-Internal-Token + /internal/v1
        ▼
FastAPI :8000
  ├─ 接收 task + history，不访问业务数据库
  ├─ 流式模型调用、重试、指标与主动中断
  └─ 隔离工作区、暂存 diff 与确认写入
```

## 目录

```text
aio_agent_framework/
├── business-service/       # Java 21 / Spring Boot 4.1 业务服务
│   ├── mvnw                # Maven Wrapper，不要求全局安装 Maven
│   └── src/
│       ├── main/java/      # auth/project/conversation/run/internal
│       ├── main/resources/db/migration/
│       └── test/           # JUnit + Testcontainers(PostgreSQL/Redis)
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

1. 首次启动先复制配置模板（不要提交真实密钥）：

```bash
cp .env.example .env
chmod 600 .env
```

必须替换 PostgreSQL、Redis 密码、管理员密码、JWT Secret 和内部服务 Token；应用不再提供这些值的开发默认值。JWT Secret 与内部 Token 至少使用 32 个字符，管理员密码至少 12 个字符。模型 API Key 可以在管理员登录后的“模型设置”里填写；如果需要用环境变量自动初始化，也仍可设置 `MODEL_API_KEY`。

2. 确认 MiniMind 权重位于 `minimind/out/full_sft_768.pth`，然后启动 PostgreSQL、Redis、MiniMind、Sandbox、Python 与 Java：

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

打开 `http://127.0.0.1:5173`，使用 `.env` 中配置的 bootstrap admin 登录。公开注册默认关闭；只有显式设置 `AIO_PUBLIC_REGISTRATION_ENABLED=true` 时，登录页和注册接口才允许创建普通用户。

Compose 会把仓库挂载到 Python 容器的 `/workspace/aio_agent_framework`。使用 Compose 时，在“项目工作”里打开这个容器路径；直接在宿主机运行 FastAPI 时，可以打开宿主机路径。

公网生产部署使用独立的 `docker-compose.prod.yml`，仅对外发布 Nginx `443`，完整步骤见 [`DEPLOYMENT.md`](DEPLOYMENT.md)。

### 在页面里切换模型

每个用户都可以在页面右上角为当前对话选择模型，选择会保存在该对话上，不影响其他用户或其他对话：

- `MiniMind`：使用仓库内置的本地模型。
- `DeepSeek`：使用管理员在服务端配置的远程模型；普通用户不会看到或提交 API Key。
- DeepSeek 默认每个用户每天最多创建 20 个运行，按 `Asia/Shanghai` 自然日重置。使用 `AIO_DEEPSEEK_RUNS_PER_USER_PER_DAY` 和 `AIO_QUOTA_TIME_ZONE` 可调整；设为 `0` 表示不限制运行次数。

管理员可以点击模型选择器旁边的设置按钮维护服务端配置：

- `远程 API`：填写白名单内的 DeepSeek 或其他 OpenAI Chat Completions 兼容接口、模型名和 API Key。
- `本地模型`：使用仓库内置 MiniMind，Compose 默认连接内部地址 `http://minimind:8998/v1`，模型名为 `minimind`。
- “保存配置”只更新服务端模型资料；“保存并测试”会额外对当前测试目标发起一次最小模型请求。实际运行使用各对话自己的模型选择。

本机 Qwen3 MLX 服务使用 `finetuning_lab/scripts/serve_qwen3_mlx.sh` 启动。应用请求不设置 `max_tokens`，回答会自然生成到模型结束标记；MLX 服务的防失控上限由 `QWEN_MLX_MAX_TOKENS` 控制，默认从上游的 512 提高到 8192。模型上下文长度和机器内存仍是不可移除的物理边界。

API Key 只由浏览器发送给 Spring Boot，再通过内部令牌转发给 FastAPI。FastAPI 将它写入 Git 忽略的 `data/model-settings.json`，文件权限为 `600`；读取设置时只返回 `api_key_configured`，不会把 Key 回传到浏览器。

公网部署应分别通过 `MODEL_REMOTE_ALLOWED_HOSTS` 和 `MODEL_LOCAL_ALLOWED_HOSTS` 固定可访问域名。不要为了临时调试把白名单改成任意地址。

### 连接 QQ 邮箱 MCP Server

登录后从左侧打开 `MCP Servers`，选择 QQ 邮箱并输入邮箱地址和在 QQ 邮箱设置中生成的授权码。服务端会先通过 `imap.qq.com:993` 测试连接，再保存配置：

- 授权码由 Spring Boot 使用 AES-GCM 加密后存入 PostgreSQL，只向前端返回 `credential_configured`，不会回显原文。
- 每个连接归属于当前登录用户；其他用户无法查看或使用。
- 当前注册 `qq_mail_list_folders`、`qq_mail_list_messages`、`qq_mail_search_messages`、`qq_mail_read_message` 四个只读工具。
- “最近 N 天”使用 IMAP `SINCE` 初筛，再按服务器 `INTERNALDATE` 精确过滤和排序；返回值会分别标明服务器收件时间 `received_at` 与邮件头声明时间 `header_date`。
- 邮件 UID 只在对应目录内有效，读取非收件箱邮件时必须沿用列表结果中的 `folder_id`。
- 文本搜索会批量读取目录中最近至多 200 封候选邮件；候选更多时返回 `scan_truncated=true`，Agent 必须说明结果并非整个目录的穷尽搜索。
- 邮件内容视为不可信数据，Agent 的系统提示明确禁止执行邮件正文里的指令。
- Agent 调用邮件工具时，完成请求所需的邮件内容会进入当前会话所选模型；若选择远程模型，相应内容会发送给该模型服务商。
- 发信、删除和移动等写操作尚未开放，需先补齐逐次工具确认流程。

生产环境建议为 `AIO_CONNECTOR_ENCRYPTION_KEY` 配置一个独立的至少 32 字节随机值；未设置时会从 `AIO_JWT_SECRET` 做用途隔离派生。首版只允许固定的 QQ IMAP 地址，避免用户通过连接器配置访问内网地址。

MiniMind 已由 `docker compose up -d --build` 自动启动，并配置了健康检查和异常自动重启。模型源码在镜像构建时固定到上游提交，权重通过 `MINIMIND_WEIGHTS_HOST_PATH`（默认 `./minimind/out`）只读挂载，不会复制进镜像或提交到 Git。宿主机仅在 `127.0.0.1:8998` 暴露接口，可执行：

```bash
./scripts/test_minimind_api.sh
```

如果需要脱离 Docker 直接调试 MiniMind，仍可执行 `./scripts/run_minimind_api.sh`；运行前应先停止 Compose 中的 `minimind` 服务，避免占用同一个端口。

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
INTERNAL_SERVICE_TOKEN="$(openssl rand -base64 48)" \
AIO_ALLOWED_WORKSPACE_ROOTS=/absolute/path/to/allowed/workspaces \
  .venv/bin/uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

前端代理已指向 Spring Boot `8081`，不再指向 FastAPI `8000`。

## 业务 API

公开 API 均由 Spring Boot 提供：

- `GET /api/v1/auth/config`、`POST /api/v1/auth/login`、`GET /api/v1/auth/me`
- `POST /api/v1/auth/refresh|logout|password|reset-password`
- `POST /api/v1/auth/register`（仅在部署者显式开启公开注册时可用）
- `GET|POST /api/v1/conversations`
- `GET /api/v1/conversations/{id}/messages`
- `POST /api/v1/conversations/{id}/runs`（要求 `Idempotency-Key`）
- `GET|DELETE /api/v1/runs/{id}`
- `GET /api/v1/runs/{id}/events`（SSE）
- `GET /api/v1/runs/{id}/event-history?after=...&size=...`（游标分页）
- `POST /api/v1/runs/{id}/changes/apply|reject`
- `GET /api/v1/projects`、`POST /api/v1/projects/open`
- `GET /api/v1/mcp/servers`、`PUT /api/v1/mcp/servers/qq-mail`
- `POST /api/v1/mcp/servers/{id}/test`、`PUT /api/v1/mcp/servers/{id}/enabled`、`DELETE /api/v1/mcp/servers/{id}`
- 项目成员与项目工作区文件 API
- `GET /actuator/health`、`/actuator/metrics`、`/actuator/prometheus`

FastAPI 只暴露带 `X-Internal-Token` 的 `/internal/v1/agent/*`、`/internal/v1/workspaces/*` 与 MCP 连接测试接口，不向前端提供会话 API。

## 运行保障

- 本地与生产 Compose 为所有长期服务配置了 healthcheck 和 `restart: unless-stopped`。
- Redis Stream 承担任务分发，Redis Pub/Sub/短期 Key 承担跨实例 SSE 通知、取消、限流和 JWT 注销；业务真相仍以 PostgreSQL 为准。
- `postgres-backup` 启动后立即备份，并按配置周期生成 PostgreSQL custom-format dump；恢复步骤见 `DEPLOYMENT.md`。
- Nginx、Spring Boot、FastAPI 和备份任务输出结构化日志。请求经 Nginx、Java、Python 传播同一个 `trace_id`，错误响应也会返回该值；Compose 同时限制本地 Docker 日志文件的大小和保留数量。
- Java 与 Python 的未预期异常只在服务日志保留诊断信息，前端仅显示脱敏错误和 `trace_id`。
- `.github/workflows/ci.yml` 会执行 Vitest、Playwright、Python、Java 集成测试和 Compose 配置检查；`codeql.yml` 与 Dependency Review 检查代码及新增依赖风险。
- Redis 的投递语义、恢复边界和运维检查见 `docs/REDIS_SCALING.md`。

## 异步任务流程

1. Java 校验 JWT、会话所有权和项目成员关系。
2. Java 保存用户消息和 `PENDING` 任务；数据库唯一约束保证同一会话只能有一个活动任务。
3. Java 把 run ID 写入 Redis Stream；消费者事务化地把任务改成 `RUNNING` 后调用 Python。
4. Python 对瞬时模型错误指数退避，并按 token 回传文本；取消会关闭正在使用的 HTTP 客户端。
5. Java 持久化每条事件，再通过 Redis 通知各实例的 SSE 连接；浏览器用 `Last-Event-ID` 重连。
6. 项目修改先作为 diff 提案返回，用户确认且原文件哈希未变化时才写入工作区。

## SQLite 迁移

`AIO_LEGACY_IMPORT_ENABLED=true` 时，Java 启动后会只读扫描 `data/app.sqlite3`，把会话和消息导入 PostgreSQL，并在 `legacy_imports` 记录导入结果。再次启动不会重复导入。Hibernate 使用 `ddl-auto=validate`，建表与变更只由 Flyway SQL 管理。

当前实机迁移验证结果：35 个会话、176 条消息。

## 验证

```bash
# Java：真实 PostgreSQL/Redis Testcontainers、并发、幂等、跨用户、SSE 重连
cd business-service
export JAVA_HOME=/path/to/jdk-21
./mvnw test

# Python：模型重试/取消、错误分类、工具参数、步数和目录边界
cd ..
.venv/bin/python -m pytest -q backend/tests

# React 单元测试、类型检查与生产构建
cd frontend
npm test
npm run build

# 浏览器完整流程（首次需 npx playwright install chromium）
npm run test:e2e
```

停止服务但保留 PostgreSQL 数据：

```bash
docker compose down
```

`docker compose down -v` 会删除 PostgreSQL 卷，只应在明确要清空数据时使用。
