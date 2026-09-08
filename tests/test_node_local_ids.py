"""ADR-0014 §11 — name the node wherever the argument is node-local.

THE FIXTURE IS THE POINT OF THIS FILE. Two nodes with **hyphenated slugs** (every real
ADR-0008 slug has a hyphen; forty-four green tests once sailed past a bug that rejected
them because the fixtures were all ``alpha``/``beta``) and **deliberately colliding
ids**: each node holds ``#1`` and ``#2``, and ``#2`` is threaded to ``#1`` in one node
only. A fixture that cannot fail the way production fails is not a fixture, it is a
decoration (umbrella #403).

To see the red these were written against, stash the package and run this file:

    git stash push -- package/boonyard && python -m unittest tests.test_node_local_ids
    git stash pop
"""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from boonyard import init_db, log_entry
from boonyard.aggregator import aggregator
from boonyard.mcp import TOOL_DEFS, MCPError, MCPServer

# The class sets are looked up lazily, inside the tests that need them, so this file
# still LOADS against a build that predates §11 — otherwise the red run is an import
# error, which proves nothing. The fallbacks are §11's table, stated here as the
# specification these tests were written against.
_EXPECTED_NODE_LOCAL = frozenset({"by_id", "get_thread", "latest_skill"})
_EXPECTED_PER_NODE = frozenset({"node_info", "list_skills", "audit_doctor", "ghosts"})


def _sets():
    from boonyard import mcp

    return (
        getattr(mcp, "_NODE_LOCAL_TOOLS", _EXPECTED_NODE_LOCAL),
        getattr(mcp, "_PER_NODE_TOOLS", _EXPECTED_PER_NODE),
        getattr(mcp, "_AGGREGATOR_TOOLS", frozenset()),
    )


PINNED = "2026-09-07"


def _call(server, tool, **args):
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


class CollidingIdsCase(unittest.TestCase):
    """`mycelium-sky` and `tea-guru`, each holding #1 and #2. Threaded in tea-guru only."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.nodes = {}
        for slug in ("mycelium-sky", "tea-guru"):
            db = self.root / slug / "journal.db"
            init_db(db, node_name=slug)
            log_entry("system", "note", f"{slug} root", tags="test", db_path=db)
            self.nodes[slug] = str(db)
        # tea-guru's #2 is a CHILD of its #1; mycelium-sky's #2 is a second root, and a
        # dated one, so the register has something to return.
        log_entry("system", "note", "tea-guru child", related_id=1, db_path=self.nodes["tea-guru"])
        log_entry(
            "system",
            "note",
            "mycelium-sky second root",
            tags=f"open:{PINNED}",
            db_path=self.nodes["mycelium-sky"],
        )
        self.meter = self.root / "account-meter.db"

    def account(self):
        return MCPServer(nodes=self.nodes, meter_path=self.meter)

    def aggregate(self):
        return MCPServer(aggregator=aggregator(nodes=self.nodes), meter_path=self.meter)

    def single(self, slug="tea-guru"):
        return MCPServer(db_path=self.nodes[slug])

    def node_meter(self, slug):
        return Path(self.nodes[slug]).parent / "meter.db"

    def heat_rows(self, slug):
        path = self.node_meter(slug)
        if not path.exists():
            return []
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            return conn.execute("SELECT tool, node, entry_id FROM read_hit").fetchall()
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# 1 + 2 + 3 — the union is unreachable, and a typo cannot span
# ---------------------------------------------------------------------------
class NodeLocalArgumentTests(CollidingIdsCase):
    def test_get_thread_cannot_return_two_nodes_at_the_account_door(self):
        """RED before §11: three rows, two nodes, TWO UNRELATED ROOTS in one 'thread'."""
        error = _error(self.account(), "get_thread", root_id=1)
        self.assertIn("missing required parameter 'node'", error["message"])

        rows = _call(self.account(), "get_thread", root_id=1, node="tea-guru")
        self.assertEqual({r["source"] for r in rows}, {"tea-guru"})
        self.assertEqual([r["id"] for r in rows], [1, 2])
        self.assertEqual(sum(1 for r in rows if r["related_id"] is None), 1, "two roots")

    def test_get_thread_cannot_return_two_nodes_at_the_aggregate_door(self):
        error = _error(self.aggregate(), "get_thread", root_id=1)
        self.assertIn("missing required parameter 'node'", error["message"])
        rows = _call(self.aggregate(), "get_thread", root_id=1, node="mycelium-sky")
        self.assertEqual({r["source"] for r in rows}, {"mycelium-sky"})
        self.assertEqual(len(rows), 1, "mycelium-sky's #1 has no children")

    def test_by_id_with_no_node_is_refused_at_both_doors(self):
        for server in (self.account(), self.aggregate()):
            error = _error(server, "by_id", entry_id=1)
            self.assertIn("missing required parameter 'node'", error["message"])

    def test_by_id_names_a_different_entry_per_node(self):
        for door in (self.account(), self.aggregate()):
            mycelium = _call(door, "by_id", entry_id=1, node="mycelium-sky")
            tea = _call(door, "by_id", entry_id=1, node="tea-guru")
            self.assertEqual(mycelium["content"], "mycelium-sky root")
            self.assertEqual(tea["content"], "tea-guru root")
            self.assertEqual(mycelium["source"], "mycelium-sky")
            self.assertEqual(tea["source"], "tea-guru")

    def test_a_typo_raises_and_names_the_reachable_slugs(self):
        """RED before §11: an unrecognised node fell through to the union and returned
        a plausible row from the wrong wall. Requiring the argument does not fix that."""
        for door in (self.account(), self.aggregate()):
            error = _error(door, "by_id", entry_id=1, node="mycelim-sky")
            self.assertEqual(error["data"]["error"], "validation")
            self.assertIn("unknown node 'mycelim-sky'", error["message"])
            self.assertIn("mycelium-sky", error["message"])
            self.assertIn("tea-guru", error["message"])

    def test_a_typo_on_a_write_raises_the_same_error(self):
        error = _error(
            self.account(),
            "log_entry",
            agent="code",
            entry_type="note",
            content="x",
            node="tea-gru",
        )
        self.assertIn("unknown node 'tea-gru'", error["message"])
        self.assertIn("tea-guru", error["message"])

    def test_latest_skill_requires_a_node_at_the_account_door(self):
        _call(
            self.account(),
            "log_skill_revision",
            slug="readme",
            content="tea-guru's readme",
            agent="code",
            node="tea-guru",
        )
        error = _error(self.account(), "latest_skill", slug="readme")
        self.assertIn("missing required parameter 'node'", error["message"])
        found = _call(self.account(), "latest_skill", slug="readme", node="tea-guru")
        self.assertEqual(found["content"], "tea-guru's readme")
        self.assertEqual(found["source"], "tea-guru")
        self.assertIsNone(_call(self.account(), "latest_skill", slug="readme", node="mycelium-sky"))


# ---------------------------------------------------------------------------
# 4 — one key name for "which node", and the read heat that rides on it
# ---------------------------------------------------------------------------
class DatedRowKeyTests(CollidingIdsCase):
    def test_dated_rows_carry_source_at_every_door(self):
        for door, expected in (
            (self.account(), "mycelium-sky"),
            (self.aggregate(), "mycelium-sky"),
        ):
            payload = _call(door, "upcoming_dates", prefix="open", today=PINNED)
            row = payload["dates"][0]
            self.assertNotIn("node", row, "the old key survived")
            self.assertEqual(row["source"], expected)
            self.assertEqual(row["entry_id"], 2)

    def test_a_single_node_door_keeps_the_label_under_the_same_key(self):
        payload = _call(self.single("mycelium-sky"), "upcoming_dates", prefix="open", today=PINNED)
        self.assertEqual(payload["dates"][0]["source"], "mycelium-sky")

    def test_dated_read_heat_lands_on_the_right_nodes_meter(self):
        """The silent one: _returned_ids read the very key that was renamed, so heat
        would have attributed to None forever with no symptom and ghosts would rot."""
        _call(self.account(), "upcoming_dates", prefix="open", today=PINNED)
        rows = self.heat_rows("mycelium-sky")
        self.assertIn(("upcoming_dates", "mycelium-sky", 2), rows)
        self.assertEqual(self.heat_rows("tea-guru"), [])


# ---------------------------------------------------------------------------
# 5 — provenance, write receipts included
# ---------------------------------------------------------------------------
class ProvenanceTests(CollidingIdsCase):
    def test_a_node_named_read_names_its_node(self):
        rows = _call(self.account(), "recent", limit=10, scope="tea-guru")
        self.assertEqual({r["source"] for r in rows}, {"tea-guru"})

    def test_a_write_receipt_carries_the_slug(self):
        """A bare {"id": 412} from a door serving six walls cannot be cited."""
        receipt = _call(
            self.account(),
            "log_entry",
            agent="code",
            entry_type="note",
            content="x",
            node="tea-guru",
        )
        self.assertEqual(receipt["source"], "tea-guru")
        self.assertIsInstance(receipt["id"], int)

    def test_per_node_payloads_carry_the_slug(self):
        account = self.account()
        self.assertEqual(_call(account, "node_info", node="tea-guru")["source"], "tea-guru")
        self.assertEqual(_call(account, "audit_doctor", node="tea-guru")["source"], "tea-guru")
        self.assertEqual(
            _call(account, "ghosts", node="mycelium-sky"),
            [],
            "nothing is a ghost on the day it was written",
        )

        _call(
            account, "log_skill_revision", slug="readme", content="r", agent="code", node="tea-guru"
        )
        catalogue = _call(account, "list_skills", node="tea-guru")
        self.assertEqual(catalogue[0]["source"], "tea-guru")
        self.assertEqual(catalogue[0]["latest"]["source"], "tea-guru", "nested rows too")

        instructions = _call(account, "instructions", node="tea-guru")
        self.assertEqual(instructions["source"], "tea-guru")
        self.assertEqual(instructions["readme"]["source"], "tea-guru")

    def test_a_spanning_read_still_names_each_row(self):
        rows = _call(self.account(), "recent", limit=10)
        self.assertEqual({r["source"] for r in rows}, {"mycelium-sky", "tea-guru"})


# ---------------------------------------------------------------------------
# 6 — a door advertises only what it can serve, and the set cannot drift
# ---------------------------------------------------------------------------
class DoorSurfaceTests(CollidingIdsCase):
    def _names(self, server):
        return {
            t["name"]
            for t in server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"][
                "tools"
            ]
        }

    def test_the_aggregate_door_drops_the_five_it_cannot_serve(self):
        names = self._names(self.aggregate())
        self.assertEqual(len(names), 15)
        _node_local, per_node, _agg = _sets()
        for gone in per_node | {"latest_skill"}:
            self.assertNotIn(gone, names, gone)

    def test_the_two_writes_stay_listed_and_keep_refusing(self):
        """Deliberate asymmetry: that refusal is ADR-0008's teaching surface."""
        names = self._names(self.aggregate())
        self.assertIn("log_entry", names)
        error = _error(
            self.aggregate(),
            "log_entry",
            agent="code",
            entry_type="note",
            content="x",
            node="tea-guru",
        )
        self.assertEqual(error["code"], -32006)
        self.assertIn("read-only", error["message"])

    def test_aggregator_tools_set_matches_what_the_method_dispatches(self):
        """ANTI-DRIFT, driven through the real method: a tool added to _call_aggregator
        and not to the set (or the reverse) fails here rather than in production."""
        server = self.aggregate()
        minimal = {
            "by_id": {"entry_id": 1, "node": "tea-guru"},
            "get_thread": {"root_id": 1, "node": "tea-guru"},
            "latest_skill": {"slug": "readme", "node": "tea-guru"},
            "search_by_tag": {"tag": "test"},
            "search_by_tag_exact": {"tag": "test"},
            "search_text": {"query": "root"},
            "log_entry": {"agent": "a", "entry_type": "note", "content": "c"},
            "log_skill_revision": {"slug": "s", "content": "c", "agent": "a"},
        }
        served = set()
        for tool in TOOL_DEFS:
            name = tool["name"]
            try:
                server._call_aggregator(name, dict(minimal.get(name, {})))
                served.add(name)
            except MCPError as exc:
                if "not available on the aggregator endpoint" not in exc.message:
                    served.add(name)  # it dispatched and objected to something else
        _node_local, _per_node, aggregator_tools = _sets()
        self.assertEqual(served, set(aggregator_tools))

    def test_the_readme_lists_exactly_what_the_door_serves(self):
        """§11 applies to the text a model reads, not only to tools/list.

        A readme built from the module default would teach `ghosts` and `node_info` at
        a door that refuses them — a listing that sends the model straight to an error.
        """
        import re

        for server in (self.account(), self.aggregate(), self.single()):
            served = {
                t["name"]
                for t in server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})[
                    "result"
                ]["tools"]
            }
            readme = server.handle(
                {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
            )["result"]["instructions"]
            listed = set(re.findall(r"^  ([a-z_]+) — ", readme, re.M))
            self.assertEqual(listed, served, f"{server._mode} door")

    def test_the_instructions_tool_returns_the_same_per_door_text(self):
        aggregate = self.aggregate()
        payload = _call(aggregate, "instructions")
        self.assertNotIn("  ghosts — ", payload["package"])
        self.assertIn("  recent — ", payload["package"])
        self.assertIsNone(payload["readme"])

    def test_every_node_local_tool_is_advertised_as_requiring_node(self):
        for server in (self.account(), self.aggregate()):
            advertised = {
                t["name"]: t["inputSchema"]["required"]
                for t in server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})[
                    "result"
                ]["tools"]
            }
            node_local, _per_node, _agg = _sets()
            for name in node_local & set(advertised):
                self.assertIn("node", advertised[name], f"{name} at {server._mode}")


# ---------------------------------------------------------------------------
# 7 — THE REGRESSION FENCE: single-node doors are untouched
# ---------------------------------------------------------------------------
class SingleNodeDoorIsUntouchedTests(CollidingIdsCase):
    def test_tools_list_is_byte_identical_to_the_module_default(self):
        served = self.single().handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})[
            "result"
        ]["tools"]
        self.assertEqual(served, TOOL_DEFS)

    def test_no_node_argument_is_advertised_anywhere(self):
        for tool in self.single().handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})[
            "result"
        ]["tools"]:
            self.assertNotIn("node", tool["inputSchema"]["properties"], tool["name"])
            self.assertNotIn("node", tool["inputSchema"]["required"], tool["name"])

    def test_no_payload_gains_a_source(self):
        door = self.single()
        self.assertNotIn("source", _call(door, "by_id", entry_id=1))
        self.assertNotIn("source", _call(door, "node_info"))
        self.assertNotIn(
            "source",
            _call(door, "log_entry", agent="code", entry_type="note", content="x"),
        )
        for row in _call(door, "recent", limit=10):
            self.assertNotIn("source", row)

    def test_a_bare_id_still_works_because_there_is_only_one_node(self):
        self.assertEqual(_call(self.single(), "by_id", entry_id=1)["content"], "tea-guru root")
        rows = _call(self.single(), "get_thread", root_id=1)
        self.assertEqual([r["id"] for r in rows], [1, 2])


if __name__ == "__main__":
    unittest.main(verbosity=2)
