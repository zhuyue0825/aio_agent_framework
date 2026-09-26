# 聊天附件与知识库（第一期）

## 使用

刷新 `http://127.0.0.1:5173`，进入一个对话。建议选择已配置的 DeepSeek 模型进行工具调用演示。

1. 点击输入框上方「知识库：未选择」，勾选「中文通用检索演示库」。例如提问「请先查询知识库：覆铜板是什么？引用来源回答」。
2. 点击「＋ → 上传本地文件」，选择 UTF-8 文本、Markdown、代码或文字型 PDF。等附件显示「已就绪」后发送问题。
3. 在项目对话中，点击「＋ → 引用工作区文件」，筛选并选择文件。系统保存当时的文本快照；回答中的来源可以查看原路径和行号。
4. 解析中或解析失败时禁止发送；失败附件可以「重试」或从待发送列表「移除」。移除不会删除电脑上的原文件。
5. 点击回答中的 `[E1]` 等编号或「已查阅来源」按钮，打开原文侧栏；匹配片段会高亮。PDF 展示页码，文本/代码展示行号，演示库展示字符区间。
6. 「知识库检索记录」可展开查看查询、成功/失败、返回数量与耗时。该耗时包含远程问题向量化和检索，不包含之后的回答生成。

知识库选择按对话保存。附件随本条消息保存，发送后待发送列表清空；后续消息需要再次选取文件才能调用附件工具。已发送消息的附件与来源仍可打开查看。

## 当前范围

- 单文件 5 MiB，每条消息最多 5 个附件，每个对话最多保存 30 个上传/引用记录。
- PDF 最多 200 页；总提取文本最多 15 万字符。不支持扫描件 OCR、加密 PDF、Word/Excel、压缩包及非 UTF-8 文本。
- 附件按 2,000 字符切段，提供 `attachment_read` 精确读取和 `attachment_search` 关键词检索；不会自动加入长期知识库，也不会为附件调用 Embedding API。
- DuRetrieval 为 10,000 篇历史中文资料的演示子集，不包含当前项目资料。每次 `knowledge_search` 调用硅基流动 `BAAI/bge-m3` 为新查询生成 1024 维向量，再在已有 pgvector 向量中检索，每篇文档取最佳片段，返回 Top 5。每次任务最多调用 4 次。
- 勾选知识库表示允许按需使用；普通问候无需检索。明确要求「根据知识库」时，提示词要求先检索。真实使用情况以检索记录和来源为准。
- 来源定位只能证明工具读取过相应原文，不能自动保证模型的每一句解释都正确。
- 本地上传指浏览器选择本机文件后上传到业务服务，不是授予 Agent 任意访问本机磁盘的权限。所选文件的相关文本会进入当前对话模型的上下文。

## 启动配置

数据目录默认使用项目旁的 `../codex_data`，即此机的 `D:\codex_project\codex_data`。可用 `CODEX_DATA_PATH` 覆盖。

```powershell
# 已有独立实验库（保留已有导入数据）
docker compose --env-file D:/codex_project/codex_data/rag-postgres.env -p aio-rag-lab -f docker-compose.rag.yml up -d

# 在原应用 Compose 上叠加附件目录、Embedding 凭据、实验库连接
docker compose -f docker-compose.yml -f docker-compose.materials.yml up -d --build agent-service business-service

# 前端仍沿用现有 Vite 开发服务
cd frontend
npm run dev
```

`embedding.env` 仅挂载给 Agent 服务；`rag-postgres.env` 仅挂载给业务服务。密钥不发送到浏览器、不写入消息。业务服务连接 `host.docker.internal:5433/rag_lab`，仅执行检索查询。该配置用于当前单机实验部署。

附件原件保存在 `codex_data/attachments/<UUID>.bin`；解析文本、处理状态、会话选择保存在业务 PostgreSQL。V10 Flyway 迁移自动创建两张材料表，原消息及 Agent 任务表不变。草稿移除仅解除本次选择，原件清理和容量管理属于后续功能。

## 请求链路与权限

浏览器 → Java 上传/工作区引用接口 → Python 文本解析 → Java 保存 READY/FAILED → 创建任务时校验附件范围与状态 → Agent 工具读取 → 保存回答、来源及检索摘要。

- Java 校验登录用户、对话归属、工作区成员资格、附件对话归属和 READY 状态。
- Agent 只获得本条消息选中的附件快照；未选知识库时不注册 `knowledge_search`。
- 内部检索接口验证内部凭据，并再次检查任务处于 RUNNING、请求用户匹配、该任务原消息选中了演示库。
- 文档内容作为不可信数据处理；未知 `[E编号]` 在最终回答中替换为「来源未验证」。只有工具实际返回的证据生成来源链接。
- 工作区文件通过现有受限文件读取接口读取，引用不会修改文件。

## 验证记录（2026-09-25）

- 前端：13 项测试通过；生产构建通过。
- Python：Linux 容器内 56 项测试通过。
- Java：29 项测试通过，包括真实 PostgreSQL 上的迁移、附件跨用户/跨对话隔离、失败重试与知识库选择持久化。
- 真实模型验收：上传独有事实的文本后回答 ORBIT-472 / 17 天并引用行号；演示库查询实际完成 Embedding → pgvector，原文端点与返回片段一致；引用 `backend/materials.py` 后回答 5 MiB / 200 页并引用代码路径和行号，未修改代码。
- 本机验收 JSON 与日志位于 `D:\codex_project\codex_data\materials-*-acceptance.json`，不包含凭据。

```powershell
cd frontend
npm test
npm run build
# Python 完整测试宜在 Linux 环境运行；已有部分工作区安全测试依赖 Linux 文件权限。
# Java 完整测试需要 JDK 21 和 Docker（Testcontainers）。
```
