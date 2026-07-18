"""M4 tests — the over-many aggregator (ADR-0003): union correctness, read-only."""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from boonyard import aggregator, init_db, log_entry
from boonyard.aggregator import Aggregator


class AggregatorTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        d = Path(self._tmp.name)
        self.path_a = d / "a" / "journal.db"
        self.path_b = d / "b" / "journal.db"
        init_db(self.path_a, node_name="alpha")
        init_db(self.path_b, node_name="beta")
        log_entry("code", "note", "from A one", tags="shared,onlya", db_path=self.path_a)
        log_entry("code", "decision", "from A two", tags="shared", db_path=self.path_a)
        log_entry("opus", "note", "from B one", tags="shared,onlyb", db_path=self.path_b)
        self.agg = Aggregator({"a": str(self.path_a), "b": str(self.path_b)})

    def tearDown(self):
        self._tmp.cleanup()


class UnionTests(AggregatorTestCase):
    def test_recent_unions_all_nodes_with_source(self):
        rows = self.agg.recent()
        self.assertEqual(len(rows), 3)
        sources = {r["source"] for r in rows}
        self.assertEqual(sources, {"a", "b"})

    def test_recent_scope_narrowing(self):
        rows = self.agg.recent(scope=["a"])
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r["source"] == "a" for r in rows))

    def test_recent_single_name_scope(self):
        rows = self.agg.recent(scope="b")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["content"], "from B one")

    def test_unknown_scope_raises(self):
        with self.assertRaises(ValueError):
            self.agg.recent(scope=["nonexistent"])

    def test_by_id_returns_first_with_source(self):
        row = self.agg.by_id(1)
        self.assertIsNotNone(row)
        self.assertIn(row["source"], {"a", "b"})

    def test_search_by_tag_across_nodes(self):
        self.assertEqual(len(self.agg.search_by_tag("shared")), 3)
        self.assertEqual(len(self.agg.search_by_tag_exact("onlyb")), 1)

    def test_search_text_across_nodes(self):
        hits = self.agg.search_text("from")
        self.assertEqual(len(hits), 3)

    def test_list_tags_sums_counts_across_nodes(self):
        tags = {t["tag"]: t["count"] for t in self.agg.list_tags()}
        self.assertEqual(tags["shared"], 3)  # 2 in A + 1 in B

    def test_list_agents_and_types_union(self):
        agents = {a["agent"]: a["count"] for a in self.agg.list_agents()}
        self.assertEqual(agents, {"code": 2, "opus": 1})
        types = {t["entry_type"] for t in self.agg.list_entry_types()}
        self.assertEqual(types, {"note", "decision"})

    def test_list_nodes_metadata(self):
        nodes = {n["slug"]: n for n in self.agg.list_nodes()}
        self.assertEqual(nodes["a"]["name"], "alpha")
        self.assertEqual(nodes["a"]["entry_count"], 2)
        self.assertEqual(nodes["b"]["entry_count"], 1)

    def test_scope_all_equals_default(self):
        self.assertEqual(len(self.agg.recent(scope="all")), 3)

    def test_by_id_miss_returns_none(self):
        self.assertIsNone(self.agg.by_id(9999))

    def test_get_thread_across_nodes(self):
        # Add a child of entry id 1 in node A. Note ids are node-local, so
        # get_thread(1) also matches node B's id=1 — each row carries its source.
        log_entry("code", "note", "child of A#1", related_id=1, db_path=self.path_a)
        thread = self.agg.get_thread(1)
        child = next(e for e in thread if e["content"] == "child of A#1")
        self.assertEqual(child["source"], "a")
        self.assertEqual(child["related_id"], 1)

    def test_list_tags_tree(self):
        tree = self.agg.list_tags(tree=True)
        self.assertIn("shared", tree)
        self.assertIn("onlya", tree)

    def test_nodes_accessor(self):
        self.assertEqual(set(self.agg.nodes()), {"a", "b"})


class ReadOnlyTests(AggregatorTestCase):
    def test_no_write_methods_exposed(self):
        self.assertFalse(hasattr(self.agg, "log_entry"))
        self.assertFalse(hasattr(self.agg, "retag_entry"))

    def test_write_through_attached_connection_fails(self):
        # query_only = ON makes writes physically impossible on the aggregator conn.
        with self.assertRaises(sqlite3.OperationalError):
            with self.agg._attach(["a"]) as conn:
                conn.execute(
                    'INSERT INTO "a".entry (agent, entry_type, content) VALUES (?,?,?)',
                    ("code", "note", "nope"),
                )


class ConfigAndValidationTests(unittest.TestCase):
    def test_invalid_node_name_rejected(self):
        with self.assertRaises(ValueError):
            Aggregator({"bad name!": "/x/journal.db"})

    def test_aggregator_from_umbrella_toml(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "journal.db"
            init_db(path, node_name="solo")
            log_entry("code", "note", "hi", tags="model:claude-opus-4-8", db_path=path)
            cfg = Path(d) / "umbrella.toml"
            cfg.write_text(f'[nodes]\nsolo = "{path.as_posix()}"\n')
            agg = aggregator(cfg)
            self.assertEqual(len(agg.recent()), 1)
            self.assertEqual(agg.recent()[0]["source"], "solo")

    def test_aggregator_from_nodes_mapping(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "journal.db"
            init_db(path, node_name="solo")
            log_entry("code", "note", "hi", db_path=path)
            agg = aggregator(nodes={"solo": str(path)})
            self.assertEqual(len(agg.recent()), 1)

    def test_aggregator_requires_config_or_nodes(self):
        with self.assertRaises(ValueError):
            aggregator()

    def test_empty_scope_config_returns_empty(self):
        agg = Aggregator({})
        self.assertEqual(agg.recent(), [])
        self.assertEqual(agg.list_tags(), [])


if __name__ == "__main__":
    unittest.main()
