"""M2 tests — the audited tags-only mutation (ADR-0005's sole exception)."""

import json
import sqlite3
import unittest

from boonyard import init_db, log_entry, retag_entry


def _node() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    init_db(conn=conn)
    return conn


class RetagTests(unittest.TestCase):
    def test_changes_tags_and_entry_tag_rows(self):
        conn = _node()
        eid = log_entry("code", "discussion", "x", tags="personalities", conn=conn)
        retag_entry(eid, "personality", reason="merge plural drift", actor="cowork", conn=conn)
        tags = conn.execute("SELECT tags FROM entry WHERE id = ?", (eid,)).fetchone()["tags"]
        self.assertIn("personality", tags.split(","))
        self.assertNotIn("personalities", tags.split(","))
        et = {
            r["tag"] for r in conn.execute("SELECT tag FROM entry_tag WHERE entry_id = ?", (eid,))
        }
        self.assertIn("personality", et)
        self.assertNotIn("personalities", et)

    def test_meta_log_audit_row_written(self):
        conn = _node()
        eid = log_entry("code", "note", "x", tags="old", conn=conn)
        ml_id = retag_entry(eid, "new", reason="because", actor="code", conn=conn)
        row = conn.execute("SELECT * FROM meta_log WHERE id = ?", (ml_id,)).fetchone()
        self.assertEqual(row["op"], "retag")
        self.assertEqual(row["entry_id"], eid)
        self.assertEqual(row["actor"], "code")
        payload = json.loads(row["payload"])
        self.assertEqual(payload["reason"], "because")
        self.assertIn("old", payload["before"])
        self.assertIn("new", payload["after"])

    def test_type_tag_preserved_even_if_dropped(self):
        conn = _node()
        eid = log_entry("code", "decision", "x", tags="alpha", conn=conn)
        # new_tags omits the mandated 'decision' type tag; it must be re-added.
        retag_entry(eid, "beta", reason="rework", actor="code", conn=conn)
        tags = conn.execute("SELECT tags FROM entry WHERE id = ?", (eid,)).fetchone()["tags"]
        self.assertIn("decision", tags.split(","))

    def test_content_and_attribution_untouched(self):
        conn = _node()
        root = log_entry("code", "discussion", "root", conn=conn)
        eid = log_entry("opus", "decision", "body", related_id=root, tags="a", conn=conn)
        before = conn.execute("SELECT * FROM entry WHERE id = ?", (eid,)).fetchone()
        retag_entry(eid, "b", reason="r", actor="code", conn=conn)
        after = conn.execute("SELECT * FROM entry WHERE id = ?", (eid,)).fetchone()
        self.assertEqual(after["content"], before["content"])
        self.assertEqual(after["agent"], before["agent"])
        self.assertEqual(after["entry_type"], before["entry_type"])
        self.assertEqual(after["related_id"], before["related_id"])

    def test_nonexistent_entry_raises(self):
        conn = _node()
        with self.assertRaises(ValueError):
            retag_entry(9999, "x", reason="r", actor="code", conn=conn)

    def test_empty_reason_raises(self):
        conn = _node()
        eid = log_entry("code", "note", "x", conn=conn)
        with self.assertRaises(ValueError):
            retag_entry(eid, "x", reason="   ", actor="code", conn=conn)

    def test_empty_actor_raises(self):
        conn = _node()
        eid = log_entry("code", "note", "x", conn=conn)
        with self.assertRaises(ValueError):
            retag_entry(eid, "x", reason="r", actor="", conn=conn)


if __name__ == "__main__":
    unittest.main()
