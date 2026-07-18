"""M5 tests — the CLI: --help exit codes, exit codes, log→recent roundtrip."""

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from boonyard.cli import build_parser, main


def run(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv)
    return code, out.getvalue(), err.getvalue()


def _help_exit_code(argv: list[str]) -> int:
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            main(argv)
    except SystemExit as exc:
        return int(exc.code or 0)
    return -1


class CliTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self._tmp.name) / "node" / "journal.db")
        run(["--db", self.db, "init", "--name", "test"])

    def tearDown(self):
        self._tmp.cleanup()


class HelpTests(unittest.TestCase):
    def test_every_command_help_exits_zero(self):
        parser = build_parser()
        # Discover the registered subcommand names from the parser itself.
        names = []
        for action in parser._actions:
            if isinstance(action, __import__("argparse")._SubParsersAction):
                names.extend(action.choices)
        self.assertIn("log", names)
        for name in names:
            self.assertEqual(_help_exit_code([name, "--help"]), 0, f"{name} --help")

    def test_top_level_help_exits_zero(self):
        self.assertEqual(_help_exit_code(["--help"]), 0)

    def test_skill_subcommand_help_exits_zero(self):
        self.assertEqual(_help_exit_code(["skill", "latest", "--help"]), 0)
        self.assertEqual(_help_exit_code(["skill", "new", "--help"]), 0)


class InitTests(CliTestCase):
    def test_init_creates_db_and_toml(self):
        self.assertTrue(Path(self.db).exists())
        self.assertTrue((Path(self.db).parent / "boonyard.toml").exists())


class RoundtripTests(CliTestCase):
    def test_log_then_recent(self):
        code, out, _ = run(["--db", self.db, "log", "code", "note", "hello world", "--tags", "a,b"])
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "1")  # first entry id
        code, out, _ = run(["--db", self.db, "recent"])
        self.assertEqual(code, 0)
        self.assertIn("hello world", out)
        self.assertIn("code/note", out)

    def test_show_hit_and_miss(self):
        run(["--db", self.db, "log", "code", "note", "findme"])
        code, out, _ = run(["--db", self.db, "show", "1"])
        self.assertEqual(code, 0)
        self.assertIn("findme", out)
        code, _, err = run(["--db", self.db, "show", "999"])
        self.assertEqual(code, 1)  # not found
        self.assertIn("not found", err)

    def test_thread(self):
        run(["--db", self.db, "log", "code", "discussion", "root"])
        run(["--db", self.db, "log", "code", "decision", "child", "--related", "1"])
        code, out, _ = run(["--db", self.db, "thread", "1"])
        self.assertEqual(code, 0)
        self.assertIn("root", out)
        self.assertIn("child", out)

    def test_tag_and_find(self):
        run(["--db", self.db, "log", "code", "note", "the fox", "--tags", "animal"])
        code, out, _ = run(["--db", self.db, "tag", "animal"])
        self.assertEqual(code, 0)
        self.assertIn("the fox", out)
        code, out, _ = run(["--db", self.db, "find", "fox"])
        self.assertEqual(code, 0)
        self.assertIn("the fox", out)

    def test_tags_agents_types(self):
        run(["--db", self.db, "log", "code", "note", "x", "--tags", "alpha"])
        self.assertIn("alpha", run(["--db", self.db, "tags"])[1])
        self.assertIn("code", run(["--db", self.db, "agents"])[1])
        self.assertIn("note", run(["--db", self.db, "types"])[1])


class DoctorAndMaintenanceTests(CliTestCase):
    def test_doctor_clean_fresh_node(self):
        code, out, _ = run(["--db", self.db, "doctor"])
        self.assertEqual(code, 0)
        self.assertIn("boonyard doctor", out)

    def test_reindex_runs(self):
        run(["--db", self.db, "log", "code", "note", "x", "--tags", "a,b"])
        code, out, _ = run(["--db", self.db, "reindex"])
        self.assertEqual(code, 0)
        self.assertIn("reindexed", out)
        # entry_tag preserved after reindex
        self.assertIn("a", run(["--db", self.db, "tags"])[1])

    def test_info(self):
        code, out, _ = run(["--db", self.db, "info"])
        self.assertEqual(code, 0)
        self.assertIn("schema_version: 3", out)


class RetagAndSkillTests(CliTestCase):
    def test_retag(self):
        run(["--db", self.db, "log", "code", "note", "x", "--tags", "old"])
        code, out, _ = run(
            ["--db", self.db, "retag", "1", "new", "--reason", "merge", "--actor", "code"]
        )
        self.assertEqual(code, 0)
        self.assertIn("new", run(["--db", self.db, "tags"])[1])

    def test_skill_new_renders_template(self):
        code, out, _ = run(["--db", self.db, "skill", "new", "fuse-boot"])
        self.assertEqual(code, 0)
        self.assertIn("SKILL:", out)
        self.assertIn("fuse-boot", out)

    def test_skill_latest_miss(self):
        code, _, err = run(["--db", self.db, "skill", "latest", "nope"])
        self.assertEqual(code, 1)


class OutputBranchTests(CliTestCase):
    def test_recent_empty_node(self):
        code, out, _ = run(["--db", self.db, "recent"])
        self.assertEqual(code, 0)
        self.assertIn("(no entries)", out)

    def test_log_unknown_agent_warns_on_stderr(self):
        code, out, err = run(["--db", self.db, "log", "rogue", "note", "x"])
        self.assertEqual(code, 0)
        self.assertIn("warning:", err)
        self.assertIn("unknown agent", err)

    def test_thread_miss(self):
        code, _, err = run(["--db", self.db, "thread", "999"])
        self.assertEqual(code, 1)
        self.assertIn("no thread", err)

    def test_tags_tree(self):
        run(["--db", self.db, "log", "code", "note", "x", "--tags", "skill-a,skill-b"])
        code, out, _ = run(["--db", self.db, "tags", "--tree"])
        self.assertEqual(code, 0)
        self.assertIn("skill:", out)

    def test_skills_empty_and_populated(self):
        self.assertIn("(no skills)", run(["--db", self.db, "skills"])[1])
        run(["--db", self.db, "log", "code", "skill", "SKILL: x", "--tags", "skill-fuse-boot"])
        code, out, _ = run(["--db", self.db, "skills"])
        self.assertEqual(code, 0)
        self.assertIn("fuse-boot", out)

    def test_skill_latest_hit(self):
        run(["--db", self.db, "log", "code", "skill", "SKILL: body", "--tags", "skill-fuse-boot"])
        code, out, _ = run(["--db", self.db, "skill", "latest", "fuse-boot"])
        self.assertEqual(code, 0)
        self.assertIn("SKILL: body", out)

    def test_doctor_reports_warnings(self):
        run(["--db", self.db, "log", "rogue", "spaceship", "x"])  # unknown agent+type, no model tag
        code, out, _ = run(["--db", self.db, "doctor"])
        self.assertEqual(code, 0)
        self.assertIn("unknown-agent", out)
        self.assertIn("missing_model_tag", out)


class ErrorHandlingTests(CliTestCase):
    def test_bad_extras_json_exits_usage(self):
        code, _, err = run(["--db", self.db, "log", "code", "note", "x", "--extras", "not json"])
        self.assertEqual(code, 2)
        self.assertIn("error", err)

    def test_retag_missing_reason_is_argparse_error(self):
        # argparse enforces required --reason before our handler runs.
        self.assertEqual(_help_exit_code(["--db", self.db, "retag", "1", "new", "--actor", "x"]), 2)


class UmbrellaTests(unittest.TestCase):
    def test_umbrella_init_add_list_recent(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = str(Path(d) / "umbrella.toml")
            node = str(Path(d) / "n" / "journal.db")
            run(["--db", node, "init", "--name", "solo"])
            run(["--db", node, "log", "code", "note", "unified"])
            self.assertEqual(run(["umbrella", "--config", cfg, "init"])[0], 0)
            self.assertEqual(run(["umbrella", "--config", cfg, "add", "solo", node])[0], 0)
            code, out, _ = run(["umbrella", "--config", cfg, "list"])
            self.assertEqual(code, 0)
            self.assertIn("solo", out)
            code, out, _ = run(["umbrella", "--config", cfg, "recent"])
            self.assertEqual(code, 0)
            self.assertIn("unified", out)

    def test_umbrella_remove_missing(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = str(Path(d) / "umbrella.toml")
            run(["umbrella", "--config", cfg, "init"])
            code, _, err = run(["umbrella", "--config", cfg, "remove", "ghost"])
            self.assertEqual(code, 1)

    def test_umbrella_find_tags_and_remove(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = str(Path(d) / "umbrella.toml")
            node = str(Path(d) / "n" / "journal.db")
            run(["--db", node, "init", "--name", "solo"])
            run(["--db", node, "log", "code", "note", "findable body", "--tags", "z"])
            run(["umbrella", "--config", cfg, "add", "solo", node])
            self.assertIn("findable", run(["umbrella", "--config", cfg, "find", "findable"])[1])
            self.assertIn("z", run(["umbrella", "--config", cfg, "tags"])[1])
            self.assertIn("z:", run(["umbrella", "--config", cfg, "tags", "--tree"])[1])
            self.assertEqual(run(["umbrella", "--config", cfg, "remove", "solo"])[0], 0)

    def test_umbrella_list_empty(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = str(Path(d) / "umbrella.toml")
            run(["umbrella", "--config", cfg, "init"])
            self.assertIn("no nodes", run(["umbrella", "--config", cfg, "list"])[1])


class McpKeyResolutionTests(unittest.TestCase):
    def _args(self, key):
        import argparse

        return argparse.Namespace(key=key)

    def test_explicit_key_wins(self):
        import os

        from boonyard.cli import _resolve_mcp_key

        os.environ["BOONYARD_MCP_KEY"] = "from_env"
        try:
            self.assertEqual(_resolve_mcp_key(self._args("explicit")), "explicit")
        finally:
            del os.environ["BOONYARD_MCP_KEY"]

    def test_env_fallback(self):
        import os

        from boonyard.cli import _resolve_mcp_key

        os.environ["BOONYARD_MCP_KEY"] = "from_env"
        try:
            self.assertEqual(_resolve_mcp_key(self._args(None)), "from_env")
        finally:
            del os.environ["BOONYARD_MCP_KEY"]

    def test_none_when_unset(self):
        import os

        from boonyard.cli import _resolve_mcp_key

        os.environ.pop("BOONYARD_MCP_KEY", None)
        self.assertIsNone(_resolve_mcp_key(self._args(None)))


class ModuleEntryPointTests(unittest.TestCase):
    def test_python_m_boonyard_version(self):
        import subprocess
        import sys

        env = {
            **__import__("os").environ,
            "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "package"),
        }
        result = subprocess.run(
            [sys.executable, "-m", "boonyard", "--version"],
            capture_output=True,
            text=True,
            env=env,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("boonyard", result.stdout)


if __name__ == "__main__":
    unittest.main()
