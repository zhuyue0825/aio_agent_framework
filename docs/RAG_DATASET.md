# DuRetrieval 实验子集

此步骤只准备和校验检索数据，不调用 Embedding 或回答模型，也不连接业务数据库。
数据放在仓库外的 `D:\codex_project\codex_data`，不会混入代码或业务数据目录。

## 本机目录

```text
D:\codex_project\codex_data\
  .venv-rag\                       独立 Python 环境
  .pip-cache\                      依赖下载缓存
  duretrieval\
    raw\                          固定版本的三个原始 Parquet 文件
    subset_q200_c10000_s42\
      corpus.jsonl                10,000 条候选文本，id / text
      queries.jsonl               200 个问题，id / text
      qrels.jsonl                 所选问题的全部相关性标注，qid / pid / score
      queries.dev.jsonl           100 个调试问题
      queries.test.jsonl          100 个最终验收问题
      qrels.dev.jsonl             调试问题的标注
      qrels.test.jsonl            验收问题的标注
      manifest.json              数据源版本、抽样参数、文件哈希和行数
      validation_report.json     生成时的完整校验报告
```

完整 ID 清单保存在 JSONL 文件本身。文本原样保留，不清洗、不截断、不重新切块。
部分原文较长，向量化阶段必须明确截断或分块策略；分块时保留父文本 ID，评测前按父文本聚合去重。

## 命令（PowerShell，项目根目录执行）

已有环境可以直接运行下面命令。新机器先用 Python 3.12 创建虚拟环境，并安装
`scripts/requirements-rag-data.txt`；pip 缓存也可以通过 `--cache-dir` 放入上述数据目录。

准备子集（若输出目录已存在会拒绝覆盖）：

```powershell
& D:/codex_project/codex_data/.venv-rag/Scripts/python.exe scripts/rag_dataset.py prepare --data-root D:/codex_project/codex_data/duretrieval --queries 200 --corpus 10000 --seed 42
```

重新校验，并对照原始 Parquet 重建抽样，检查是否遗漏相关文本：

```powershell
& D:/codex_project/codex_data/.venv-rag/Scripts/python.exe scripts/rag_dataset.py validate --subset D:/codex_project/codex_data/duretrieval/subset_q200_c10000_s42 --raw-dir D:/codex_project/codex_data/duretrieval/raw
```

省略 `--raw-dir` 可以做纯标准库的离线校验，但不会重新核实源数据和抽样。
校验成功输出 JSON 并返回退出码 0，失败向 stderr 输出错误并返回非零退出码。
`validate` 不覆盖原先生成时的报告，最新结果在命令输出中。

运行小型离线测试：

```powershell
& D:/codex_project/codex_data/.venv-rag/Scripts/python.exe -m unittest discover -s scripts -p test_rag_dataset.py -v
```

## 抽样和校验规则

1. 固定两个上游仓库的 commit，下载后核对官方文件 SHA-256 和字节数。缓存命中时同样校验。
2. 从有正向标注的问题中，按排序后的 ID 和 seed=42 抽取 200 个。
3. 保留这 200 个问题的全部标注及对应文本，剩余候选从其他文本随机补齐至 10,000 条。
4. 使用独立 seed 打乱问题，分为 100 个 dev 和 100 个 test，共用同一候选库。
5. 校验字段类型、空文本、重复 ID、重复标注、非法分数、悬空引用、每题有正样本、问题划分互斥且完整。
6. 校验各分组问题和标注与全集一致；检查 dev/test 是否存在完全相同的问题文本。
7. 校验生成文件哈希，并在源数据校验模式下完整重建抽样，逐条比对文本、ID、标注和顺序。

语料中相同文本但不同 ID 的记录只报告数量，保留上游标注关系。文件哈希用于发现意外修改，
不是防篡改签名。复现时建议保持同一 Python 版本；实际版本记录在 manifest 中。

## 如何使用

- `corpus.jsonl`：用于构建向量索引和关键词索引。
- `queries.dev.jsonl`：用于调整召回数量、融合方式等参数。
- `queries.test.jsonl`：方案确定后验收，不反复据此调参。
- `qrels*.jsonl`：仅供评测脚本计算 Recall / nDCG，不能给检索器或回答模型作为提示。

这是从上游 dev 标注构建的本地实验拆分，不是官方 test 集。随机补充的候选属于未标注文本，
不能保证都不相关；qrels 也不是完整标准答案。缩小候选库会改变检索难度，结果必须标为
“DuRetrieval 子集实验”，不能当成全量 C-MTEB 成绩。该集主要测检索，不能替代项目知识问答验收。

来源：
- https://huggingface.co/datasets/C-MTEB/DuRetrieval
- https://huggingface.co/datasets/C-MTEB/DuRetrieval-qrels

## 下一步

读取 corpus 生成 Embedding，保留原始文本 ID；检索返回 ID 列表后，对照 qrels 计算 Recall@5、
Recall@10、nDCG@10，再将验证过的检索功能接入 Agent 的 knowledge_search 工具。
