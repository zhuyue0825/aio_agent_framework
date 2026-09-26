"""Offline checks; these tests never contact SiliconFlow."""
from pathlib import Path
import sqlite3
import struct
import tempfile
import unittest
from unittest.mock import patch

import rag_embeddings as embeddings
from rag_dataset import write_jsonl


class FakeClient:
    def __init__(self, fail_on=None):
        self.calls = 0
        self.fail_on = fail_on

    def embed(self, texts):
        self.calls += 1
        if self.calls == self.fail_on:
            raise ValueError("simulated failure")
        vector = [1.0] + [0.0] * (embeddings.DIMENSIONS - 1)
        return [vector[:] for _ in texts], len(texts), 0.01


class EmbeddingTests(unittest.TestCase):
    def test_chunks_preserve_tail_and_cover_all_characters(self):
        text = "中文abc" * 697
        parts = list(embeddings.chunks(text))
        covered = set()
        for start, end, part in parts:
            self.assertEqual(part, text[start:end])
            self.assertLessEqual(len(part), embeddings.CHUNK_SIZE)
            covered.update(range(start, end))
        self.assertEqual(covered, set(range(len(text))))
        self.assertEqual(parts[-1][1], len(text))
        self.assertEqual(len(list(embeddings.chunks("a" * embeddings.CHUNK_SIZE))), 1)

    def test_response_reordered_and_normalized(self):
        a = [2.0] + [0.0] * 1023
        b = [0.0, 3.0] + [0.0] * 1022
        vectors = embeddings.parse_vectors({"data": [
            {"index": 1, "embedding": b}, {"index": 0, "embedding": a}]}, 2)
        self.assertEqual(vectors[0][0], 1.0)
        self.assertEqual(vectors[1][1], 1.0)

    def test_rejects_dimension_nonfinite_zero_and_duplicate_indices(self):
        vectors = [[1.0], [float("nan")] * 1024, [0.0] * 1024]
        for vector in vectors:
            with self.subTest(vector_head=vector[0]), self.assertRaises(ValueError):
                embeddings.parse_vectors({"data": [{"index": 0, "embedding": vector}]}, 1)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            embeddings.parse_vectors({"data": [
                {"index": 0, "embedding": [1.0] * 1024},
                {"index": 0, "embedding": [1.0] * 1024}]}, 2)

    def make_input(self, root):
        subset = root / "subset"
        subset.mkdir()
        write_jsonl(subset / "corpus.jsonl", [{"id": "d1", "text": "资料" * 1200}])
        write_jsonl(subset / "queries.jsonl", [{"id": "q1", "text": "问题？"}])
        return subset

    @patch.object(embeddings, "validate")
    def test_rejects_changed_source_on_resume(self, _):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            subset = self.make_input(root)
            connection, _ = embeddings.open_checkpoint(subset, root / "output")
            connection.close()
            write_jsonl(subset / "queries.jsonl", [{"id": "q1", "text": "不同问题"}])
            with self.assertRaisesRegex(ValueError, "configuration/input changed"):
                embeddings.open_checkpoint(subset, root / "output")

    @patch.object(embeddings, "validate")
    @patch("builtins.print")
    def test_resume_skips_committed_vectors_after_failure(self, _print, _validate):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            subset = self.make_input(root)
            connection, _ = embeddings.open_checkpoint(subset, root / "output")
            try:
                with self.assertRaisesRegex(ValueError, "simulated failure"):
                    embeddings.run_batches(connection, FakeClient(fail_on=2), 2, 0, 0)
                self.assertEqual(connection.execute("SELECT count(*) FROM items WHERE vector IS NOT NULL").fetchone()[0], 2)
                client = FakeClient()
                report = embeddings.run_batches(connection, client, 2, 0, 0)
                self.assertTrue(all(value["pending"] == 0 for value in report["items"].values()))
                self.assertEqual(client.calls, 1)
                vector = connection.execute("SELECT vector FROM items LIMIT 1").fetchone()[0]
                self.assertEqual(len(vector), 4096)
                self.assertEqual(struct.unpack("<1024f", vector)[0], 1.0)
                verification = embeddings.verify_checkpoint(connection, subset)
                self.assertEqual(verification["checked_vectors"], 4)
                with connection:
                    connection.execute("UPDATE items SET vector=? WHERE kind='query'", (b"bad",))
                with self.assertRaisesRegex(ValueError, "Missing/invalid vector"):
                    embeddings.verify_checkpoint(connection, subset)
                embeddings.run_batches(connection, client, 2, 0, 0)
                self.assertEqual(client.calls, 1)
            finally:
                connection.close()

    @patch.object(embeddings, "validate")
    def test_smoke_report_persists_without_item_vectors(self, _):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            subset = self.make_input(root)
            connection, config = embeddings.open_checkpoint(subset, root / "output")
            try:
                report = embeddings.smoke_test(connection, config, FakeClient())
                self.assertEqual(report["dimensions"], 1024)
                self.assertTrue(embeddings.status(connection)["smoke_passed"])
                self.assertEqual(connection.execute("SELECT count(*) FROM items WHERE vector IS NOT NULL").fetchone()[0], 0)
            finally:
                connection.close()

    @patch.dict("os.environ", {}, clear=True)
    def test_missing_key_and_bom_env_file(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "embedding.env"
            path.write_text("SILICONFLOW_API_KEY=\n", encoding="utf-8-sig")
            with self.assertRaisesRegex(ValueError, "Missing SILICONFLOW_API_KEY"):
                embeddings.read_key(path)
            path.write_text("SILICONFLOW_API_KEY=test-only-key\n", encoding="utf-8-sig")
            self.assertEqual(embeddings.read_key(path), "test-only-key")


if __name__ == "__main__":
    unittest.main()
