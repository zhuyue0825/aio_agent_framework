# pgvector 实验检索与评测

数据库：独立 Compose 项目 `aio-rag-lab`，仅监听 `127.0.0.1:5433`。
现有业务 PostgreSQL 的 5432 端口、数据和配置不变。

## 文件位置

- 数据库目录：`D:\codex_project\codex_data\pgvector`
- 数据库密码：`D:\codex_project\codex_data\rag-postgres.env`，仓库外随机生成，不要提交或分享。
- 现有向量：`D:\codex_project\codex_data\duretrieval\embeddings_bge_m3\embeddings.sqlite3`
- 导入/评测报告：`D:\codex_project\codex_data\duretrieval\retrieval_reports`

数据库业务文件通过 bind mount 放在 D 盘；Docker 镜像层由 Docker Desktop 的镜像存储位置管理。

## 启动、停止

在仓库根目录执行：

```powershell
docker compose -f docker-compose.rag.yml --env-file D:/codex_project/codex_data/rag-postgres.env up -d --wait
docker compose -f docker-compose.rag.yml --env-file D:/codex_project/codex_data/rag-postgres.env stop
```

镜像固定为 `pgvector/pgvector:0.8.6-pg17`。首次在其他机器部署时，自行生成上述 env 文件，
包含 `RAG_DB_PASSWORD` 和 `RAG_PGDATA_PATH`；修改后者可以指定新的持久化目录。
模型向量维度为 1024；数据库驱动依赖见 `scripts/requirements-rag-search.txt`。

## 导入和搜索

```powershell
$ragPython = 'D:/codex_project/codex_data/.venv-rag/Scripts/python.exe'
& $ragPython -X utf8 scripts/rag_search.py import
& $ragPython -X utf8 scripts/rag_search.py search --query-id '从 queries.dev.jsonl 复制一个问题ID' --top-k 5
& $ragPython -X utf8 scripts/rag_search.py search --query '如何配置数据库连接？' --top-k 5
& $ragPython -X utf8 scripts/rag_search.py evaluate
```

`--query-id` 复用缓存，不调用外部 API。`--query` 使用 embedding.env 的 Key，
调用同一硅基流动 BGE-M3 接口生成查询向量；结果只包含语料库里的内容，不生成最终答案。
DuRetrieval 是通用中文数据，未包含本项目知识，任意项目问题不保证有相关答案。

导入先校验 SQLite 完整性、文本映射和全部向量，再在一个数据库事务中建表并 COPY：

- `rag_lab.chunks`：10,578 条候选文本块，保留原始文档 ID、字符区间、文本哈希和向量。
- `rag_lab.queries`：200 个查询及向量，单独存储，不参与候选检索。
- `rag_lab.metadata`：模型、分块参数、源文件哈希及有序向量哈希。

提交前逐条比较 ID、原文、元数据、向量值与源数据。重复导入同一数据只做验证，
不同实验数据拒绝覆盖。脚本仅连接固定的本机实验库。

## 检索与指标

基线不建 HNSW/IVFFlat 索引，精确计算全部块的余弦距离，每篇文档取最高相似度。
先按原始文档去重，再返回前 K 篇；分数相同按文档 ID 稳定排序。

`evaluate` 固定只跑 100 题本地 dev，验收集只导入向量、不评分。
先执行一次预热，然后每题测量一次数据库检索往返，排除查询向量化、连接建立和缓存向量读取时间。

- Recall@K：前 K 篇命中的正向标注文档数量 / 该题全部正向标注文档数量，然后对问题取均值。
- nDCG@10：增益 `2^relevance-1`，折扣 `log2(rank+1)`，以理想排名归一化，然后取均值。
- Hit@10：至少命中一篇正向标注文档的问题比例。
- P95：100 条延迟排序后的第 95 条（nearest-rank）。

输出 `import_report.json`、`dev_report.json` 和中文 `dev_report.md`。
JSON 包含每题的排名、原文片段、未命中文档 ID 和指标，方便定位坏例。

这是候选库被缩小的 DuRetrieval 子集实验，不能等同官方全量 benchmark，也不能据此判断生成答案质量。
未标注文档按不相关计分，但不意味着现实中一定不相关。

## 验证脚本

```powershell
$env:RAG_SEARCH_INTEGRATION = '1'
& $ragPython -m unittest discover -s scripts -p test_rag_search.py -v
```

集成测试在事务内插入临时样例验证文档去重和排名，结束后回滚，不保留测试数据。
