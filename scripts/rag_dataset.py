"""Prepare and validate a reproducible DuRetrieval retrieval-only experiment.

Preparation/source validation requires pyarrow; ordinary validation is stdlib-only.
No embedding or language model is called. See docs/RAG_DATASET.md.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import random
import shutil
import sys
import tempfile
import time
import urllib.request


SOURCES = {
    "corpus": ("C-MTEB/DuRetrieval", "a1a333e290fe30b10f3f56498e3a0d911a693ced",
               "data/corpus-00000-of-00001-19b9e924cb33e4d5.parquet",
               "d4b4eb51b63549ef0851a15fc63c2a61b703dce95e3727b535a08f7ba1d14424", 64412709),
    "queries": ("C-MTEB/DuRetrieval", "a1a333e290fe30b10f3f56498e3a0d911a693ced",
                "data/queries-00000-of-00001-7c7edb40be6b560c.parquet",
                "62ac55e764bffd4ffceb0aa51e7a536a0e5932f23c8606566906db6a9efb4b94", 118461),
    "qrels": ("C-MTEB/DuRetrieval-qrels", "497b7bd1bbb25cb3757ff34d95a8be50a3de2279",
              "data/dev-00000-of-00001-d3c385852a7c0c9d.parquet",
              "c87e7c16f535a98b29ee0ebf6977639c793e3bd149c04634a1810273cfd3c3e5", 420443),
}
FILES = ("corpus.jsonl", "queries.jsonl", "qrels.jsonl", "queries.dev.jsonl",
         "queries.test.jsonl", "qrels.dev.jsonl", "qrels.test.jsonl")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def write_jsonl(path, rows):
    with Path(path).open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")


def read_jsonl(path):
    rows = []
    with Path(path).open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            require(bool(line.strip()), f"{path}:{number}: blank line")
            row = json.loads(line)
            require(isinstance(row, dict), f"{path}:{number}: expected object")
            rows.append(row)
    return rows


def text_index(rows, label):
    result = {}
    for row in rows:
        require(set(row) == {"id", "text"}, f"{label}: expected id,text fields")
        key, text = row["id"], row["text"]
        require(isinstance(key, str) and bool(key.strip()), f"{label}: invalid ID")
        require(isinstance(text, str) and bool(text.strip()), f"{label}: empty text: {key}")
        require(key not in result, f"{label}: duplicate ID: {key}")
        result[key] = row
    return result


def relevance_index(rows, queries, corpus):
    result = {}
    for row in rows:
        require(set(row) == {"qid", "pid", "score"}, "qrels: expected qid,pid,score fields")
        qid, pid, score = row["qid"], row["pid"], row["score"]
        require(isinstance(qid, str) and isinstance(pid, str), "qrels: IDs must be strings")
        require(qid in queries, f"qrels: missing query: {qid}")
        require(pid in corpus, f"qrels: missing corpus ID: {pid}")
        require(isinstance(score, (int, float)) and not isinstance(score, bool)
                and math.isfinite(score) and score > 0, "qrels: score must be finite and positive")
        require((qid, pid) not in result, f"qrels: duplicate pair: {qid}, {pid}")
        result[qid, pid] = score
    return result


def download(raw_dir):
    raw_dir.mkdir(parents=True, exist_ok=True)
    for name, (repo, revision, filename, expected_hash, expected_size) in SOURCES.items():
        destination = raw_dir / f"{name}.parquet"
        if destination.exists():
            require(destination.stat().st_size == expected_size and sha256(destination) == expected_hash,
                    f"Cached source is corrupt: {destination}; move it aside before retrying")
            print(f"Verified cached {name}", flush=True)
            continue
        url = f"https://huggingface.co/datasets/{repo}/resolve/{revision}/{filename}"
        partial = destination.with_suffix(".parquet.part")
        for attempt in range(3):
            try:
                print(f"Downloading {name} ({expected_size:,} bytes), attempt {attempt + 1}", flush=True)
                request = urllib.request.Request(url, headers={"User-Agent": "aio-rag-dataset/1.0"})
                with urllib.request.urlopen(request, timeout=60) as response, partial.open("wb") as output:
                    shutil.copyfileobj(response, output, 1024 * 1024)
                require(partial.stat().st_size == expected_size and sha256(partial) == expected_hash,
                        f"Download checksum mismatch: {name}")
                partial.replace(destination)
                break
            except Exception:
                partial.unlink(missing_ok=True)
                if attempt == 2:
                    raise
                time.sleep(2 * (attempt + 1))


def load_sources(raw_dir):
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise ValueError("Install scripts/requirements-rag-data.txt for preparation/source validation") from exc
    result = {}
    for name, (_, _, _, expected_hash, expected_size) in SOURCES.items():
        path = raw_dir / f"{name}.parquet"
        require(path.stat().st_size == expected_size and sha256(path) == expected_hash,
                f"Source checksum mismatch: {path}")
        result[name] = pq.read_table(path).to_pylist()
    return result


def select_subset(source, query_count, corpus_count, seed):
    require(query_count >= 2, "Need at least 2 queries for dev/test")
    corpus = text_index(source["corpus"], "source corpus")
    queries = text_index(source["queries"], "source queries")
    relevance_index(source["qrels"], queries, corpus)
    eligible = sorted({row["qid"] for row in source["qrels"]})
    require(query_count <= len(eligible), "Not enough queries with positive judgments")
    selected = set(random.Random(seed).sample(eligible, query_count))
    qrels = sorted((row for row in source["qrels"] if row["qid"] in selected),
                   key=lambda row: (row["qid"], row["pid"]))
    positives = {row["pid"] for row in qrels}
    require(len(positives) <= corpus_count <= len(corpus),
            f"corpus-count must be between {len(positives)} (all relevant texts) and {len(corpus)}")
    # Unjudged candidates are not asserted to be true negatives.
    other_ids = random.Random(seed + 1).sample(sorted(set(corpus) - positives), corpus_count - len(positives))
    selected_corpus = positives | set(other_ids)
    split_ids = sorted(selected)
    random.Random(seed + 2).shuffle(split_ids)
    dev_ids = set(split_ids[:query_count // 2])
    rows = {
        "corpus.jsonl": [corpus[key] for key in sorted(selected_corpus)],
        "queries.jsonl": [queries[key] for key in sorted(selected)],
        "qrels.jsonl": qrels,
        "queries.dev.jsonl": [queries[key] for key in sorted(dev_ids)],
        "queries.test.jsonl": [queries[key] for key in sorted(selected - dev_ids)],
        "qrels.dev.jsonl": [row for row in qrels if row["qid"] in dev_ids],
        "qrels.test.jsonl": [row for row in qrels if row["qid"] not in dev_ids],
    }
    return rows, len(positives)


def validate(directory, raw_dir=None):
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    require(manifest["schema_version"] == 1, "Unsupported manifest version")
    require(set(manifest["files"]) == set(FILES), "Manifest file set mismatch")
    rows = {}
    for filename in FILES:
        path = directory / filename
        require(sha256(path) == manifest["files"][filename]["sha256"], f"Checksum mismatch: {filename}")
        rows[filename] = read_jsonl(path)
        require(len(rows[filename]) == manifest["files"][filename]["rows"], f"Row count mismatch: {filename}")
    corpus = text_index(rows["corpus.jsonl"], "corpus")
    queries = text_index(rows["queries.jsonl"], "queries")
    qrels = relevance_index(rows["qrels.jsonl"], queries, corpus)
    require({qid for qid, _ in qrels} == set(queries), "Every query must have positive judgments")
    dev = text_index(rows["queries.dev.jsonl"], "dev queries")
    test = text_index(rows["queries.test.jsonl"], "test queries")
    require(dev and test, "Dev and test must be nonempty")
    require(not (dev.keys() & test.keys()), "Dev/test query IDs overlap")
    require(dev.keys() | test.keys() == queries.keys(), "Dev/test do not cover all queries")
    for key, row in {**dev, **test}.items():
        require(row == queries[key], f"Split query differs from queries.jsonl: {key}")
    for label, subset in (("dev", dev), ("test", test)):
        split_qrels = relevance_index(rows[f"qrels.{label}.jsonl"], subset, corpus)
        require(split_qrels == {pair: score for pair, score in qrels.items() if pair[0] in subset},
                f"{label} qrels do not match full qrels")
    sampling = manifest["sampling"]
    require(len(queries) == sampling["query_count"] and len(corpus) == sampling["corpus_count"],
            "Sample sizes do not match manifest")
    require(len(dev) == len(queries) // 2, "Unexpected dev/test split sizes")
    positive_ids = {pid for _, pid in qrels}
    require(len(positive_ids) == manifest["relevant_corpus_count"], "Relevant corpus count mismatch")
    expected_sources = source_metadata()
    require(manifest["sources"] == expected_sources, "Source revisions/checksums differ from pinned sources")
    source_verified = False
    if raw_dir is not None:
        source = load_sources(raw_dir)
        expected, _ = select_subset(source, sampling["query_count"], sampling["corpus_count"], sampling["seed"])
        for filename in FILES:
            require(rows[filename] == expected[filename], f"Source reproduction mismatch: {filename}")
        require(manifest["source_counts"] == {name: len(value) for name, value in source.items()},
                "Source counts mismatch")
        source_verified = True
    texts = [row["text"] for row in corpus.values()]
    dev_texts = {row["text"].strip() for row in dev.values()}
    test_texts = {row["text"].strip() for row in test.values()}
    require(not (dev_texts & test_texts), "Identical query text appears in dev and test")
    report = {
        "status": "passed", "corpus_count": len(corpus), "query_count": len(queries),
        "qrels_count": len(qrels), "dev_query_count": len(dev), "test_query_count": len(test),
        "relevant_corpus_count": len(positive_ids),
        "additional_unjudged_corpus_count": len(corpus) - len(positive_ids),
        "duplicate_corpus_text_count": len(texts) - len(set(texts)),
        "max_corpus_characters": max(map(len, texts)),
        "corpus_over_8000_characters": sum(len(text) > 8000 for text in texts),
        "source_reproduction_verified": source_verified,
        "notes": ["Retrieval subset experiment, not a full benchmark score.",
                  "qrels label relevance, not complete reference answers.",
                  "Additional candidates are unjudged, not guaranteed negatives.",
                  "Local dev/test are split from upstream dev judgments; corpus is shared.",
                  "Texts are unchanged; long texts need an explicit embedding/chunking policy."],
    }
    return report


def source_metadata():
    return {name: {"repository": repo, "revision": revision, "path": filename,
                   "sha256": digest, "bytes": size}
            for name, (repo, revision, filename, digest, size) in SOURCES.items()}


def prepare(root, query_count, corpus_count, seed):
    destination = root / f"subset_q{query_count}_c{corpus_count}_s{seed}"
    require(not destination.exists(), f"Output already exists: {destination}; use validate or another seed/root")
    raw_dir = root / "raw"
    download(raw_dir)
    source = load_sources(raw_dir)
    rows, positive_count = select_subset(source, query_count, corpus_count, seed)
    # Validate a staged output before publishing it; never overwrite an existing experiment.
    with tempfile.TemporaryDirectory(prefix=".prepare-", dir=root) as temp:
        stage = Path(temp) / "subset"
        stage.mkdir()
        for filename, values in rows.items():
            write_jsonl(stage / filename, values)
        manifest = {
            "schema_version": 1, "dataset": "DuRetrieval", "experiment": "sampled-retrieval-only",
            "sampling": {"query_count": query_count, "corpus_count": corpus_count, "seed": seed,
                         "algorithm": "sorted IDs; Python Random sample(seed), candidates(seed+1), split shuffle(seed+2)"},
            "sources": source_metadata(), "source_counts": {name: len(value) for name, value in source.items()},
            "relevant_corpus_count": positive_count,
            "files": {name: {"rows": len(values), "sha256": sha256(stage / name)} for name, values in rows.items()},
            "python_version": sys.version.split()[0],
        }
        write_json(stage / "manifest.json", manifest)
        report = validate(stage, raw_dir)
        write_json(stage / "validation_report.json", report)
        stage.rename(destination)
    print(json.dumps({"output": str(destination), **report}, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    preparation = commands.add_parser("prepare")
    preparation.add_argument("--data-root", type=Path, default=Path(__file__).resolve().parents[2] / "codex_data" / "duretrieval")
    preparation.add_argument("--queries", type=int, default=200)
    preparation.add_argument("--corpus", type=int, default=10000)
    preparation.add_argument("--seed", type=int, default=42)
    validation = commands.add_parser("validate")
    validation.add_argument("--subset", type=Path, required=True)
    validation.add_argument("--raw-dir", type=Path, help="Also verify sources and reproduce the exact sample")
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            require(args.queries >= 2 and args.corpus >= 1, "Invalid sample sizes")
            prepare(args.data_root.resolve(), args.queries, args.corpus, args.seed)
        else:
            report = validate(args.subset.resolve(), args.raw_dir.resolve() if args.raw_dir else None)
            print(json.dumps(report, ensure_ascii=False, indent=2))
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
