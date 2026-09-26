"""Small offline tests for sampling and rejection of broken retrieval datasets."""
from pathlib import Path
import tempfile
import unittest

import rag_dataset as dataset


class DatasetTests(unittest.TestCase):
    def setUp(self):
        self.source = {
            "corpus": [{"id": f"d{i}", "text": f"Document {i}"} for i in range(12)],
            "queries": [{"id": f"q{i}", "text": f"Question {i}"} for i in range(4)],
            "qrels": [{"qid": f"q{i}", "pid": f"d{j}", "score": 1}
                      for i in range(4) for j in (i, i + 4)],
        }

    def make_subset(self, directory):
        rows, positives = dataset.select_subset(self.source, 4, 10, 42)
        for name, values in rows.items():
            dataset.write_jsonl(directory / name, values)
        manifest = {
            "schema_version": 1,
            "sampling": {"query_count": 4, "corpus_count": 10, "seed": 42},
            "sources": dataset.source_metadata(),
            "relevant_corpus_count": positives,
            "files": {name: {"rows": len(values), "sha256": dataset.sha256(directory / name)}
                      for name, values in rows.items()},
        }
        dataset.write_json(directory / "manifest.json", manifest)
        return rows, manifest

    def rewrite(self, directory, filename, rows, manifest):
        dataset.write_jsonl(directory / filename, rows)
        manifest["files"][filename] = {"rows": len(rows), "sha256": dataset.sha256(directory / filename)}
        dataset.write_json(directory / "manifest.json", manifest)

    def test_deterministic_and_preserves_all_judgments(self):
        rows, _ = dataset.select_subset(self.source, 2, 8, 42)
        reversed_source = {key: list(reversed(value)) for key, value in self.source.items()}
        self.assertEqual(rows, dataset.select_subset(reversed_source, 2, 8, 42)[0])
        selected = {row["id"] for row in rows["queries.jsonl"]}
        self.assertEqual(rows["qrels.jsonl"], sorted(
            [row for row in self.source["qrels"] if row["qid"] in selected],
            key=lambda row: (row["qid"], row["pid"])))
        self.assertTrue({row["pid"] for row in rows["qrels.jsonl"]}
                        <= {row["id"] for row in rows["corpus.jsonl"]})

    def test_rejects_candidate_budget_smaller_than_positives(self):
        with self.assertRaisesRegex(ValueError, "all relevant texts"):
            dataset.select_subset(self.source, 4, 7, 42)

    def test_rejects_bad_source_reference(self):
        self.source["qrels"][0]["pid"] = "missing"
        with self.assertRaisesRegex(ValueError, "missing corpus ID"):
            dataset.select_subset(self.source, 2, 8, 42)

    def test_valid_fixture(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            self.make_subset(directory)
            report = dataset.validate(directory)
            self.assertEqual(report["status"], "passed")
            self.assertEqual(report["dev_query_count"], 2)
            self.assertFalse(report["source_reproduction_verified"])

    def test_detects_file_tampering(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            self.make_subset(directory)
            with (directory / "corpus.jsonl").open("a", encoding="utf-8") as handle:
                handle.write("\n")
            with self.assertRaisesRegex(ValueError, "Checksum mismatch"):
                dataset.validate(directory)

    def test_rejects_duplicate_ids_even_with_updated_checksum(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            rows, manifest = self.make_subset(directory)
            rows["corpus.jsonl"][1] = rows["corpus.jsonl"][0]
            self.rewrite(directory, "corpus.jsonl", rows["corpus.jsonl"], manifest)
            with self.assertRaisesRegex(ValueError, "duplicate ID"):
                dataset.validate(directory)

    def test_rejects_overlapping_splits(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            rows, manifest = self.make_subset(directory)
            rows["queries.test.jsonl"][0] = rows["queries.dev.jsonl"][0]
            self.rewrite(directory, "queries.test.jsonl", rows["queries.test.jsonl"], manifest)
            with self.assertRaisesRegex(ValueError, "overlap"):
                dataset.validate(directory)

    def test_rejects_missing_split_judgments(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            rows, manifest = self.make_subset(directory)
            self.rewrite(directory, "qrels.dev.jsonl", rows["qrels.dev.jsonl"][1:], manifest)
            with self.assertRaisesRegex(ValueError, "do not match full qrels"):
                dataset.validate(directory)

    def test_rejects_blank_source_text(self):
        self.source["corpus"][0]["text"] = "  "
        with self.assertRaisesRegex(ValueError, "empty text"):
            dataset.select_subset(self.source, 2, 8, 42)


if __name__ == "__main__":
    unittest.main()
