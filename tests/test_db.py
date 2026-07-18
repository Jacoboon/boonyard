"""M1 tests — schema init, idempotency, FTS trigger, meta bootstrap (arch 02)."""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from boonyard import connect, init_db
from boonyard.constants import SCHEMA_VERSION
from boonyard.db import schema_version


def _mem() -> sqlite3.Connection:
    """A persistent in-memory connection initialized as a v3 node."""
    conn = sqlite3.connect(":memory:")
    init_db(conn=conn)
    return conn


class InitSchemaTests(unittest.TestCase):
    def test_core_objects_created(self):
        conn = _mem()
        names = {
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")
        }
        for expected in ("entry", "entry_fts", "entry_tag", "meta", "meta_log"):
            self.assertIn(expected, names)

    def test_entry_column_set_is_the_closed_eight(self):
        # ADR-0002: the column set is closed. Guard it so an accidental eighth
        # (or missing) column fails loudly.
        conn = _mem()
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(entry)")]
        self.assertEqual(
            cols,
            ["id", "timestamp", "agent", "entry_type", "content", "related_id", "tags", "extras"],
        )

    def test_meta_bootstrap_rows_present(self):
        conn = _mem()
        meta = {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM meta")}
        self.assertEqual(meta["schema_version"], str(SCHEMA_VERSION))
        self.assertIsNotNone(meta.get("node_uuid"))
        self.assertNotEqual(meta.get("node_uuid"), "")
        self.assertIsNotNone(meta.get("created_at"))
        self.assertEqual(schema_version(conn), SCHEMA_VERSION)

    def test_node_name_recorded_when_given(self):
        conn = sqlite3.connect(":memory:")
        init_db(conn=conn, node_name="boonyard")
        row = conn.execute("SELECT value FROM meta WHERE key = 'node_name'").fetchone()
        self.assertEqual(row["value"], "boonyard")

    def test_node_name_absent_when_not_given(self):
        conn = _mem()
        row = conn.execute("SELECT value FROM meta WHERE key = 'node_name'").fetchone()
        self.assertIsNone(row)  # placeholder was skipped by OR IGNORE; never populated

    def test_reinit_is_idempotent_and_preserves_identity(self):
        conn = _mem()
        uuid_before = conn.execute("SELECT value FROM meta WHERE key = 'node_uuid'").fetchone()[
            "value"
        ]
        init_db(conn=conn)  # re-init must not raise or change identity
        init_db(conn=conn)
        uuid_after = conn.execute("SELECT value FROM meta WHERE key = 'node_uuid'").fetchone()[
            "value"
        ]
        self.assertEqual(uuid_before, uuid_after)

    def test_init_requires_a_target(self):
        with self.assertRaises(ValueError):
            init_db()


class FtsTriggerTests(unittest.TestCase):
    def test_insert_is_searchable_via_fts(self):
        conn = _mem()
        conn.execute(
            "INSERT INTO entry (agent, entry_type, content) VALUES (?, ?, ?)",
            ("code", "note", "the quick brown fox jumps"),
        )
        hits = conn.execute(
            "SELECT e.content FROM entry e JOIN entry_fts f ON f.rowid = e.id "
            "WHERE entry_fts MATCH ?",
            ("brown",),
        ).fetchall()
        self.assertEqual(len(hits), 1)
        self.assertIn("brown", hits[0]["content"])

    def test_fts_delete_trigger_keeps_index_consistent(self):
        # ADR-0005 says DELETE should never fire in practice, but the trigger must
        # keep FTS consistent if it ever does — verify it here.
        conn = _mem()
        conn.execute(
            "INSERT INTO entry (agent, entry_type, content) VALUES ('code','note','ephemeral row')"
        )
        conn.execute("DELETE FROM entry WHERE content = 'ephemeral row'")
        hits = conn.execute(
            "SELECT rowid FROM entry_fts WHERE entry_fts MATCH 'ephemeral'"
        ).fetchall()
        self.assertEqual(hits, [])


class ConnectTests(unittest.TestCase):
    def test_on_disk_init_creates_file_and_is_readable(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "nested" / "journal.db"
            init_db(path)  # parent dir is created
            self.assertTrue(path.exists())
            with connect(path) as conn:
                self.assertEqual(schema_version(conn), SCHEMA_VERSION)

    def test_read_only_connection_cannot_write(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "journal.db"
            init_db(path)
            with self.assertRaises(sqlite3.OperationalError):
                with connect(path, read_only=True) as conn:
                    conn.execute(
                        "INSERT INTO entry (agent, entry_type, content) "
                        "VALUES ('code','note','nope')"
                    )

    def test_connect_rolls_back_on_exception(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "journal.db"
            init_db(path)
            with self.assertRaises(RuntimeError):
                with connect(path) as conn:
                    conn.execute(
                        "INSERT INTO entry (agent, entry_type, content) "
                        "VALUES ('code','note','doomed')"
                    )
                    raise RuntimeError("boom")
            with connect(path) as conn:
                n = conn.execute("SELECT COUNT(*) AS n FROM entry").fetchone()["n"]
            self.assertEqual(n, 0)


if __name__ == "__main__":
    unittest.main()
