"""``python -m boonyardnn`` — the provisioning commands and their exit codes."""

import argparse
import contextlib
import io
import json
import os
import re
import tempfile
import unittest
from pathlib import Path

from boonyardnn.cli import EXIT_NOT_FOUND, EXIT_OK, EXIT_USAGE, build_parser, main
from boonyardnn.registry import Registry

_KEY_RE = re.compile(r"bnyk_[0-9a-f]{64}")


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


class HelpTests(unittest.TestCase):
    def _subcommands(self, parser) -> dict[str, argparse.ArgumentParser]:
        for action in parser._actions:
            if isinstance(action, argparse._SubParsersAction):
                return dict(action.choices)
        return {}

    def test_every_command_and_subcommand_help_exits_zero(self):
        parser = build_parser()
        top = self._subcommands(parser)
        self.assertEqual(
            set(top),
            {"user", "node", "key", "export", "serve", "serve-web", "account", "mail"},
        )
        for name, sub in top.items():
            self.assertEqual(_help_exit_code([name, "--help"]), 0, name)
            for child in self._subcommands(sub):
                self.assertEqual(_help_exit_code([name, child, "--help"]), 0, f"{name} {child}")

    def test_no_command_is_usage_error(self):
        self.assertEqual(_help_exit_code([]), 2)


class CliTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = str(Path(self._tmp.name) / "data")
        self._env = dict(os.environ)
        os.environ.pop("BOONYARDNN_DATA_ROOT", None)
        os.environ.pop("BOONYARDNN_PUBLIC_BASE", None)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env)
        self._tmp.cleanup()

    def cmd(self, *argv: str) -> tuple[int, str, str]:
        return run(["--root", self.root, *argv])


class RootResolutionTests(CliTestCase):
    def test_missing_root_is_a_usage_error(self):
        code, _out, err = run(["user", "list"])
        self.assertEqual(code, EXIT_USAGE)
        self.assertIn("BOONYARDNN_DATA_ROOT", err)

    def test_env_root_is_honoured(self):
        os.environ["BOONYARDNN_DATA_ROOT"] = self.root
        code, out, _ = run(["user", "add", "alice", "--email", "alice@example.test"])
        self.assertEqual(code, EXIT_OK)
        self.assertIsNotNone(Registry(Path(self.root)).get_user("alice"))


class AcceptanceFlowTests(CliTestCase):
    """§ACCEPTANCE 1: user add → node add → key add prints one key and two URLs."""

    def test_user_zero_flow(self):
        code, out, _ = self.cmd("user", "add", "jacoboon", "--email", "jacob@example.test")
        self.assertEqual(code, EXIT_OK)
        self.assertIn("jacoboon", out)

        code, out, _ = self.cmd("node", "add", "jacoboon", "test-0")
        self.assertEqual(code, EXIT_OK)
        self.assertIn("test-0", out)

        code, out, _ = self.cmd("key", "add", "jacoboon", "test-0", "--label", "code seat")
        self.assertEqual(code, EXIT_OK)
        keys = _KEY_RE.findall(out)
        self.assertEqual(len(set(keys)), 1, "exactly one raw key is printed")
        raw = keys[0]
        self.assertIn(f"http://127.0.0.1:8800/jacoboon/test-0/{raw}", out)  # capability form
        self.assertIn("http://127.0.0.1:8800/jacoboon/test-0\n", out + "\n")  # header form
        self.assertIn("Authorization: Bearer", out)

        # The raw key appears nowhere on disk.
        hits = [
            p for p in Path(self.root).rglob("*") if p.is_file() and raw.encode() in p.read_bytes()
        ]
        self.assertEqual(hits, [])

        # And never again on stdout: key list shows label + dates, no hash, no raw.
        code, out, _ = self.cmd("key", "list", "jacoboon", "test-0")
        self.assertEqual(code, EXIT_OK)
        self.assertIn("code seat", out)
        self.assertNotIn(raw, out)
        store = json.loads(next(Path(self.root).rglob("api_keys.json")).read_text())
        self.assertNotIn(store["keys"][0]["hashed_secret"], out)

    def test_public_base_env_changes_the_printed_urls_only(self):
        os.environ["BOONYARDNN_PUBLIC_BASE"] = "https://mcp.boonyard.com"
        self.cmd("user", "add", "alice", "--email", "a@example.test")
        self.cmd("node", "add", "alice", "n1")
        _code, out, _ = self.cmd("key", "add", "alice", "n1")
        self.assertIn("https://mcp.boonyard.com/alice/n1", out)
        self.assertNotIn("127.0.0.1", out)


class ListAndRevokeTests(CliTestCase):
    def setUp(self):
        super().setUp()
        self.cmd("user", "add", "alice", "--email", "a@example.test")
        self.cmd("node", "add", "alice", "n1")

    def test_user_and_node_list(self):
        code, out, _ = self.cmd("user", "list")
        self.assertEqual(code, EXIT_OK)
        self.assertIn("alice", out)
        code, out, _ = self.cmd("node", "list", "alice")
        self.assertEqual(code, EXIT_OK)
        self.assertIn("n1", out)

    def test_key_revoke(self):
        _code, out, _ = self.cmd("key", "add", "alice", "n1")
        key_id = re.search(r"key_id:\s+(\S+)", out).group(1)
        code, out, _ = self.cmd("key", "revoke", key_id)
        self.assertEqual(code, EXIT_OK)
        self.assertIn("revoked", out)
        code, out, _ = self.cmd("key", "list", "alice", "n1")
        self.assertIn("revoked", out)

    def test_revoke_unknown_key_is_not_found(self):
        code, _, err = self.cmd("key", "revoke", "no-such-key")
        self.assertEqual(code, EXIT_NOT_FOUND)
        self.assertIn("no-such-key", err)

    def test_unknown_user_is_not_found(self):
        code, _, _ = self.cmd("node", "list", "nobody")
        self.assertEqual(code, EXIT_NOT_FOUND)
        code, _, _ = self.cmd("node", "add", "nobody", "n1")
        self.assertEqual(code, EXIT_NOT_FOUND)

    def test_bad_slug_is_usage_error(self):
        code, _, err = self.cmd("user", "add", "Admin", "--email", "x@example.test")
        self.assertEqual(code, EXIT_USAGE)
        self.assertIn("slug", err)
        code, _, _ = self.cmd("user", "add", "admin", "--email", "x@example.test")
        self.assertEqual(code, EXIT_USAGE)

    def test_duplicate_slug_is_usage_error(self):
        code, _, err = self.cmd("user", "add", "alice", "--email", "x@example.test")
        self.assertEqual(code, EXIT_USAGE)
        self.assertIn("alice", err)

    def test_export(self):
        code, out, _ = self.cmd("export", "alice", "n1")
        self.assertEqual(code, EXIT_OK)
        self.assertIn("export_", out)
        bundles = list(Path(self.root).rglob("exports/export_*.zip"))
        self.assertEqual(len(bundles), 1)
