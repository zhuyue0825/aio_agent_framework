# 远程 Embedding 实验

选用硅基流动 `BAAI/bge-m3`，接口为 `https://api.siliconflow.cn/v1/embeddings`，
输出 1024 维向量。账户是否可用及实际计费以控制台为准，脚本不会自动改用其他付费模型。
官方接口文档：https://siliconflow.readme.io/reference/createembedding

## 凭据

在 `D:\codex_project\codex_data\embedding.env` 中填写 `SILICONFLOW_API_KEY=...`。
也可通过同名进程环境变量提供。该文件在仓库外，不要把 Key 发到聊天或提交 Git。
脚本只读取这个专用 Key，不复用项目的聊天模型 Key，也不会跟随 HTTP 重定向发送凭据。

## 运行顺序

在项目根目录用 PowerShell 执行：

```powershell
$ragPython = 'D:/codex_project/codex_data/.venv-rag/Scripts/python.exe'
& $ragPython scripts/rag_embeddings.py plan
& $ragPython scripts/rag_embeddings.py smoke
& $ragPython scripts/rag_embeddings.py run --max-items 100
& $ragPython scripts/rag_embeddings.py run --max-items 0
& $ragPython scripts/rag_embeddings.py status
& $ragPython scripts/rag_embeddings.py verify
```

- plan：只做本地数据校验和分块，不调用 API。
- smoke：发送 5 条文本，包含中文改写、无关句子、重复句子和一个最长文本块，
  检查响应索引、维度、数值、非零向量及重复输入一致性。语义相似度只报告，不代表检索评测。
- run：必须先通过真实 smoke；默认试跑 100 个待处理项，`--max-items 0` 处理所有剩余项。
- status：报告已完成/待完成项和服务商返回的 token 用量。
- verify：批量完成后，逐条对照输入，检查无缺失记录、文本哈希、向量维度、有限数值、归一化和数据库完整性。

原文会发送给硅基流动。每次默认 8 条，批次间隔 1 秒，可用 `--batch-size`、`--interval` 调整。
429 和部分服务端错误指数退避重试；鉴权、余额、模型权限或输入错误会停止，不无限重试。

## 分块与保存

此基线按 1000 **字符**分块、重叠 100 字符，保留父文本 ID 和字符范围，不丢弃尾部。
该方案不是 tokenizer 精确分块，也不是最优分块策略；若服务端仍拒绝输入则停止并调整配置，
不能静默截断。问题保持原样。检索评测时必须按父文本 ID 聚合、去重后再取前 K 条。

输出目录：`D:\codex_project\codex_data\duretrieval\embeddings_bge_m3`。

- `embeddings.sqlite3`：本地断点缓存，items 表含文本、父 ID、字符范围、哈希及向量。
- 向量存为 L2 归一化的 1024 维小端 float32 BLOB，读取用 `struct.unpack('<1024f', blob)`。
- `plan_report.json` / `smoke_report.json` / `run_report.json` / `status_report.json`：各阶段报告。

每批结果与用量在同一个事务提交。重跑只处理尚无向量的记录；输入哈希、服务商、模型、
维度或分块配置变化时拒绝复用缓存。不要并行运行两个生成进程，以免重复发起 API 请求。
网络超时或进程在响应后、提交前退出可能导致该批次重算；服务商可能仍计费，本地成功用量并非完整账单。
服务商若在同一模型名下更新权重，本地配置哈希无法检测，重要评测应重新生成完整索引。

SQLite 仅用于断点保存，下一阶段将这些向量导入 PostgreSQL + pgvector，不是最终检索数据库。
本阶段不读取 qrels 作为模型输入，也不会训练模型。

## 离线验证

```powershell
& $ragPython -m unittest discover -s scripts -p test_rag_embeddings.py -v
```

离线测试只能验证代码行为。没有真实 API Key 时，不能声称真实接口或批量生成成功。
