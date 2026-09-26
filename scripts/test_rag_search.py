"""Metric tests plus opt-in rollback-only integration test against the lab DB."""
import math
import os
import unittest

import rag_search as search


class MetricTests(unittest.TestCase):
    def test_perfect_ranking(self):
        result = search.metrics(["a", "b", "c"], {"a": 1, "b": 1})
        self.assertEqual(result["recall_at_5"], 1)
        self.assertEqual(result["ndcg_at_10"], 1)

    def test_partial_recall_and_rank_discount(self):
        result = search.metrics(["x", "a"], {"a": 1, "b": 1})
        self.assertEqual(result["recall_at_10"], .5)
        self.assertAlmostEqual(result["ndcg_at_10"], (1 / math.log2(3)) / (1 + 1 / math.log2(3)))

    def test_no_hit(self):
        result = search.metrics(["x"], {"a": 1})
        self.assertEqual(result["hit_at_10"], 0)
        self.assertEqual(result["ndcg_at_10"], 0)

    def test_top_k_boundary(self):
        result = search.metrics([f"d{i}" for i in range(11)], {"d5": 1, "d10": 1})
        self.assertEqual(result["recall_at_5"], 0)
        self.assertEqual(result["recall_at_10"], .5)

    def test_reject_duplicate_document_ids(self):
        with self.assertRaisesRegex(ValueError, "unique"):
            search.metrics(["a", "a"], {"a": 1})


@unittest.skipUnless(os.environ.get("RAG_SEARCH_INTEGRATION") == "1", "set RAG_SEARCH_INTEGRATION=1 for lab DB test")
class IntegrationTests(unittest.TestCase):
    def test_parent_dedup_before_limit_and_rollback(self):
        with search.connect(search.ROOT / "rag-postgres.env") as db:
            before = db.execute("SELECT count(*) FROM rag_lab.chunks").fetchone()[0]
            with db.transaction(force_rollback=True):
                for item_id, parent, vector in [
                    ("_test_a1", "_test_a", [1., 0.] + [0.] * 1022),
                    ("_test_a2", "_test_a", [1., 0.] + [0.] * 1022),
                    ("_test_b", "_test_b", [.999, .001] + [0.] * 1022),
                ]:
                    db.execute("INSERT INTO rag_lab.chunks VALUES (%s,%s,0,4,'test','test',%s::vector)",
                               (item_id, parent, search.vector_text(vector)))
                results, _ = search.search(db, search.vector_text([1.] + [0.] * 1023), 2)
                self.assertEqual([row["document_id"] for row in results], ["_test_a", "_test_b"])
                self.assertEqual(results[0]["chunk_id"], "_test_a1")
            after = db.execute("SELECT count(*) FROM rag_lab.chunks").fetchone()[0]
            self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
