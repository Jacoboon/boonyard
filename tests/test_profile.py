"""M4 tests — profile parsing, config precedence, soft-validation + doctor wiring."""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from boonyard import (
    audit_doctor,
    default_profile,
    init_db,
    load_profile,
    log_entry,
    node_info,
    resolve_db_path,
    resolve_profile_path,
    validate_entry,
)
from boonyard.constants import DEFAULT_AGENTS
from boonyard.profile import profile_from_dict

_TOML = """
[node]
name = "boonyard"

[agents]
code = "the implementing seat"
cowork = "the design seat"

[entry_types]
allowed = ["note", "decision", "milestone"]

[tags.namespaces]
case = "FK to some external record"

[extras]
enabled = true
fields = ["x:int"]
indexes = ["x"]
"""


def _node() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    init_db(conn=conn)
    return conn


class ProfileParsingTests(unittest.TestCase):
    def test_lane_form_agents_become_the_registry(self):
        p = profile_from_dict({"agents": {"code": "impl seat", "cowork": "design seat"}})
        self.assertEqual(p.allowed_agents, frozenset({"code", "cowork"}))
        self.assertEqual(p.agent_lanes["code"], "impl seat")

    def test_allowed_list_form_agents(self):
        p = profile_from_dict({"agents": {"allowed": ["a", "b"]}})
        self.assertEqual(p.allowed_agents, frozenset({"a", "b"}))

    def test_full_toml_parse(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "boonyard.toml"
            path.write_text(_TOML)
            p = load_profile(path)
        self.assertEqual(p.node_name, "boonyard")
        self.assertEqual(p.allowed_agents, frozenset({"code", "cowork"}))
        self.assertEqual(p.allowed_entry_types, frozenset({"note", "decision", "milestone"}))
        self.assertIn("case", p.namespaces)
        self.assertIn("model", p.namespaces)  # default namespace always present
        self.assertTrue(p.extras_enabled)
        self.assertEqual(p.extras_fields, ("x:int",))

    def test_missing_file_returns_defaults(self):
        p = load_profile("/no/such/boonyard.toml")
        self.assertEqual(p.allowed_agents, DEFAULT_AGENTS)

    def test_none_path_returns_defaults(self):
        self.assertEqual(load_profile(None).allowed_agents, DEFAULT_AGENTS)

    def test_malformed_toml_warns_not_crashes(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "boonyard.toml"
            path.write_text("this is = = not valid toml [[[")
            with self.assertLogs("boonyard", level="WARNING"):
                p = load_profile(path)
        self.assertEqual(p.allowed_agents, DEFAULT_AGENTS)  # fell back to defaults

    def test_validation_kwargs_shape(self):
        kwargs = default_profile().validation_kwargs()
        self.assertEqual(set(kwargs), {"known_agents", "known_entry_types", "known_namespaces"})


class ConfigPrecedenceTests(unittest.TestCase):
    def test_explicit_beats_env(self):
        got = resolve_db_path("/explicit/journal.db", env={"BOONYARD_DB_PATH": "/env/journal.db"})
        self.assertEqual(got, Path("/explicit/journal.db"))

    def test_env_beats_local_and_default(self):
        with tempfile.TemporaryDirectory() as d:
            got = resolve_db_path(env={"BOONYARD_DB_PATH": "/env/journal.db"}, cwd=d)
            self.assertEqual(got, Path("/env/journal.db"))

    def test_default_when_nothing_set(self):
        with tempfile.TemporaryDirectory() as d:
            got = resolve_db_path(env={}, cwd=d)
            self.assertEqual(got, Path(d) / "node" / "journal.db")

    def test_local_existing_file_wins_over_default(self):
        with tempfile.TemporaryDirectory() as d:
            local = Path(d) / "journal.db"
            local.write_text("")  # exists
            got = resolve_db_path(env={}, cwd=d)
            self.assertEqual(got, local)

    def test_profile_path_precedence(self):
        with tempfile.TemporaryDirectory() as d:
            # explicit wins
            self.assertEqual(
                resolve_profile_path("/x/boonyard.toml", env={}, cwd=d),
                Path("/x/boonyard.toml"),
            )
            # env next
            self.assertEqual(
                resolve_profile_path(env={"BOONYARD_PROFILE_PATH": "/e/boonyard.toml"}, cwd=d),
                Path("/e/boonyard.toml"),
            )
            # none found → None
            self.assertIsNone(resolve_profile_path(env={}, cwd=d))


class SoftValidationWiringTests(unittest.TestCase):
    def test_profile_drives_log_entry_warnings(self):
        conn = _node()
        profile = profile_from_dict({"agents": {"allowed": ["code"]}})
        warns: list[str] = []
        # 'opus' is a default seat but NOT in this profile's registry → should warn.
        log_entry("opus", "note", "x", conn=conn, profile=profile, warnings_out=warns)
        self.assertTrue(any("unknown agent" in w for w in warns))

    def test_profile_allows_its_declared_namespace(self):
        conn = _node()
        profile = profile_from_dict({"tags": {"namespaces": {"case": "docs"}}})
        warns = validate_entry("code", "note", tags="case:1", profile=profile, conn=conn)
        self.assertFalse(any("namespace" in w for w in warns))


class DoctorModelTagTests(unittest.TestCase):
    def test_ai_seat_without_model_tag_flagged(self):
        conn = _node()
        log_entry("code", "note", "no model tag here", conn=conn)
        report = audit_doctor(conn=conn)
        kinds = {w["kind"] for w in report["warnings"]}
        self.assertIn("missing_model_tag", kinds)

    def test_ai_seat_with_model_tag_not_flagged(self):
        conn = _node()
        log_entry("code", "note", "x", tags="model:claude-opus-4-8", conn=conn)
        report = audit_doctor(conn=conn)
        kinds = {w["kind"] for w in report["warnings"]}
        self.assertNotIn("missing_model_tag", kinds)

    def test_professor_and_system_exempt(self):
        conn = _node()
        log_entry("professor", "note", "human note, no model", conn=conn)
        log_entry("system", "note", "auto note, no model", conn=conn)
        report = audit_doctor(conn=conn)
        kinds = {w["kind"] for w in report["warnings"]}
        self.assertNotIn("missing_model_tag", kinds)

    def test_node_info_summarizes_profile(self):
        conn = _node()
        profile = profile_from_dict({"agents": {"allowed": ["code", "cowork"]}})
        info = node_info(conn=conn, profile=profile)
        self.assertEqual(set(info["profile"]["allowed_agents"]), {"code", "cowork"})


if __name__ == "__main__":
    unittest.main()
