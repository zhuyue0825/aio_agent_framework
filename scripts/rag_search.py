"""Import cached embeddings into isolated pgvector, search, and evaluate dev only."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import statistics
import struct
import sys
import time

import psycopg
from psycopg.types.json import Jsonb

from rag_dataset import read_jsonl, require, sha256, validate
from rag_embeddings import ROOT, Client, config_for, read_key, verify_checkpoint

SUBSET = ROOT / "duretrieval/subset_q200_c10000_s42"
CHECKPOINT = ROOT / "duretrieval/embeddings_bge_m3/embeddings.sqlite3"
REPORTS = ROOT / "duretrieval/retrieval_reports"
TABLES = {"corpus": "rag_lab.chunks", "query": "rag_lab.queries"}


def connect(env_file):
    values = {}
    for line in env_file.read_text(encoding="utf-8-sig").splitlines():
        key, sep, value = line.partition("=")
        if sep and not key.lstrip().startswith("#"):
            values[key.strip()] = value.strip()
    require(bool(values.get("RAG_DB_PASSWORD")), "Missing RAG_DB_PASSWORD")
    return psycopg.connect(host="127.0.0.1", port=5433, dbname="rag_lab", user="rag_lab",
                           password=values["RAG_DB_PASSWORD"], connect_timeout=10, autocommit=True)


def vector_text(vector):
    require(len(vector) == 1024 and all(math.isfinite(x) for x in vector), "Invalid vector")
    return "[" + ",".join(format(x, ".9g") for x in vector) + "]"


def metadata(db):
    row = db.execute("SELECT value FROM rag_lab.metadata WHERE id=1").fetchone()
    require(row is not None, "Import embeddings first")
    return row[0]


def verify_import(db, source):
    counts, max_error = {}, 0.0
    for kind, table in TABLES.items():
        expected = {row[0]: row[1:] for row in source.execute(
            "SELECT id,parent_id,start_char,end_char,text,content_sha256,vector FROM items WHERE kind=?", (kind,))}
        counts[kind] = len(expected)
        for row in db.execute(f"SELECT id,parent_id,start_char,end_char,text,content_sha256,embedding::text FROM {table}"):
            original = expected.pop(row[0], None)
            require(original is not None and tuple(row[1:6]) == tuple(original[:5]), "Imported ID/text metadata mismatch")
            vector = json.loads(row[6])
            require(len(vector) == 1024, "Imported vector dimension mismatch")
            error = max(abs(a - b) for a, b in zip(vector, struct.unpack("<1024f", original[5])))
            require(error < 1e-7, "Imported vector values differ from source")
            max_error = max(max_error, error)
        require(not expected, "Missing imported records")
    return {"status": "passed", "counts": counts, "max_vector_roundtrip_error": max_error}


def import_vectors(db, checkpoint, subset):
    require(checkpoint.is_file(), "Embedding checkpoint missing")
    with sqlite3.connect(checkpoint.resolve().as_uri() + "?mode=ro", uri=True) as source:
        verification = verify_checkpoint(source, subset)
        config = json.loads(source.execute("SELECT value FROM metadata WHERE key='config'").fetchone()[0])
        require(config == config_for(subset), "Checkpoint configuration does not match current embedding pipeline")
        manifest = {"config": config, "ordered_vectors_sha256": verification["ordered_vectors_sha256"]}
        with db.transaction():
            db.execute("CREATE EXTENSION IF NOT EXISTS vector")
            db.execute("CREATE SCHEMA IF NOT EXISTS rag_lab")
            db.execute("CREATE TABLE IF NOT EXISTS rag_lab.metadata (id integer PRIMARY KEY CHECK(id=1), value jsonb NOT NULL)")
            for table in TABLES.values():
                db.execute(f"""CREATE TABLE IF NOT EXISTS {table} (
                    id text PRIMARY KEY, parent_id text NOT NULL, start_char integer NOT NULL,
                    end_char integer NOT NULL, text text NOT NULL, content_sha256 text NOT NULL,
                    embedding vector(1024) NOT NULL)""")
            existing = db.execute("SELECT value FROM rag_lab.metadata WHERE id=1").fetchone()
            if existing:
                require(existing[0] == manifest, "Database contains a different experiment; refusing to overwrite")
            else:
                for kind, table in TABLES.items():
                    require(db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0,
                            "Database contains untracked rows; refusing to overwrite")
                    with db.cursor().copy(f"COPY {table} (id,parent_id,start_char,end_char,text,content_sha256,embedding) FROM STDIN") as copy:
                        for row in source.execute(
                                "SELECT id,parent_id,start_char,end_char,text,content_sha256,vector FROM items WHERE kind=? ORDER BY id", (kind,)):
                            copy.write_row((*row[:6], vector_text(struct.unpack("<1024f", row[6]))))
                db.execute("INSERT INTO rag_lab.metadata VALUES (1,%s)", (Jsonb(manifest),))
            report = verify_import(db, source)
        for table in TABLES.values():
            db.execute(f"ANALYZE {table}")
        report.update({"already_imported": bool(existing), **manifest,
                       "postgres_version": db.execute("SHOW server_version").fetchone()[0],
                       "pgvector_version": db.execute("SELECT extversion FROM pg_extension WHERE extname='vector'").fetchone()[0]})
        return report


def search(db, vector, top_k=10):
    require(1 <= top_k <= 100, "top-k must be 1..100")
    # No chunk-level LIMIT: all parents compete before the final top-k.
    sql = """WITH scored AS MATERIALIZED (
        SELECT id,parent_id,embedding <=> %s::vector AS distance FROM rag_lab.chunks
    ), best AS (
        SELECT DISTINCT ON (parent_id) id,parent_id,distance
        FROM scored ORDER BY parent_id,distance,id
    ), top_docs AS (
        SELECT * FROM best ORDER BY distance,parent_id LIMIT %s
    ) SELECT b.parent_id,b.id,1-b.distance,c.text,c.start_char,c.end_char
      FROM top_docs b JOIN rag_lab.chunks c ON c.id=b.id
      ORDER BY b.distance,b.parent_id"""
    started = time.perf_counter()
    rows = db.execute(sql, (vector, top_k)).fetchall()
    elapsed = (time.perf_counter() - started) * 1000
    return [{"document_id": row[0], "chunk_id": row[1], "score": row[2],
             "text": row[3], "start_char": row[4], "end_char": row[5]} for row in rows], elapsed


def cached_query(db, qid):
    row = db.execute("SELECT text,embedding::text FROM rag_lab.queries WHERE id=%s", (qid,)).fetchone()
    require(row is not None, "Unknown cached query ID")
    return row


def metrics(ranking, judgments):
    require(len(ranking) == len(set(ranking)), "Ranking must contain unique document IDs")
    positive = {key: value for key, value in judgments.items() if value > 0}
    require(bool(positive), "Query has no positive judgments")
    result = {}
    for k in (5, 10):
        result[f"recall_at_{k}"] = len(set(ranking[:k]) & positive.keys()) / len(positive)
    dcg = sum((2 ** positive.get(doc, 0) - 1) / math.log2(rank + 2) for rank, doc in enumerate(ranking[:10]))
    ideal = sum((2 ** grade - 1) / math.log2(rank + 2)
                for rank, grade in enumerate(sorted(positive.values(), reverse=True)[:10]))
    result["ndcg_at_10"] = dcg / ideal
    result["hit_at_10"] = float(bool(set(ranking[:10]) & positive.keys()))
    return result


def evaluate(db, subset, output):
    validate(subset)
    source_meta = metadata(db)
    require(source_meta["config"] == config_for(subset), "Database/input configuration mismatch")
    queries = read_jsonl(subset / "queries.dev.jsonl")
    require(len(queries) == 100, "This report expects exactly 100 development queries")
    judgments = {row["id"]: {} for row in queries}
    for row in read_jsonl(subset / "qrels.dev.jsonl"):
        judgments[row["qid"]][row["pid"]] = row["score"]
    # One explicit warm-up; timings below measure DB retrieval + local transport,
    # excluding API calls, connection setup and cached-query-vector loading.
    search(db, cached_query(db, queries[0]["id"])[1])
    cases = []
    for number, query in enumerate(queries, 1):
        text, vector = cached_query(db, query["id"])
        require(text == query["text"], "Cached query text mismatch")
        results, elapsed = search(db, vector)
        ranking = [item["document_id"] for item in results]
        scores = metrics(ranking, judgments[query["id"]])
        cases.append({"query_id": query["id"], "question": text, **scores,
                      "latency_ms": elapsed,
                      "relevant_document_ids": sorted(judgments[query["id"]]),
                      "missing_relevant_ids_at_10": sorted(set(judgments[query["id"]]) - set(ranking)),
                      "results": results})
        if number % 20 == 0:
            print(f"Evaluated {number}/{len(queries)} dev queries", flush=True)
    latencies = sorted(case["latency_ms"] for case in cases)
    report = {"created_at_utc": datetime.now(timezone.utc).isoformat(), "split": "local-dev",
              "query_count": len(cases), "corpus_document_count": db.execute("SELECT count(DISTINCT parent_id) FROM rag_lab.chunks").fetchone()[0],
              "chunk_count": db.execute("SELECT count(*) FROM rag_lab.chunks").fetchone()[0],
              "method": "exact cosine, all chunks, max similarity per parent, unique top-10 documents",
              "metrics": {name: statistics.mean(case[name] for case in cases)
                          for name in ("recall_at_5", "recall_at_10", "ndcg_at_10", "hit_at_10")},
              "latency_ms": {"mean": statistics.mean(latencies), "p50": statistics.median(latencies),
                             "p95_nearest_rank": latencies[math.ceil(len(latencies) * .95) - 1]},
              "zero_hit_queries_at_10": sum(case["hit_at_10"] == 0 for case in cases),
              "queries_missing_any_relevant_at_10": sum(bool(case["missing_relevant_ids_at_10"]) for case in cases),
              "online_embedding_requests": 0, "warmup_queries": 1,
              "dev_queries_sha256": sha256(subset / "queries.dev.jsonl"),
              "dev_qrels_sha256": sha256(subset / "qrels.dev.jsonl"),
              "source": source_meta,
              "postgres_version": db.execute("SHOW server_version").fetchone()[0],
              "pgvector_version": db.execute("SELECT extversion FROM pg_extension WHERE extname='vector'").fetchone()[0],
              "limitations": ["Sampled corpus, not a full C-MTEB benchmark score.",
                              "Unjudged documents count as non-relevant for scoring; judgments may be incomplete.",
                              "Measures retrieval, not generated answer quality.",
                              "100 test queries were imported but not evaluated.",
                              "Latency is one warm-cache local run; excludes query embedding and connection setup."],
              "cases": cases}
    output.mkdir(parents=True, exist_ok=True)
    write_report(output / "dev_report.json", report)
    lines = ["# DuRetrieval 调试集检索基线", "", f"时间：{report['created_at_utc']}", "",
             "100 题本地调试集；10,000 篇候选文档，10,578 个文本块。", "",
             "采用精确余弦检索，扫描全部分块，按原始文档取最高相似度后返回前 10 篇。", "",
             "| 指标 | 结果 |", "|---|---:|"]
    for name, value in report["metrics"].items():
        lines.append(f"| {name} | {value:.4f} ({value:.2%}) |")
    lines += [f"| 检索 P50 | {report['latency_ms']['p50']:.2f} ms |",
              f"| 检索 P95 | {report['latency_ms']['p95_nearest_rank']:.2f} ms |", "",
              f"前 10 条完全未命中标注的题数：{report['zero_hit_queries_at_10']}。",
              f"未找回全部相关文档的题数：{report['queries_missing_any_relevant_at_10']}。", "",
              "## 较弱的 10 个案例", ""]
    for case in sorted(cases, key=lambda value: (value["recall_at_10"], value["ndcg_at_10"]))[:10]:
        lines += [f"- {case['question']}（ID：{case['query_id']}）",
                  f"  Recall@10={case['recall_at_10']:.3f}，nDCG@10={case['ndcg_at_10']:.3f}；未命中 ID：{', '.join(case['missing_relevant_ids_at_10']) or '无'}"]
    lines += ["", "## 复现与边界", "", "完整问题、原文片段、排名和缺失文档 ID 见同目录 dev_report.json。",
              "复用全部已保存向量，评测未调用远程 Embedding API；100 题验收集未评测。",
              "延迟为预热一次后的本机数据库往返耗时，不含查询向量化、建立连接或最终答案生成。",
              "这是缩小候选库后的子集实验，不能当作全量 C-MTEB 成绩；未标注文档按不相关计分，标注可能不完整。",
              "下一步优先检查弱例中的同主题干扰文档、分块边界与证据，再在相同调试集上比较关键词/混合检索。", ""]
    (output / "dev_report.md").write_text("\n".join(lines), encoding="utf-8")
    return {key: value for key, value in report.items() if key not in {"cases", "source"}}


def write_report(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["import", "search", "evaluate"])
    parser.add_argument("--subset", type=Path, default=SUBSET)
    parser.add_argument("--checkpoint", type=Path, default=CHECKPOINT)
    parser.add_argument("--db-env", type=Path, default=ROOT / "rag-postgres.env")
    parser.add_argument("--embedding-env", type=Path, default=ROOT / "embedding.env")
    parser.add_argument("--output", type=Path, default=REPORTS)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--query-id", help="Reuse cached question vector; no API call")
    group.add_argument("--query", help="New text: calls remote embedding API")
    parser.add_argument("--top-k", type=int, default=10)
    args = parser.parse_args()
    try:
        with connect(args.db_env) as db:
            if args.command == "import":
                report = import_vectors(db, args.checkpoint, args.subset)
                write_report(args.output / "import_report.json", report)
            elif args.command == "evaluate":
                report = evaluate(db, args.subset, args.output)
            else:
                require(args.query_id or (args.query and args.query.strip()), "Provide --query-id or --query")
                require(metadata(db)["config"] == config_for(args.subset), "Model/source configuration mismatch")
                embedding_seconds = 0
                if args.query_id:
                    question, vector = cached_query(db, args.query_id)
                else:
                    question = args.query
                    require(len(question) <= 1000, "Query exceeds baseline length limit")
                    vectors, _, embedding_seconds = Client(read_key(args.embedding_env)).embed([question])
                    vector = vector_text(vectors[0])
                results, elapsed = search(db, vector, args.top_k)
                report = {"question": question, "embedding_seconds": embedding_seconds,
                          "search_ms": elapsed, "results": results}
            print(json.dumps(report, ensure_ascii=False, indent=2))
    except psycopg.Error as exc:
        print(f"Database operation failed ({type(exc).__name__}, SQLSTATE={exc.sqlstate}); check experiment database and schema.", file=sys.stderr)
        return 1
    except (ValueError, OSError, KeyError, TypeError, sqlite3.Error) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
