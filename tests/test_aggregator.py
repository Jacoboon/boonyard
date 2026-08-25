"""M4 tests — the over-many aggregator (ADR-0003): union correctness, read-only."""

import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path

from boonyard import aggregator, init_db, log_entry, meter
from boonyard.aggregator import Aggregator

# Pinned so days_out never drifts with the wall clock.
PINNED = date(2026, 8, 24)


def _make_v2_node(path: Path) -> None:
    """A pre-v3 node: table ``journal``, no ``entry``. The vectorscape-wall shape.

    This is the exact file that took down reads across all six registered nodes
    (boonyard #76 Finding 2, "no such table: vectorscape_wall.entry").
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE journal (id INTEGER PRIMARY KEY, content TEXT)")
    conn.execute("INSERT INTO journal (content) VALUES ('a v2 wall entry')")
    conn.commit()
    conn.close()


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


# --------------------------------------------------------------------------
# A broken node degrades the union; it never kills it (ADR-0003 clarification)
# --------------------------------------------------------------------------
class DegradedUnionTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        d = Path(self._tmp.name)
        self.good = d / "good" / "journal.db"
        init_db(self.good, node_name="good")
        log_entry("code", "note", "healthy entry", tags="shared", db_path=self.good)
        self.v2 = d / "v2" / "journal.db"
        _make_v2_node(self.v2)
        self.missing = d / "gone" / "journal.db"
        self.junk = d / "junk" / "journal.db"
        self.junk.parent.mkdir(parents=True)
        self.junk.write_bytes(b"this is not a database, it is a text file")
        self.agg = Aggregator(
            {
                "good": str(self.good),
                "v2_wall": str(self.v2),
                "gone": str(self.missing),
                "junk": str(self.junk),
            }
        )

    def tearDown(self):
        self._tmp.cleanup()

    def test_probe_names_each_failure_mode(self):
        self.assertIsNone(self.agg._probe("good"))
        self.assertIn("entry", self.agg._probe("v2_wall"))
        self.assertIn("not found", self.agg._probe("gone"))
        self.assertIn("unreadable", self.agg._probe("junk"))

    def test_probe_does_not_create_a_missing_node_file(self):
        self.agg._probe("gone")
        self.assertFalse(self.missing.exists(), "probing must never mint a node file")

    def test_recent_serves_healthy_nodes_instead_of_raising(self):
        """boonyard #76 Finding 2: this call used to raise for EVERY node."""
        rows = self.agg.recent()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source"], "good")

    def test_every_reader_survives_a_broken_node(self):
        self.assertIsNotNone(self.agg.by_id(1))
        self.assertEqual(len(self.agg.get_thread(1)), 1)
        self.assertEqual(len(self.agg.search_by_tag("shared")), 1)
        self.assertEqual(len(self.agg.search_by_tag_exact("shared")), 1)
        self.assertEqual(len(self.agg.search_text("healthy")), 1)
        self.assertIn("shared", {t["tag"] for t in self.agg.list_tags()})
        self.assertEqual(self.agg.list_agents(), [{"agent": "code", "count": 1}])
        self.assertEqual(len(self.agg.list_entry_types()), 1)

    def test_list_nodes_reports_health_instead_of_crashing(self):
        nodes = {n["slug"]: n for n in self.agg.list_nodes()}
        self.assertTrue(nodes["good"]["healthy"])
        self.assertIsNone(nodes["good"]["warning"])
        for slug in ("v2_wall", "gone", "junk"):
            self.assertFalse(nodes[slug]["healthy"])
            self.assertTrue(nodes[slug]["warning"])

    def test_a_typo_in_scope_still_raises(self):
        """A broken node is an environment failure; an unknown NAME is a caller bug."""
        with self.assertRaises(ValueError):
            self.agg.recent(scope=["nonexistent"])

    def test_all_nodes_broken_returns_empty_not_an_exception(self):
        blind = Aggregator({"v2_wall": str(self.v2), "gone": str(self.missing)})
        self.assertEqual(blind.recent(), [])
        result = blind.upcoming_dates(45, today=PINNED)
        self.assertEqual(result["dates"], [])
        self.assertEqual(len(result["warnings"]), 2)


class UpcomingDatesAcrossNodesTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        d = Path(self._tmp.name)
        self.paths = {}
        for name in ("umbrella", "jrhood", "mindstorm"):
            path = d / name / "journal.db"
            init_db(path, node_name=name)
            self.paths[name] = str(path)
        log_entry(
            "conductor",
            "note",
            "R1 60-day falsification",
            tags="kill-date,killdate:2026-09-23",
            db_path=self.paths["umbrella"],
        )
        log_entry(
            "conductor",
            "note",
            "Searchlight hard stop",
            tags="killdate:2026-09-01",
            db_path=self.paths["umbrella"],
        )
        log_entry(
            "code",
            "note",
            "the gate that passed unread",
            tags="killdate:2026-08-20",
            db_path=self.paths["jrhood"],
        )
        log_entry(
            "code",
            "note",
            "someday",
            tags="killdate:whenever",
            db_path=self.paths["mindstorm"],
        )
        self.v2 = d / "v2" / "journal.db"
        _make_v2_node(self.v2)
        self.agg = Aggregator(dict(self.paths))
        self.with_broken = Aggregator({**self.paths, "v2_wall": str(self.v2)})

    def tearDown(self):
        self._tmp.cleanup()

    def test_scope_all_merges_and_sorts_across_three_nodes(self):
        result = self.agg.upcoming_dates(45, today=PINNED, scope="all")
        self.assertEqual(
            [(r["date"], r["node"]) for r in result["dates"]],
            [
                ("2026-08-20", "jrhood"),
                ("2026-09-01", "umbrella"),
                ("2026-09-23", "umbrella"),
            ],
        )
        self.assertTrue(result["dates"][0]["overdue"])
        self.assertEqual(result["dates"][0]["days_out"], -4)
        self.assertEqual(result["dates"][2]["days_out"], 30)

    def test_malformed_tag_on_one_node_warns_with_that_node_named(self):
        result = self.agg.upcoming_dates(45, today=PINNED, scope="all")
        warning = next(w for w in result["warnings"] if w["kind"] == "malformed_date_tag")
        self.assertEqual(warning["node"], "mindstorm")
        self.assertEqual(warning["tag"], "killdate:whenever")

    def test_scope_narrowing(self):
        result = self.agg.upcoming_dates(45, today=PINNED, scope=["jrhood"])
        self.assertEqual([r["node"] for r in result["dates"]], ["jrhood"])

    def test_broken_node_yields_healthy_results_plus_a_named_warning(self):
        """THE #76 FINDING-2 REGRESSION TEST.

        One unreadable node in scope must not take the register down with it:
        the tripwire would fail silent on the morning it matters most.
        """
        result = self.with_broken.upcoming_dates(45, today=PINNED, scope="all")
        self.assertEqual(len(result["dates"]), 3, "healthy nodes must still be served")
        skipped = [w for w in result["warnings"] if w["kind"] == "node_skipped"]
        self.assertEqual(len(skipped), 1)
        self.assertEqual(skipped[0]["node"], "v2_wall")
        self.assertIn("entry", skipped[0]["detail"])

    def test_envelope_carries_the_window_and_the_pinned_today(self):
        result = self.agg.upcoming_dates(10, today="2026-08-24", scope="all")
        self.assertEqual(result["today"], "2026-08-24")
        self.assertEqual(result["within_days"], 10)
        self.assertEqual(result["prefix"], "killdate")
        # 09-23 is 30 days out, past a 10-day window; 08-20 is overdue and stays.
        self.assertEqual([r["date"] for r in result["dates"]], ["2026-08-20", "2026-09-01"])

    def test_custom_prefix_across_scope(self):
        log_entry(
            "code",
            "note",
            "a review",
            tags="reviewdate:2026-09-02",
            db_path=self.paths["jrhood"],
        )
        result = self.agg.upcoming_dates(45, prefix="reviewdate", today=PINNED, scope="all")
        self.assertEqual([r["date"] for r in result["dates"]], ["2026-09-02"])


class ReadStatsAcrossNodesTests(unittest.TestCase):
    """Each node meters itself; the aggregator unions the sidecars (umbrella #228)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        d = Path(self._tmp.name)
        self.paths = {}
        for name in ("umbrella", "jrhood"):
            path = d / name / "journal.db"
            init_db(path, node_name=name)
            self.paths[name] = str(path)
        for _ in range(5):
            meter.record(
                meter.default_meter_path(self.paths["umbrella"]),
                "search_text",
                node="umbrella",
                kind="read",
                ts="2026-08-24T09:00:00",
            )
        for _ in range(2):
            meter.record(
                meter.default_meter_path(self.paths["jrhood"]),
                "log_entry",
                node="jrhood",
                kind="write",
                ts="2026-08-23T09:00:00",
            )
        self.v2 = d / "v2" / "journal.db"
        _make_v2_node(self.v2)
        self.agg = Aggregator(dict(self.paths))
        self.with_broken = Aggregator({**self.paths, "v2_wall": str(self.v2)})

    def tearDown(self):
        self._tmp.cleanup()

    def test_totals_union_across_nodes(self):
        stats = self.agg.read_stats(7, today=PINNED, scope="all")
        self.assertEqual(stats["totals"], {"reads": 5, "writes": 2, "ratio": 2.5})
        self.assertEqual(stats["by_tool"], {"search_text": 5, "log_entry": 2})
        self.assertEqual(
            stats["by_day"],
            [
                {"date": "2026-08-23", "reads": 0, "writes": 2},
                {"date": "2026-08-24", "reads": 5, "writes": 0},
            ],
        )

    def test_scope_narrowing(self):
        stats = self.agg.read_stats(7, today=PINNED, scope=["jrhood"])
        self.assertEqual(stats["totals"]["reads"], 0)
        self.assertEqual(stats["totals"]["writes"], 2)

    def test_a_broken_node_warns_and_the_healthy_meters_still_report(self):
        stats = self.with_broken.read_stats(7, today=PINNED, scope="all")
        self.assertEqual(stats["totals"]["reads"], 5)
        skipped = [w for w in stats["warnings"] if w["kind"] == "node_skipped"]
        self.assertEqual(skipped[0]["node"], "v2_wall")

    def test_a_node_with_no_meter_yet_warns_rather_than_raising(self):
        d = Path(self._tmp.name) / "fresh" / "journal.db"
        init_db(d, node_name="fresh")
        agg = Aggregator({**self.paths, "fresh": str(d)})
        stats = agg.read_stats(7, today=PINNED, scope="all")
        absent = [w for w in stats["warnings"] if w["kind"] == "meter_absent"]
        self.assertEqual(absent[0]["node"], "fresh")
        self.assertEqual(stats["totals"]["reads"], 5)


if __name__ == "__main__":
    unittest.main()
