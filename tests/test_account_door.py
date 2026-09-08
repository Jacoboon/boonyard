"""ADR-0014 — the account door: one server, several named nodes, writes routed by name.

The most important assertion in this file is :meth:`TwoModesTests.test_the_two_modes_differ`.
``MCPServer``'s read-only state used to be derived as ``aggregator is not None``, and that
one expression was the entire protection on the ``_aggregate`` endpoint. ``nodes`` mode
holds an aggregator AND permits writes, so a careless refactor makes ``_aggregate``
silently writable — nothing looks wrong, no test fails, and a read-only promise quietly
stops being true. That test is what makes the difference checkable.

To see it fail on purpose (the order's Acceptance 2), flip the explicit state in
``mcp.MCPServer.__init__``::

    self._read_only = False          # instead of: self._mode == "aggregator"

and run this file: ``test_aggregator_mode_refuses_a_write`` and
``test_the_two_modes_differ`` both go red.
"""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from boonyard import init_db, log_entry
from boonyard.aggregator import aggregator
from boonyard.mcp import TOOL_DEFS, MCPServer, account_tool_defs


def _call(server, tool, **args):
    """One tools/call; returns the parsed payload or raises AssertionError with the error."""
    resp = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool, "arguments": args},
        }
    )
    if "error" in resp:
        raise AssertionError(f"unexpected error: {resp['error']}")
    return json.loads(resp["result"]["content"][0]["text"])


def _error(server, tool, **args):
    """One tools/call expected to fail; returns the error object."""
    resp = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool, "arguments": args},
        }
    )
    assert "error" in resp, f"expected an error, got {resp.get('result')}"
    return resp["error"]


def _count(db: Path) -> int:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return conn.execute("SELECT COUNT(*) FROM entry").fetchone()[0]
    finally:
        conn.close()


class NodeMapCase(unittest.TestCase):
    """Two real nodes on disk, plus the meter the account door requires."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.nodes = {}
        for slug, entries in (("alpha", 2), ("beta", 3)):
            node_dir = self.root / slug
            node_dir.mkdir()
            db = node_dir / "journal.db"
            init_db(db, node_name=slug)
            for i in range(entries):
                log_entry("system", "note", f"{slug} entry {i}", tags="test", db_path=db)
            self.nodes[slug] = str(db)
        # alpha carries a profile; beta does not. The account door must honour each
        # node's own boonyard.toml, exactly as that node's own door would.
        (self.root / "alpha" / "boonyard.toml").write_text(
            '[node]\nname = "alpha"\n\n[tags.namespaces]\nlane = "alpha\'s own namespace"\n',
            encoding="utf-8",
        )
        self.meter = self.root / "meter.db"

    def account(self, **kwargs):
        return MCPServer(nodes=self.nodes, meter_path=self.meter, **kwargs)

    def aggregate(self, **kwargs):
        return MCPServer(aggregator=aggregator(nodes=self.nodes), meter_path=self.meter, **kwargs)


# ---------------------------------------------------------------------------
# construction
# ---------------------------------------------------------------------------
class ConstructionTests(NodeMapCase):
    def test_exactly_one_source_and_the_error_names_all_three(self):
        for kwargs in (
            {},
            {"db_path": self.nodes["alpha"], "nodes": self.nodes},
            {"db_path": self.nodes["alpha"], "aggregator": aggregator(nodes=self.nodes)},
            {"nodes": self.nodes, "aggregator": aggregator(nodes=self.nodes)},
        ):
            with self.assertRaises(ValueError) as caught:
                MCPServer(meter_path=self.meter, **kwargs)
            message = str(caught.exception)
            for name in ("db_path", "aggregator", "nodes"):
                self.assertIn(name, message)

    def test_nodes_mode_refuses_to_run_unmetered(self):
        """An endpoint whose meter is a silent no-op is this stack's recurring sin."""
        with self.assertRaises(ValueError) as caught:
            MCPServer(nodes=self.nodes)
        self.assertIn("meter_path", str(caught.exception))

    def test_single_node_mode_is_unchanged(self):
        server = MCPServer(db_path=self.nodes["alpha"])
        self.assertFalse(server._read_only)
        self.assertEqual(server._mode, "single")


# ---------------------------------------------------------------------------
# THE POINT OF THE ORDER
# ---------------------------------------------------------------------------
class TwoModesTests(NodeMapCase):
    def test_aggregator_mode_refuses_a_write(self):
        error = _error(self.aggregate(), "log_entry", agent="code", entry_type="note", content="x")
        self.assertEqual(error["code"], -32006)
        self.assertIn("read-only", error["message"])

    def test_the_two_modes_differ(self):
        """SAME node map. One construction refuses the write, the other accepts it."""
        before = _count(Path(self.nodes["alpha"]))

        refused = _error(
            self.aggregate(), "log_entry", agent="code", entry_type="note", content="x"
        )
        self.assertEqual(refused["data"]["error"], "read_only")
        self.assertEqual(_count(Path(self.nodes["alpha"])), before, "the refusal still wrote")

        landed = _call(
            self.account(),
            "log_entry",
            agent="code",
            entry_type="note",
            content="x",
            node="alpha",
        )
        self.assertIsInstance(landed["id"], int)
        self.assertEqual(_count(Path(self.nodes["alpha"])), before + 1)

    def test_read_only_is_not_derived_from_holding_an_aggregator(self):
        """Both modes hold one; only aggregator mode is read-only."""
        self.assertIsNotNone(self.account()._agg)
        self.assertIsNotNone(self.aggregate()._agg)
        self.assertFalse(self.account()._read_only)
        self.assertTrue(self.aggregate()._read_only)


# ---------------------------------------------------------------------------
# writes name their node
# ---------------------------------------------------------------------------
class WriteRoutingTests(NodeMapCase):
    def test_a_write_lands_in_the_named_node_and_nowhere_else(self):
        before = {s: _count(Path(p)) for s, p in self.nodes.items()}
        _call(
            self.account(),
            "log_entry",
            agent="code",
            entry_type="note",
            content="for beta only",
            node="beta",
        )
        self.assertEqual(_count(Path(self.nodes["beta"])), before["beta"] + 1)
        self.assertEqual(
            _count(Path(self.nodes["alpha"])), before["alpha"], "the write leaked into another node"
        )

    def test_a_write_with_no_node_is_a_missing_parameter(self):
        error = _error(self.account(), "log_entry", agent="code", entry_type="note", content="x")
        self.assertEqual(error["code"], -32602)
        self.assertIn("'node'", error["message"])

    def test_an_unknown_node_names_the_ones_that_exist(self):
        """A model that guessed wrong must be able to fix itself in one turn."""
        error = _error(
            self.account(), "log_entry", agent="code", entry_type="note", content="x", node="nope"
        )
        self.assertEqual(error["code"], -32602)
        self.assertIn("alpha", error["message"])
        self.assertIn("beta", error["message"])
        self.assertIn("list_nodes", error["data"]["hint"])

    def test_skill_revisions_route_the_same_way(self):
        payload = _call(
            self.account(),
            "log_skill_revision",
            slug="readme",
            content="beta's readme",
            agent="code",
            node="beta",
        )
        self.assertIsInstance(payload["id"], int)
        latest = _call(self.account(), "latest_skill", slug="readme", scope="beta")
        self.assertEqual(latest["content"], "beta's readme")
        self.assertIsNone(_call(self.account(), "latest_skill", slug="readme", scope="alpha"))


# ---------------------------------------------------------------------------
# the tool surface differs per door
# ---------------------------------------------------------------------------
class ToolSurfaceTests(NodeMapCase):
    def _defs(self, server):
        resp = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        return {t["name"]: t["inputSchema"] for t in resp["result"]["tools"]}

    def test_node_is_required_on_writes_at_the_account_door(self):
        schemas = self._defs(self.account())
        for tool in ("log_entry", "log_skill_revision"):
            self.assertIn("node", schemas[tool]["required"], tool)
            self.assertIn("node", schemas[tool]["properties"], tool)

    def test_node_is_absent_at_the_per_node_door(self):
        schemas = self._defs(MCPServer(db_path=self.nodes["alpha"]))
        for tool in ("log_entry", "log_skill_revision"):
            self.assertNotIn("node", schemas[tool]["required"], tool)
            self.assertNotIn("node", schemas[tool]["properties"], tool)

    def test_both_doors_carry_the_same_twenty_tools(self):
        self.assertEqual(set(self._defs(self.account())), set(self._defs(self.aggregate())))
        self.assertEqual(len(self._defs(self.account())), len(TOOL_DEFS))

    def test_account_tool_defs_are_derived_not_retyped(self):
        derived = {t["name"]: t for t in account_tool_defs()}
        for original in TOOL_DEFS:
            got = derived[original["name"]]
            self.assertEqual(got["description"], original["description"])
            if original["name"] not in ("log_entry", "log_skill_revision"):
                self.assertEqual(got, original)

    def test_deriving_does_not_mutate_the_module_default(self):
        account_tool_defs()
        for tool in TOOL_DEFS:
            self.assertNotIn("node", tool["inputSchema"]["required"])


# ---------------------------------------------------------------------------
# reads span, scope narrows
# ---------------------------------------------------------------------------
class ReadTests(NodeMapCase):
    def test_recent_spans_every_node_and_every_row_names_its_source(self):
        rows = _call(self.account(), "recent", limit=20)
        self.assertEqual({r["source"] for r in rows}, {"alpha", "beta"})
        self.assertEqual(len(rows), 5)

    def test_scope_narrows_to_one_node(self):
        rows = _call(self.account(), "recent", limit=20, scope="beta")
        self.assertEqual(len(rows), 3)
        self.assertTrue(all("beta" in r["content"] for r in rows))

    def test_list_nodes_returns_every_node(self):
        rows = _call(self.account(), "list_nodes")
        self.assertEqual({r["name"] for r in rows}, {"alpha", "beta"})

    def test_node_info_serves_the_named_node_and_its_own_profile(self):
        info = _call(self.account(), "node_info", scope="alpha")
        self.assertEqual(info["name"], "alpha")
        self.assertIn("lane", info["profile"]["namespaces"])
        beta = _call(self.account(), "node_info", scope="beta")
        self.assertEqual(beta["name"], "beta")
        self.assertNotIn("lane", beta["profile"]["namespaces"])

    def test_node_info_unnamed_keeps_the_aggregator_answer(self):
        error = _error(self.account(), "node_info")
        self.assertIn("aggregator endpoint", error["message"])

    def test_instructions_named_carries_that_node_readme(self):
        _call(
            self.account(),
            "log_skill_revision",
            slug="readme",
            content="alpha's readme",
            agent="code",
            node="alpha",
        )
        named = _call(self.account(), "instructions", scope="alpha")
        self.assertEqual(named["readme"]["content"], "alpha's readme")
        spanning = _call(self.account(), "instructions")
        self.assertIsNone(spanning["readme"])
        self.assertIn("aggregator endpoint", spanning["note"])


# ---------------------------------------------------------------------------
# the meter
# ---------------------------------------------------------------------------
class MeterTests(NodeMapCase):
    """Where a fact is recorded matters as much as whether it is.

    Per-node facts belong in that node's own ``meter.db``. Entry ids are per node —
    alpha's #5 and beta's #5 are different entries — and ``views.ghosts`` looks read
    heat up by entry id with no node filter, so pooling several nodes' heat in one
    file would let one node's reads mark another node's entries as read.
    """

    def _rows(self, meter_path, table="meter"):
        if not Path(meter_path).exists():
            return []
        conn = sqlite3.connect(f"file:{meter_path}?mode=ro", uri=True)
        try:
            sql = (
                "SELECT tool, node, kind FROM meter"
                if table == "meter"
                else "SELECT tool, node, entry_id FROM read_hit"
            )
            return conn.execute(sql).fetchall()
        finally:
            conn.close()

    def _node_meter(self, slug):
        return Path(self.nodes[slug]).parent / "meter.db"

    def test_a_write_is_metered_in_the_node_it_addressed(self):
        _call(
            self.account(), "log_entry", agent="code", entry_type="note", content="x", node="beta"
        )
        self.assertEqual(
            [r for r in self._rows(self._node_meter("beta")) if r[0] == "log_entry"],
            [("log_entry", "beta", "write")],
        )
        self.assertEqual([r for r in self._rows(self.meter) if r[0] == "log_entry"], [])
        self.assertEqual(self._rows(self._node_meter("alpha")), [])

    def test_a_spanning_read_meters_on_the_account_and_heats_each_node(self):
        _call(self.account(), "recent", limit=20)
        self.assertIn(("recent", "all", "read"), self._rows(self.meter))
        for slug in ("alpha", "beta"):
            heat = self._rows(self._node_meter(slug), "read_hit")
            self.assertTrue(heat, f"{slug} recorded no read heat")
            self.assertEqual({r[1] for r in heat}, {slug})
        self.assertEqual(self._rows(self.meter, "read_hit"), [], "heat pooled on the account")

    def test_one_nodes_reads_never_heat_another_nodes_entries(self):
        """The collision this rule exists for: both nodes have an entry #1."""
        _call(self.account(), "by_id", entry_id=1, scope="beta")
        beta_heat = self._rows(self._node_meter("beta"), "read_hit")
        self.assertEqual([(r[1], r[2]) for r in beta_heat], [("beta", 1)])
        self.assertEqual(self._rows(self._node_meter("alpha"), "read_hit"), [])

    def test_read_stats_at_the_account_door_reads_that_nodes_meter(self):
        _call(
            self.account(), "log_entry", agent="code", entry_type="note", content="x", node="beta"
        )
        stats = _call(self.account(), "read_stats", scope="beta")
        self.assertEqual(stats["totals"]["writes"], 1)
        self.assertEqual(_call(self.account(), "read_stats", scope="alpha")["totals"]["writes"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
