"""M3 tests — the read path: readers, discovery, skills, node_info, audit_doctor."""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from boonyard import (
    audit_doctor,
    by_id,
    get_thread,
    init_db,
    latest_skill,
    list_agents,
    list_entry_types,
    list_skills,
    list_tags,
    log_entry,
    log_skill_revision,
    node_info,
    recent,
    search_by_tag,
    search_by_tag_exact,
    search_text,
)


def _node() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    init_db(conn=conn)
    return conn


def _seed(conn: sqlite3.Connection) -> None:
    log_entry("code", "note", "the quick brown fox", tags="alpha,animal", conn=conn)
    log_entry("opus", "decision", "chose the lazy dog", tags="beta,animal", conn=conn)
    log_entry("code", "discussion", "unrelated musings", tags="gamma", conn=conn)


class ReaderShapeTests(unittest.TestCase):
    def test_recent_newest_first_and_shape(self):
        conn = _node()
        _seed(conn)
        rows = recent(conn=conn)
        self.assertEqual(len(rows), 3)
        self.assertGreater(rows[0]["id"], rows[1]["id"])  # newest first
        self.assertIsInstance(rows[0]["tags"], list)  # tags parsed to a list

    def test_recent_filters(self):
        conn = _node()
        _seed(conn)
        self.assertEqual(len(recent(agent="code", conn=conn)), 2)
        self.assertEqual(len(recent(entry_type="decision", conn=conn)), 1)
        self.assertEqual(len(recent(limit=1, conn=conn)), 1)

    def test_by_id_hit_and_miss(self):
        conn = _node()
        eid = log_entry("code", "note", "x", conn=conn)
        self.assertEqual(by_id(eid, conn=conn)["content"], "x")
        self.assertIsNone(by_id(9999, conn=conn))

    def test_extras_parsed_back_to_dict(self):
        conn = _node()
        eid = log_entry("code", "note", "x", extras={"a": 1}, conn=conn)
        self.assertEqual(by_id(eid, conn=conn)["extras"], {"a": 1})

    def test_malformed_extras_stays_string_on_read(self):
        conn = _node()
        eid = log_entry("code", "note", "x", extras="not json", conn=conn)
        self.assertEqual(by_id(eid, conn=conn)["extras"], "not json")

    def test_get_thread_root_plus_children(self):
        conn = _node()
        root = log_entry("code", "discussion", "root", conn=conn)
        c1 = log_entry("code", "decision", "c1", related_id=root, conn=conn)
        c2 = log_entry("opus", "note", "c2", related_id=root, conn=conn)
        ids = {e["id"] for e in get_thread(root, conn=conn)}
        self.assertEqual(ids, {root, c1, c2})


class TagSearchTests(unittest.TestCase):
    def test_substring_vs_exact_distinction(self):
        conn = _node()
        log_entry("code", "note", "a", tags="animal", conn=conn)
        log_entry("code", "note", "b", tags="animalia", conn=conn)
        # substring matches both animal and animalia; exact matches only 'animal'
        self.assertEqual(len(search_by_tag("animal", conn=conn)), 2)
        self.assertEqual(len(search_by_tag_exact("animal", conn=conn)), 1)

    def test_exact_finds_namespace_tag(self):
        conn = _node()
        log_entry("code", "note", "x", tags="model:claude-opus-4-8", conn=conn)
        hits = search_by_tag_exact("model:claude-opus-4-8", conn=conn)
        self.assertEqual(len(hits), 1)


class TextSearchTests(unittest.TestCase):
    def test_fts_match(self):
        conn = _node()
        _seed(conn)
        hits = search_text("brown", conn=conn)
        self.assertEqual(len(hits), 1)
        self.assertIn("brown", hits[0]["content"])

    def test_fts_boolean_query(self):
        conn = _node()
        log_entry("code", "note", "fuse boot ritual", conn=conn)
        log_entry("code", "note", "fuse only", conn=conn)
        self.assertEqual(len(search_text("fuse AND boot", conn=conn)), 1)

    def test_malformed_query_raises_valueerror(self):
        conn = _node()
        _seed(conn)
        with self.assertRaises(ValueError):
            search_text('"unbalanced', conn=conn)


class DiscoveryTests(unittest.TestCase):
    def test_list_tags_counts_and_order(self):
        conn = _node()
        _seed(conn)  # 'animal' appears twice
        flat = list_tags(conn=conn)
        top = flat[0]
        self.assertEqual(top["tag"], "animal")
        self.assertEqual(top["count"], 2)

    def test_list_tags_prefix(self):
        conn = _node()
        log_entry("code", "note", "x", tags="case:1,case:2,other", conn=conn)
        tags = {t["tag"] for t in list_tags(prefix="case:", conn=conn)}
        self.assertEqual(tags, {"case:1", "case:2"})

    def test_list_tags_tree(self):
        conn = _node()
        log_entry("code", "note", "x", tags="skill-a,skill-b,other", conn=conn)
        tree = list_tags(tree=True, conn=conn)
        self.assertIn("skill", tree)
        self.assertEqual({t["tag"] for t in tree["skill"]}, {"skill-a", "skill-b"})

    def test_list_agents_and_types(self):
        conn = _node()
        _seed(conn)
        agents = {a["agent"]: a["count"] for a in list_agents(conn=conn)}
        self.assertEqual(agents, {"code": 2, "opus": 1})
        types = {t["entry_type"] for t in list_entry_types(conn=conn)}
        self.assertEqual(types, {"note", "decision", "discussion"})


class SkillCatalogTests(unittest.TestCase):
    def test_list_skills_groups_and_latest(self):
        conn = _node()
        root = log_skill_revision("code", "v1", slug="fuse-boot", conn=conn)
        log_skill_revision("code", "v2", root_id=root, conn=conn)
        skills = list_skills(conn=conn)
        self.assertEqual(len(skills), 1)
        skill = skills[0]
        self.assertEqual(skill["slug"], "fuse-boot")
        self.assertEqual(skill["root_id"], root)
        self.assertEqual(len(skill["all_revisions"]), 2)
        self.assertEqual(skill["latest"]["content"], "v2")
        self.assertFalse(skill["is_deprecated"])

    def test_list_skills_detects_deprecation(self):
        conn = _node()
        root = log_skill_revision("code", "v1", slug="old-way", conn=conn)
        log_skill_revision(
            "code", "superseded", root_id=root, tags="old-way-deprecated,tombstone", conn=conn
        )
        # the tombstone tag is skill-old-way-deprecated after identity-tag merge
        log_skill_revision("code", "tomb", root_id=root, tags="skill-old-way-deprecated", conn=conn)
        skill = list_skills(conn=conn)[0]
        self.assertTrue(skill["is_deprecated"])

    def test_latest_skill(self):
        conn = _node()
        root = log_skill_revision("code", "v1", slug="fuse-boot", conn=conn)
        log_skill_revision("code", "v2", root_id=root, conn=conn)
        self.assertEqual(latest_skill("fuse-boot", conn=conn)["content"], "v2")
        self.assertIsNone(latest_skill("nonexistent", conn=conn))

    def test_slugless_skill_grouped_by_root(self):
        conn = _node()
        root = log_skill_revision("code", "v1 no slug", conn=conn)  # only 'skill' tag, no slug
        log_skill_revision("code", "v2", root_id=root, conn=conn)
        skills = list_skills(conn=conn)
        self.assertEqual(len(skills), 1)
        self.assertIsNone(skills[0]["slug"])
        self.assertEqual(len(skills[0]["all_revisions"]), 2)


class NodeInfoTests(unittest.TestCase):
    def test_node_info_fields(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "journal.db"
            init_db(path, node_name="boonyard")
            log_entry("code", "note", "x", db_path=path)
            info = node_info(db_path=path)
            self.assertEqual(info["name"], "boonyard")
            self.assertEqual(info["schema_version"], 3)
            self.assertEqual(info["entry_count"], 1)
            self.assertIsNotNone(info["uuid"])
            self.assertGreater(info["storage_bytes"], 0)

    def test_node_info_in_memory_has_no_storage_bytes(self):
        conn = _node()
        self.assertIsNone(node_info(conn=conn)["storage_bytes"])


class AuditDoctorTests(unittest.TestCase):
    def test_flags_raw_delete_as_possible_deletion(self):
        conn = _node()
        log_entry("code", "note", "keep-1", conn=conn)
        mid = log_entry("code", "note", "delete-me", conn=conn)
        log_entry("code", "note", "keep-2", conn=conn)
        conn.execute(
            "DELETE FROM entry WHERE id = ?", (mid,)
        )  # raw SQL delete (ADR-0005 violation)
        report = audit_doctor(conn=conn)
        kinds = {w["kind"] for w in report["warnings"]}
        self.assertIn("possible_deletion", kinds)

    def test_flags_unknown_agent_and_type(self):
        conn = _node()
        log_entry("rogue", "spaceship", "x", conn=conn)
        report = audit_doctor(conn=conn)
        self.assertIn("rogue", {a["agent"] for a in report["unknown_agents"]})
        self.assertIn("spaceship", {t["entry_type"] for t in report["unknown_entry_types"]})

    def test_flags_orphaned_related_id(self):
        conn = _node()
        root = log_entry("code", "discussion", "root", conn=conn)
        child = log_entry("code", "note", "child", related_id=root, conn=conn)
        # Simulate out-of-band corruption (a raw SQLite edit that bypassed FK) —
        # exactly what audit_doctor exists to catch. foreign_keys can only toggle
        # outside a transaction, so commit first.
        conn.commit()
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("DELETE FROM entry WHERE id = ?", (root,))
        conn.execute("PRAGMA foreign_keys = ON")
        report = audit_doctor(conn=conn)
        kinds = {w["kind"] for w in report["warnings"]}
        self.assertIn("orphaned_related_id", kinds)
        self.assertTrue(
            any(
                child in w["sample_ids"]
                for w in report["warnings"]
                if w["kind"] == "orphaned_related_id"
            )
        )

    def test_detects_non_root_anchored_skill(self):
        conn = _node()
        root = log_skill_revision("code", "v1", slug="fuse-boot", conn=conn)
        v2 = log_skill_revision("code", "v2", root_id=root, conn=conn)
        # Manually mis-anchor v3 to v2 (a revision), bypassing the anchoring helper.
        v3 = log_entry("code", "skill", "v3", related_id=v2, tags="skill-fuse-boot", conn=conn)
        report = audit_doctor(conn=conn)
        broken = {b["broken_revision_id"] for b in report["skill_threads_not_root_anchored"]}
        self.assertIn(v3, broken)

    def test_clean_node_reports_nothing_alarming(self):
        conn = _node()
        log_entry("code", "note", "x", tags="alpha,beta", conn=conn)
        log_entry("code", "note", "y", tags="alpha,beta", conn=conn)
        report = audit_doctor(conn=conn)
        kinds = {w["kind"] for w in report["warnings"]}
        self.assertNotIn("possible_deletion", kinds)
        self.assertNotIn("orphaned_related_id", kinds)
        self.assertEqual(report["unknown_agents"], [])


if __name__ == "__main__":
    unittest.main()
