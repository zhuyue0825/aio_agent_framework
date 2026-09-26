"""SiliconFlow BGE-M3 embeddings: offline plan, live smoke test, resumable run.

Only stdlib is needed. SQLite is a local checkpoint/export artifact, not a
replacement for the planned PostgreSQL vector store. See docs/RAG_EMBEDDINGS.md.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import struct
import sys
import time
import urllib.error
import urllib.request

from rag_dataset import read_jsonl, require, sha256, validate

ROOT = Path(__file__).resolve().parents[2] / "codex_data"
ENDPOINT = "https://api.siliconflow.cn/v1/embeddings"
MODEL = "BAAI/bge-m3"
DIMENSIONS = 1024
CHUNK_SIZE = 1000
OVERLAP = 100


def chunks(text):
    """Preserve all characters with bounded overlapping windows (not tokens)."""
    start = 0
    while start < len(text):
        end = min(start + CHUNK_SIZE, len(text))
        yield start, end, text[start:end]
        if end == len(text):
            break
        start = end - OVERLAP


def config_for(subset):
    return {"schema_version": 1, "endpoint": ENDPOINT, "model": MODEL,
            "dimensions": DIMENSIONS, "chunk_characters": CHUNK_SIZE,
            "overlap_characters": OVERLAP, "normalization": "l2",
            "vector_encoding": "float32-little-endian",
            "corpus_sha256": sha256(subset / "corpus.jsonl"),
            "queries_sha256": sha256(subset / "queries.jsonl")}


def fingerprint(config):
    return hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()


def open_checkpoint(subset, output):
    config = config_for(subset)
    path = output / "embeddings.sqlite3"
    if not path.exists():
        validate(subset)
    output.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=30)
    connection.execute("PRAGMA journal_mode=WAL")
    try:
        with connection:
            connection.execute("CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            connection.execute("""CREATE TABLE IF NOT EXISTS items (
                kind TEXT NOT NULL, id TEXT NOT NULL, parent_id TEXT NOT NULL,
                start_char INTEGER NOT NULL, end_char INTEGER NOT NULL, text TEXT NOT NULL,
                content_sha256 TEXT NOT NULL, vector BLOB, PRIMARY KEY(kind,id))""")
            stored = connection.execute("SELECT value FROM metadata WHERE key='config'").fetchone()
            if stored:
                require(json.loads(stored[0]) == config,
                        "Checkpoint configuration/input changed; use a new output directory")
            else:
                require(connection.execute("SELECT count(*) FROM items").fetchone()[0] == 0,
                        "Checkpoint has items but no configuration")
                connection.execute("INSERT INTO metadata VALUES ('config', ?)", (json.dumps(config),))
                for row in read_jsonl(subset / "corpus.jsonl"):
                    for number, (start, end, text) in enumerate(chunks(row["text"])):
                        if not text.strip():
                            continue
                        connection.execute("INSERT INTO items VALUES (?,?,?,?,?,?,?,NULL)",
                                           ("corpus", f'{row["id"]}:{number}', row["id"], start, end,
                                            text, hashlib.sha256(text.encode()).hexdigest()))
                for row in read_jsonl(subset / "queries.jsonl"):
                    require(len(row["text"]) <= CHUNK_SIZE,
                            "Query too long for this baseline; do not silently truncate")
                    connection.execute("INSERT INTO items VALUES (?,?,?,?,?,?,?,NULL)",
                                       ("query", row["id"], row["id"], 0, len(row["text"]),
                                        row["text"], hashlib.sha256(row["text"].encode()).hexdigest()))
        return connection, config
    except Exception:
        connection.close()
        raise


def status(connection):
    counts = {}
    for kind, total, done in connection.execute(
            "SELECT kind,count(*),sum(vector IS NOT NULL) FROM items GROUP BY kind"):
        counts[kind] = {"total": total, "completed": done, "pending": total - done}
    usage = connection.execute("SELECT value FROM metadata WHERE key='usage'").fetchone()
    smoke = connection.execute("SELECT value FROM metadata WHERE key='smoke'").fetchone()
    return {"items": counts, "smoke_passed": bool(smoke),
            "usage": json.loads(usage[0]) if usage else {"successful_requests": 0, "reported_tokens": 0}}


def verify_checkpoint(connection, subset):
    require(connection.execute("PRAGMA quick_check").fetchone()[0] == "ok", "SQLite integrity check failed")
    expected = {}
    for row in read_jsonl(subset / "corpus.jsonl"):
        for number, (start, end, text) in enumerate(chunks(row["text"])):
            if text.strip():
                expected["corpus", f'{row["id"]}:{number}'] = (row["id"], start, end, text)
    for row in read_jsonl(subset / "queries.jsonl"):
        expected["query", row["id"]] = (row["id"], 0, len(row["text"]), row["text"])
    checked = 0
    min_norm, max_norm = float("inf"), 0.0
    digest = hashlib.sha256()
    for kind, item_id, parent, start, end, text, content_hash, blob in connection.execute(
            "SELECT kind,id,parent_id,start_char,end_char,text,content_sha256,vector FROM items ORDER BY kind,id"):
        require(expected.pop((kind, item_id), None) == (parent, start, end, text),
                f"Unexpected or changed checkpoint text: {kind}/{item_id}")
        require(hashlib.sha256(text.encode()).hexdigest() == content_hash, "Checkpoint content hash mismatch")
        require(blob is not None and len(blob) == DIMENSIONS * 4, f"Missing/invalid vector: {kind}/{item_id}")
        vector = struct.unpack(f"<{DIMENSIONS}f", blob)
        require(all(math.isfinite(value) for value in vector), "Stored vector contains non-finite values")
        norm = math.hypot(*vector)
        require(abs(norm - 1.0) < 1e-5, "Stored vector is not normalized")
        min_norm, max_norm = min(min_norm, norm), max(max_norm, norm)
        digest.update(f"{kind}/{item_id}\n".encode())
        digest.update(blob)
        checked += 1
    require(not expected, "Checkpoint is missing expected input records")
    return {"status": "passed", "checked_vectors": checked, "dimensions": DIMENSIONS,
            "min_l2_norm": min_norm, "max_l2_norm": max_norm,
            "ordered_vectors_sha256": digest.hexdigest(), **status(connection)}


def read_key(path):
    key = os.environ.get("SILICONFLOW_API_KEY", "").strip()
    if not key and path.exists():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            name, separator, value = line.partition("=")
            if separator and name.strip() == "SILICONFLOW_API_KEY":
                key = value.strip().strip('"').strip("'")
                break
    require(bool(key) and key not in {"YOUR_API_KEY", "你的Key", "your-key"},
            f"Missing SILICONFLOW_API_KEY; configure it in {path} (never print or commit it)")
    require(not any(char.isspace() for char in key), "API key contains whitespace")
    return key


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def parse_vectors(payload, count):
    require(isinstance(payload, dict), "Embedding response must be an object")
    require(payload.get("model", MODEL) == MODEL, "Response model differs from requested model")
    data = payload.get("data")
    require(isinstance(data, list) and len(data) == count, "Response vector count mismatch")
    ordered = {}
    for item in data:
        require(isinstance(item, dict), "Invalid embedding item")
        index, vector = item.get("index"), item.get("embedding")
        require(type(index) is int and 0 <= index < count and index not in ordered,
                "Invalid or duplicate response index")
        require(isinstance(vector, list) and len(vector) == DIMENSIONS, "Vector dimension mismatch")
        require(all(type(value) in (int, float) and math.isfinite(value) for value in vector),
                "Embedding has non-finite or non-numeric values")
        norm = math.hypot(*vector)
        require(math.isfinite(norm) and norm > 0, "Embedding has invalid norm")
        ordered[index] = [value / norm for value in vector]
    return [ordered[index] for index in range(count)]


class Client:
    def __init__(self, key):
        self.key = key
        self.opener = urllib.request.build_opener(NoRedirect())

    def embed(self, texts):
        require(texts and all(text.strip() for text in texts), "Empty embedding input")
        request = urllib.request.Request(
            ENDPOINT,
            data=json.dumps({"model": MODEL, "input": texts, "encoding_format": "float"}).encode(),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.key}"},
            method="POST")
        started = time.monotonic()
        for attempt in range(4):
            retry_delay = min(2 ** (attempt + 1), 30)
            try:
                with self.opener.open(request, timeout=60) as response:
                    payload = json.load(response)
                vectors = parse_vectors(payload, len(texts))
                usage = payload.get("usage", {})
                tokens = usage.get("total_tokens", usage.get("prompt_tokens", 0))
                require(type(tokens) is int and tokens >= 0, "Invalid token usage in response")
                return vectors, tokens, round(time.monotonic() - started, 3)
            except urllib.error.HTTPError as exc:
                code = exc.code
                retry_after = exc.headers.get("Retry-After", "")
                exc.close()
                if code not in {429, 500, 502, 503, 504} or attempt == 3:
                    raise ValueError(f"Embedding API HTTP {code}; check credentials, model access, quota or input limits") from None
                if retry_after.isdigit():
                    retry_delay = min(30, max(retry_delay, int(retry_after)))
            except (urllib.error.URLError, TimeoutError):
                if attempt == 3:
                    raise ValueError("Embedding network request failed after 4 attempts") from None
            print(f"Transient API failure; retry in {retry_delay}s", flush=True)
            time.sleep(retry_delay)
        raise AssertionError("unreachable")


def add_usage(connection, tokens):
    current = status(connection)["usage"]
    current["successful_requests"] += 1
    current["reported_tokens"] += tokens
    connection.execute("INSERT OR REPLACE INTO metadata VALUES ('usage',?)", (json.dumps(current),))


def smoke_test(connection, config, client):
    longest = connection.execute("SELECT text FROM items WHERE kind='corpus' ORDER BY length(text) DESC LIMIT 1").fetchone()[0]
    texts = ["如何为项目配置数据库连接？", "项目的数据库连接应该怎么设置？",
             "香蕉是一种水果。", "如何为项目配置数据库连接？", longest]
    vectors, tokens, seconds = client.embed(texts)
    cosine = lambda a, b: sum(x * y for x, y in zip(a, b))
    repeat_similarity = cosine(vectors[0], vectors[3])
    require(repeat_similarity > 0.999, "Identical inputs produced inconsistent embeddings")
    report = {"status": "passed", "config_fingerprint": fingerprint(config),
              "endpoint": ENDPOINT, "model": MODEL, "dimensions": DIMENSIONS,
              "sample_count": len(texts), "latency_seconds": seconds,
              "reported_tokens": tokens, "duplicate_cosine": repeat_similarity,
              "paraphrase_cosine": cosine(vectors[0], vectors[1]),
              "unrelated_cosine": cosine(vectors[0], vectors[2]),
              "note": "Smoke test verifies the API contract, not retrieval quality."}
    with connection:
        add_usage(connection, tokens)
        connection.execute("INSERT OR REPLACE INTO metadata VALUES ('smoke',?)", (json.dumps(report),))
    return report


def run_batches(connection, client, batch_size, max_items, interval):
    processed = 0
    while max_items == 0 or processed < max_items:
        limit = min(batch_size, max_items - processed) if max_items else batch_size
        rows = connection.execute(
            "SELECT kind,id,text FROM items WHERE vector IS NULL ORDER BY kind,id LIMIT ?", (limit,)).fetchall()
        if not rows:
            break
        vectors, tokens, seconds = client.embed([row[2] for row in rows])
        with connection:
            for (kind, item_id, _), vector in zip(rows, vectors):
                connection.execute("UPDATE items SET vector=? WHERE kind=? AND id=?",
                                   (struct.pack(f"<{DIMENSIONS}f", *vector), kind, item_id))
            add_usage(connection, tokens)
        processed += len(rows)
        print(json.dumps({"processed_this_run": processed, "batch_seconds": seconds,
                          **status(connection)}, ensure_ascii=False), flush=True)
        time.sleep(interval)
    return status(connection)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["plan", "smoke", "run", "status", "verify"])
    parser.add_argument("--subset", type=Path, default=ROOT / "duretrieval/subset_q200_c10000_s42")
    parser.add_argument("--output", type=Path, default=ROOT / "duretrieval/embeddings_bge_m3")
    parser.add_argument("--env-file", type=Path, default=ROOT / "embedding.env")
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--max-items", type=int, default=100, help="run: default 100 for pilot; 0 for all pending")
    parser.add_argument("--interval", type=float, default=1.0)
    args = parser.parse_args()
    connection = None
    try:
        require(1 <= args.batch_size <= 32 and args.max_items >= 0 and args.interval >= 0,
                "Invalid batch size, item limit or interval")
        connection, config = open_checkpoint(args.subset, args.output)
        if args.command in {"plan", "status"}:
            report = {"output": str(args.output), "config": config, **status(connection)}
        elif args.command == "verify":
            report = verify_checkpoint(connection, args.subset)
        else:
            client = Client(read_key(args.env_file))
            if args.command == "smoke":
                report = smoke_test(connection, config, client)
            else:
                stored = connection.execute("SELECT value FROM metadata WHERE key='smoke'").fetchone()
                require(stored and json.loads(stored[0])["config_fingerprint"] == fingerprint(config),
                        "Run a successful live smoke test before batch generation")
                report = run_batches(connection, client, args.batch_size, args.max_items, args.interval)
        (args.output / f"{args.command}_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
    except (ValueError, OSError, sqlite3.Error, KeyError, TypeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupted; committed batches are saved. Resume with the same run command.", file=sys.stderr)
        return 130
    finally:
        if connection is not None:
            connection.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
