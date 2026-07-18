"""M2 tests — the write path: log_entry, log_skill_revision, soft validation."""

import json
import sqlite3
import unittest

from boonyard import init_db, log_entry, log_skill_revision, validate_entry


def _node() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    init_db(conn=conn)
    return conn


def _tags_of(conn: sqlite3.Connection, entry_id: int) -> str:
    return conn.execute("SELECT tags FROM entry WHERE id = ?", (entry_id,)).fetchone()["tags"]


def _entry_tag_set(conn: sqlite3.Connection, entry_id: int) -> set[str]:
    return {
        r["tag"] for r in conn.execute("SELECT tag FROM entry_tag WHERE entry_id = ?", (entry_id,))
    }


class HappyPathTests(unittest.TestCase):
    def test_returns_id_and_stores_row(self):
        conn = _node()
        new_id = log_entry("code", "note", "hello", tags="alpha,beta", conn=conn)
        self.assertIsInstance(new_id, int)
        row = conn.execute("SELECT * FROM entry WHERE id = ?", (new_id,)).fetchone()
        self.assertEqual(row["agent"], "code")
        self.assertEqual(row["content"], "hello")

    def test_type_tag_added_automatically(self):
        conn = _node()
        new_id = log_entry("code", "decision", "x", tags="alpha", conn=conn)
        self.assertIn("decision", _tags_of(conn, new_id).split(","))
        self.assertIn("decision", _entry_tag_set(conn, new_id))

    def test_entry_tag_rows_populated_in_transaction(self):
        conn = _node()
        new_id = log_entry("code", "note", "x", tags="alpha,beta", conn=conn)
        # Visible on the same (uncommitted) connection → same transaction as insert.
        self.assertEqual(_entry_tag_set(conn, new_id), {"alpha", "beta", "note"})

    def test_extras_dict_serialized_to_json(self):
        conn = _node()
        new_id = log_entry("code", "note", "x", extras={"player_id": "p1", "x": 3}, conn=conn)
        raw = conn.execute("SELECT extras FROM entry WHERE id = ?", (new_id,)).fetchone()["extras"]
        self.assertEqual(json.loads(raw), {"player_id": "p1", "x": 3})

    def test_related_id_threads(self):
        conn = _node()
        root = log_entry("code", "discussion", "root", conn=conn)
        child = log_entry("code", "decision", "child", related_id=root, conn=conn)
        got = conn.execute("SELECT related_id FROM entry WHERE id = ?", (child,)).fetchone()
        self.assertEqual(got["related_id"], root)

    def test_duplicate_tags_deduplicated(self):
        conn = _node()
        new_id = log_entry("code", "note", "x", tags="alpha,alpha,note", conn=conn)
        self.assertEqual(_tags_of(conn, new_id), "alpha,note")


class HardFailTests(unittest.TestCase):
    def test_empty_agent_raises(self):
        conn = _node()
        with self.assertRaises(ValueError):
            log_entry("", "note", "x", conn=conn)

    def test_empty_entry_type_raises(self):
        conn = _node()
        with self.assertRaises(ValueError):
            log_entry("code", "  ", "x", conn=conn)

    def test_empty_content_raises(self):
        conn = _node()
        with self.assertRaises(ValueError):
            log_entry("code", "note", "", conn=conn)

    def test_nonexistent_related_id_raises(self):
        conn = _node()
        with self.assertRaises(ValueError):
            log_entry("code", "note", "x", related_id=9999, conn=conn)

    def test_nothing_written_on_hard_fail(self):
        conn = _node()
        with self.assertRaises(ValueError):
            log_entry("code", "note", "x", related_id=9999, conn=conn)
        n = conn.execute("SELECT COUNT(*) AS n FROM entry").fetchone()["n"]
        self.assertEqual(n, 0)


class SoftWarnButInsertTests(unittest.TestCase):
    def test_unknown_agent_warns_but_inserts(self):
        conn = _node()
        warns: list[str] = []
        new_id = log_entry("rogue-seat", "note", "x", conn=conn, warnings_out=warns)
        self.assertTrue(any("unknown agent" in w for w in warns))
        self.assertIsNotNone(conn.execute("SELECT 1 FROM entry WHERE id = ?", (new_id,)).fetchone())

    def test_unknown_entry_type_warns_but_inserts(self):
        conn = _node()
        warns: list[str] = []
        log_entry("code", "spaceship", "x", conn=conn, warnings_out=warns)
        self.assertTrue(any("unknown entry_type" in w for w in warns))

    def test_uppercase_tag_lowercased_with_warning(self):
        conn = _node()
        warns: list[str] = []
        new_id = log_entry("code", "note", "x", tags="Alpha", conn=conn, warnings_out=warns)
        self.assertIn("alpha", _tags_of(conn, new_id).split(","))
        self.assertTrue(any("uppercase" in w for w in warns))

    def test_whitespace_inside_tag_splits_with_warning(self):
        conn = _node()
        warns: list[str] = []
        new_id = log_entry("code", "note", "x", tags="foo bar", conn=conn, warnings_out=warns)
        tags = _tags_of(conn, new_id).split(",")
        self.assertIn("foo", tags)
        self.assertIn("bar", tags)
        self.assertTrue(any("whitespace" in w for w in warns))

    def test_underscore_tag_warns_but_preserved(self):
        conn = _node()
        warns: list[str] = []
        new_id = log_entry("code", "note", "x", tags="sysop_session", conn=conn, warnings_out=warns)
        self.assertIn("sysop_session", _tags_of(conn, new_id).split(","))
        self.assertTrue(any("underscore" in w for w in warns))

    def test_undeclared_namespace_warns_when_a_set_is_given(self):
        conn = _node()
        warns: list[str] = []
        log_entry(
            "code",
            "note",
            "x",
            tags="case:123",
            known_namespaces=frozenset({"model"}),
            conn=conn,
            warnings_out=warns,
        )
        self.assertTrue(any("namespace" in w for w in warns))

    def test_model_namespace_not_flagged_by_default(self):
        conn = _node()
        warns: list[str] = []
        log_entry(
            "code",
            "note",
            "x",
            tags="model:claude-opus-4-8",
            known_namespaces=frozenset({"model"}),
            conn=conn,
            warnings_out=warns,
        )
        self.assertFalse(any("namespace" in w for w in warns))

    def test_dot_tag_warns_but_preserved(self):
        conn = _node()
        warns: list[str] = []
        new_id = log_entry(
            "code", "note", "x", tags="feature.request", conn=conn, warnings_out=warns
        )
        self.assertIn("feature.request", _tags_of(conn, new_id).split(","))
        self.assertTrue(any("dot" in w for w in warns))

    def test_plural_fork_warns(self):
        conn = _node()
        log_entry("code", "note", "x", tags="skill-fuse-boot", conn=conn)  # seeds prefix 'skill'
        warns: list[str] = []
        log_entry("code", "note", "y", tags="skills-system", conn=conn, warnings_out=warns)
        self.assertTrue(any("plural-fork" in w for w in warns))


class ValidateEntryTests(unittest.TestCase):
    def test_validate_reports_without_writing(self):
        conn = _node()
        warns = validate_entry("rogue", "spaceship", tags="Bad_Tag", conn=conn)
        self.assertTrue(any("unknown agent" in w for w in warns))
        self.assertTrue(any("unknown entry_type" in w for w in warns))
        n = conn.execute("SELECT COUNT(*) AS n FROM entry").fetchone()["n"]
        self.assertEqual(n, 0)

    def test_validate_without_conn_skips_node_context_checks(self):
        # No conn → plural-fork check is skipped; still reports agent/type/tag issues.
        warns = validate_entry("rogue", "note", tags="Bad")
        self.assertTrue(any("unknown agent" in w for w in warns))


class SkillRevisionTests(unittest.TestCase):
    def test_first_revision_becomes_root(self):
        conn = _node()
        root = log_skill_revision("code", "SKILL: do a thing", slug="do-thing", conn=conn)
        row = conn.execute(
            "SELECT related_id, entry_type FROM entry WHERE id = ?", (root,)
        ).fetchone()
        self.assertIsNone(row["related_id"])  # the root anchors to nothing
        self.assertEqual(row["entry_type"], "skill")

    def test_identity_and_type_tags_present(self):
        conn = _node()
        root = log_skill_revision("code", "SKILL: x", slug="fuse-boot", conn=conn)
        tags = set(_tags_of(conn, root).split(","))
        self.assertIn("skill", tags)
        self.assertIn("skill-fuse-boot", tags)

    def test_revision_anchors_to_root(self):
        conn = _node()
        root = log_skill_revision("code", "v1", slug="fuse-boot", conn=conn)
        v2 = log_skill_revision("code", "v2", root_id=root, conn=conn)
        rid = conn.execute("SELECT related_id FROM entry WHERE id = ?", (v2,)).fetchone()[
            "related_id"
        ]
        self.assertEqual(rid, root)

    def test_revision_of_a_revision_still_anchors_to_true_root(self):
        conn = _node()
        root = log_skill_revision("code", "v1", slug="fuse-boot", conn=conn)
        v2 = log_skill_revision("code", "v2", root_id=root, conn=conn)
        # Pass v2 (a revision) as root_id; v3 must still anchor to the true root.
        v3 = log_skill_revision("code", "v3", root_id=v2, conn=conn)
        rid = conn.execute("SELECT related_id FROM entry WHERE id = ?", (v3,)).fetchone()[
            "related_id"
        ]
        self.assertEqual(rid, root)

    def test_revision_inherits_slug_from_root(self):
        conn = _node()
        root = log_skill_revision("code", "v1", slug="fuse-boot", conn=conn)
        v2 = log_skill_revision("code", "v2", root_id=root, conn=conn)  # no slug given
        self.assertIn("skill-fuse-boot", _tags_of(conn, v2).split(","))

    def test_missing_slug_warns(self):
        conn = _node()
        warns: list[str] = []
        log_skill_revision("code", "SKILL: no slug", conn=conn, warnings_out=warns)
        self.assertTrue(any("slug" in w for w in warns))

    def test_nonexistent_root_id_raises(self):
        conn = _node()
        with self.assertRaises(ValueError):
            log_skill_revision("code", "v2", root_id=9999, conn=conn)

    def test_revising_a_slugless_root_warns(self):
        conn = _node()
        root = log_skill_revision("code", "v1 no slug", conn=conn)  # root has only 'skill' tag
        warns: list[str] = []
        log_skill_revision("code", "v2", root_id=root, conn=conn, warnings_out=warns)
        self.assertTrue(any("slug" in w for w in warns))


class DbPathWritePathTests(unittest.TestCase):
    def test_log_via_db_path_commits_and_roundtrips(self):
        import tempfile
        from pathlib import Path

        from boonyard import connect

        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "journal.db"
            init_db(path)
            new_id = log_entry("code", "note", "persisted", tags="alpha", db_path=path)
            # A fresh connection sees it → the db_path path committed.
            with connect(path) as conn:
                row = conn.execute("SELECT content FROM entry WHERE id = ?", (new_id,)).fetchone()
                self.assertEqual(row["content"], "persisted")
                tags = {r["tag"] for r in conn.execute("SELECT tag FROM entry_tag")}
                self.assertEqual(tags, {"alpha", "note"})

    def test_no_conn_and_no_db_path_raises(self):
        with self.assertRaises(ValueError):
            log_entry("code", "note", "x")


class ExtrasTests(unittest.TestCase):
    def test_valid_json_string_stored_without_warning(self):
        conn = _node()
        warns: list[str] = []
        log_entry("code", "note", "x", extras='{"a": 1}', conn=conn, warnings_out=warns)
        self.assertFalse(any("extras" in w for w in warns))

    def test_invalid_json_string_warns_but_stored(self):
        conn = _node()
        warns: list[str] = []
        new_id = log_entry("code", "note", "x", extras="not json", conn=conn, warnings_out=warns)
        raw = conn.execute("SELECT extras FROM entry WHERE id = ?", (new_id,)).fetchone()["extras"]
        self.assertEqual(raw, "not json")
        self.assertTrue(any("extras" in w for w in warns))

    def test_unserializable_extras_warns_and_stringifies(self):
        conn = _node()
        warns: list[str] = []
        # a set is not JSON-serializable
        new_id = log_entry("code", "note", "x", extras={1, 2, 3}, conn=conn, warnings_out=warns)
        raw = conn.execute("SELECT extras FROM entry WHERE id = ?", (new_id,)).fetchone()["extras"]
        self.assertIsNotNone(raw)
        self.assertTrue(any("extras" in w for w in warns))


if __name__ == "__main__":
    unittest.main()
