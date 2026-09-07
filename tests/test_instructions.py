"""3.3.0 — the ``instructions`` surface, read heat, and ``ghosts`` (the 3.3.0 order, §2–§3).

Two of these tests are the order's machinery: every tool name must appear in the readme
(delete one and this file goes red), and ``by_id`` must write exactly one ``read_hit`` row
(remove the hook and it goes red). Both were shown red before they were shown green.
"""

import contextlib
import io
import json
import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path

from boonyard import __version__, init_db, latest_skill, log_entry, log_skill_revision, meter
from boonyard import instructions as instr
from boonyard.cli import main as cli_main
from boonyard.mcp import _TOOL_NAMES, TOOL_DEFS, MCPServer
from boonyard.views import ghosts


def _rpc(method, params=None, rid=1):
    return {"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}


def _call(server, name, args=None):
    resp = server.handle(_rpc("tools/call", {"name": name, "arguments": args or {}}))
    if "error" in resp:
        return None, resp["error"]
    return json.loads(resp["result"]["content"][0]["text"]), None


def _hits(meter_path):
    if not Path(meter_path).exists():
        return []
    conn = sqlite3.connect(meter_path)
    conn.row_factory = sqlite3.Row
    try:
        return [
            dict(r)
            for r in conn.execute("SELECT tool, node, entry_id FROM read_hit ORDER BY rowid")
        ]
    finally:
        conn.close()


class NodeCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.db = str(self.dir / "journal.db")
        self.meter = str(self.dir / "meter.db")
        init_db(self.db, node_name="test")
        self.server = MCPServer(db_path=self.db, meter_path=self.meter)

    def tearDown(self):
        self._tmp.cleanup()


# --------------------------------------------------------------------------
# §2 instructions
# --------------------------------------------------------------------------
class InstructionsTests(NodeCase):
    def test_every_tool_name_appears_in_the_readme(self):
        """THE MACHINERY TEST: a tool added without a readme line fails here."""
        text = instr.instructions_text()
        for name in sorted(_TOOL_NAMES):
            self.assertIn(name, text, f"tool {name!r} has no line in INSTRUCTIONS")
        self.assertEqual(len(TOOL_DEFS), 20)

    def test_readme_is_under_the_cap(self):
        text = instr.instructions_text()
        self.assertLessEqual(len(text.encode("utf-8")), instr.MAX_BYTES)
        self.assertIn(__version__, text)
        self.assertIn("search before you assert", text)
        self.assertIn("comma-separated string", text)
        self.assertIn("killdate:", text)
        self.assertIn("open-retired:", text)

    def test_initialize_carries_instructions(self):
        resp = self.server.handle(_rpc("initialize"))
        text = resp["result"]["instructions"]
        self.assertEqual(text, instr.instructions_text())
        self.assertLessEqual(len(text.encode("utf-8")), instr.MAX_BYTES)

    def test_instructions_tool_and_the_readme_slug(self):
        payload, err = _call(self.server, "instructions")
        self.assertIsNone(err)
        self.assertEqual(payload["package"], instr.instructions_text())
        self.assertEqual(payload["version"], __version__)
        self.assertIsNone(payload["readme"])
        info, _ = _call(self.server, "node_info")
        self.assertFalse(info["has_readme"])
        self.assertIsNone(info["readme_id"])
        # write the node's readme the way every skill is written
        log_skill_revision(
            "professor",
            "READ THIS FIRST: thread your replies.",
            slug="readme",
            tags="readme,instructions,agents",
            db_path=self.db,
        )
        payload, _ = _call(self.server, "instructions")
        self.assertEqual(payload["readme"]["id"], latest_skill("readme", db_path=self.db)["id"])
        self.assertIn("thread your replies", payload["readme"]["content"])
        info, _ = _call(self.server, "node_info")
        self.assertTrue(info["has_readme"])
        self.assertEqual(info["readme_id"], payload["readme"]["id"])
        # a second revision wins
        log_skill_revision(
            "professor",
            "READ THIS FIRST, v2.",
            root_id=payload["readme"]["id"],
            slug="readme",
            db_path=self.db,
        )
        payload2, _ = _call(self.server, "instructions")
        self.assertGreater(payload2["readme"]["id"], payload["readme"]["id"])

    def test_cli_prints_the_readme(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli_main(["instructions"])
        self.assertEqual(code, 0)
        self.assertEqual(out.getvalue(), instr.instructions_text())


# --------------------------------------------------------------------------
# §3 read heat: the hook
# --------------------------------------------------------------------------
class ReadHeatHookTests(NodeCase):
    def setUp(self):
        super().setUp()
        self.root = log_entry("code", "note", "root", db_path=self.db)
        self.child = log_entry("code", "note", "child", related_id=self.root, db_path=self.db)
        self.other = log_entry("code", "decision", "other", tags="x", db_path=self.db)

    def test_by_id_writes_exactly_one_hit(self):
        """THE HOOK TEST: remove ``_hits`` from ``_call_tool`` and this goes red."""
        _call(self.server, "by_id", {"entry_id": self.other})
        rows = _hits(self.meter)
        self.assertEqual([(r["tool"], r["entry_id"]) for r in rows], [("by_id", self.other)])
        self.assertEqual(rows[0]["node"], "test")

    def test_list_tags_writes_none(self):
        _call(self.server, "list_tags")
        _call(self.server, "list_agents")
        _call(self.server, "read_stats")
        _call(self.server, "node_info")
        self.assertEqual(_hits(self.meter), [])

    def test_get_thread_records_root_and_children(self):
        _call(self.server, "get_thread", {"root_id": self.root})
        self.assertEqual(sorted(r["entry_id"] for r in _hits(self.meter)), [self.root, self.child])

    def test_recent_and_search_record_what_they_returned(self):
        payload, _ = _call(self.server, "recent", {"limit": 2})
        self.assertEqual([r["entry_id"] for r in _hits(self.meter)], [e["id"] for e in payload])
        _call(self.server, "search_text", {"query": "other"})
        self.assertEqual(_hits(self.meter)[-1]["entry_id"], self.other)

    def test_a_write_records_nothing(self):
        _call(self.server, "log_entry", {"agent": "code", "entry_type": "note", "content": "w"})
        self.assertEqual(_hits(self.meter), [])
        # and the meter's own no-arguments contract is untouched
        conn = sqlite3.connect(self.meter)
        try:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM meter").fetchone()[0], 1)
        finally:
            conn.close()

    def test_a_broken_sidecar_never_breaks_the_read(self):
        server = MCPServer(db_path=self.db, meter_path=str(self.dir))  # a directory, not a file
        payload, err = _call(server, "by_id", {"entry_id": self.other})
        self.assertIsNone(err)
        self.assertEqual(payload["id"], self.other)


# --------------------------------------------------------------------------
# §3 meter functions
# --------------------------------------------------------------------------
class MeterHeatTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.meter = str(Path(self._tmp.name) / "meter.db")

    def tearDown(self):
        self._tmp.cleanup()

    def test_record_hits_writes_n_rows_and_none_for_empty(self):
        self.assertEqual(meter.record_hits(self.meter, "recent", node="n", entry_ids=[3, 2, 1]), 3)
        self.assertEqual(meter.record_hits(self.meter, "recent", node="n", entry_ids=[]), 0)
        self.assertEqual(meter.record_hits(None, "recent", node="n", entry_ids=[1]), 0)
        self.assertEqual(len(_hits(self.meter)), 3)

    def test_entry_heat_counts_and_narrows(self):
        meter.record_hits(
            self.meter, "recent", node="n", entry_ids=[1, 2], ts="2026-09-01T10:00:00"
        )
        meter.record_hits(self.meter, "by_id", node="n", entry_ids=[1], ts="2026-09-05T10:00:00")
        heat = meter.entry_heat(self.meter)
        self.assertEqual(heat[1], {"reads": 2, "last_read": "2026-09-05T10:00:00"})
        self.assertEqual(heat[2]["reads"], 1)
        self.assertEqual(set(meter.entry_heat(self.meter, entry_ids=[2])), {2})
        self.assertEqual(meter.entry_heat(self.meter, node="other"), {})
        self.assertEqual(meter.entry_heat(str(Path(self._tmp.name) / "absent.db")), {})

    def test_rollup_moves_exactly_the_old_rows(self):
        meter.record_hits(
            self.meter, "recent", node="n", entry_ids=[1, 1, 2], ts="2026-01-01T09:00:00"
        )
        meter.record_hits(self.meter, "recent", node="n", entry_ids=[1], ts="2026-09-06T09:00:00")
        result = meter.rollup(self.meter, 180, today=date(2026, 9, 7))
        self.assertEqual(result["moved"], 3)
        self.assertEqual(result["entries"], 2)
        self.assertEqual([r["entry_id"] for r in _hits(self.meter)], [1])  # the young row stays
        heat = meter.entry_heat(self.meter)
        self.assertEqual(heat[1]["reads"], 3)  # 2 rolled + 1 raw
        self.assertEqual(heat[1]["last_read"], "2026-09-06T09:00:00")
        self.assertEqual(heat[2], {"reads": 1, "last_read": "2026-01-01T09:00:00"})
        # a second rollup finds nothing to move and keeps the counts
        self.assertEqual(meter.rollup(self.meter, 180, today=date(2026, 9, 7))["moved"], 0)
        self.assertEqual(meter.entry_heat(self.meter)[1]["reads"], 3)


# --------------------------------------------------------------------------
# §3 ghosts
# --------------------------------------------------------------------------
class GhostsTests(NodeCase):
    def setUp(self):
        super().setUp()
        self.unread = log_entry(
            "code", "note", "an unthreaded, unread root\nsecond line", db_path=self.db
        )
        self.parent = log_entry("code", "note", "a root with a child", db_path=self.db)
        log_entry("code", "note", "the child", related_id=self.parent, db_path=self.db)
        self.read = log_entry("code", "note", "a root that was read", db_path=self.db)
        self.young = log_entry("code", "note", "too young to judge", db_path=self.db)
        self.meta = log_entry("system", "meta", "a retag receipt", db_path=self.db)
        # age everything but the young one (fixture-only surgery on a scratch node)
        conn = sqlite3.connect(self.db)
        try:
            conn.execute(
                "UPDATE entry SET timestamp = '2026-01-15 10:00:00' WHERE id != ?", (self.young,)
            )
            conn.commit()
        finally:
            conn.close()
        _call(self.server, "by_id", {"entry_id": self.read})  # read today

    def test_the_fixture(self):
        rows = ghosts(20, 30, db_path=self.db, meter_path=self.meter)
        ids = [g["id"] for g in rows]
        self.assertIn(self.unread, ids)
        self.assertNotIn(self.parent, ids, "a root with a child is not a ghost")
        self.assertNotIn(self.read, ids, "a root read inside the window is not a ghost")
        self.assertNotIn(self.young, ids, "a root younger than the window is not judged yet")
        self.assertNotIn(self.meta, ids, "meta rows are not ghosts")
        ghost = rows[0]
        self.assertEqual(ghost["first_line"], "an unthreaded, unread root")
        self.assertEqual(ghost["reads"], 0)
        self.assertIsNone(ghost["last_read"])
        self.assertIsInstance(ghost["tags"], list)  # the package auto-tags the entry type

    def test_limit_and_window(self):
        extra = log_entry("code", "note", "another old root", db_path=self.db)
        conn = sqlite3.connect(self.db)
        try:
            conn.execute(
                "UPDATE entry SET timestamp = '2026-02-01 10:00:00' WHERE id = ?", (extra,)
            )
            conn.commit()
        finally:
            conn.close()
        self.assertEqual(len(ghosts(1, 30, db_path=self.db, meter_path=self.meter)), 1)
        self.assertEqual(len(ghosts(20, 30, db_path=self.db, meter_path=self.meter)), 2)
        # a window of 0 days: the read root counts as unread again only if its read is older
        self.assertNotIn(
            self.read, [g["id"] for g in ghosts(20, 0, db_path=self.db, meter_path=self.meter)]
        )
        # an enormous window: nothing is old enough
        self.assertEqual(ghosts(20, 10_000, db_path=self.db, meter_path=self.meter), [])

    def test_tool_and_cli(self):
        payload, err = _call(self.server, "ghosts", {"limit": 5, "older_than_days": 30})
        self.assertIsNone(err)
        self.assertEqual([g["id"] for g in payload], [self.unread])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli_main(["--db", self.db, "ghosts", "--limit", "5", "--older-than-days", "30"])
        self.assertEqual(code, 0)
        self.assertIn(f"#{self.unread}", out.getvalue())
        self.assertIn("1 ghost(s)", out.getvalue())


class HelpTests(unittest.TestCase):
    def _exit(self, argv):
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                cli_main(argv)
        except SystemExit as exc:
            return int(exc.code or 0)
        return -1

    def test_new_commands_help_exit_zero(self):
        self.assertEqual(self._exit(["instructions", "--help"]), 0)
        self.assertEqual(self._exit(["ghosts", "--help"]), 0)
        self.assertEqual(self._exit(["meter", "rollup", "--help"]), 0)
        self.assertEqual(self._exit(["meter", "--help"]), 0)
