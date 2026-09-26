"""The audited profile write — ``meta_log`` op ``profile_change`` (boonyard #168)."""

import json
import os
import sqlite3
import tempfile
import tomllib
import unittest
from contextlib import closing, contextmanager
from pathlib import Path
from unittest import mock

from boonyard import change_profile, init_db, load_profile, profile_history
from boonyard import profile_change as pc
from boonyard.mcp import TOOL_DEFS

#: What ``boonyard init`` writes (cli.cmd_init), trimmed to the tables that matter here.
_STARTER = (
    '[node]\nname = "n1"\nschema_version = 3\n\n'
    "[agents]\n"
    "# Advisory seat registry (wall entry 97). Unknown seats warn, never reject.\n"
    'code = "the implementing seat"\n'
    'system = "auto-generated entries"\n\n'
    "[tags.namespaces]\n"
    'model = "exact model string"\n\n'
    "[extras]\nenabled = false\n"
)


class _Node:
    """A real node on disk: ``journal.db`` with a ``boonyard.toml`` beside it."""

    def __init__(self, toml: str | None = _STARTER):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.db = root / "journal.db"
        self.toml = root / "boonyard.toml"
        init_db(self.db, node_name="n1")
        if toml is not None:
            self.toml.write_text(toml, encoding="utf-8", newline="\n")

    def text(self) -> str:
        return self.toml.read_text(encoding="utf-8")

    def audit_rows(self) -> int:
        with closing(sqlite3.connect(self.db)) as c:
            sql = "SELECT COUNT(*) FROM meta_log WHERE op = 'profile_change'"
            return c.execute(sql).fetchone()[0]

    def change(self, text: str, **kw):
        kw.setdefault("reason", "because")
        kw.setdefault("actor", "alice")
        return change_profile(self.toml, text, db_path=self.db, **kw)

    def close(self):
        self._tmp.cleanup()


class ChangeProfileTests(unittest.TestCase):
    def setUp(self):
        self.node = _Node()
        self.addCleanup(self.node.close)

    def test_writes_the_file_and_one_audit_row(self):
        new = _STARTER.replace('system = "auto', 'tg-dev = "the Tea Guru dev seat"\nsystem = "auto')
        ml_id = self.node.change(new, reason="register tg-dev", actor="jacoboon")
        self.assertEqual(self.node.text(), new)
        with closing(sqlite3.connect(self.node.db)) as c:
            c.row_factory = sqlite3.Row
            row = c.execute("SELECT * FROM meta_log WHERE id = ?", (ml_id,)).fetchone()
        self.assertEqual(row["op"], "profile_change")
        self.assertIsNone(row["entry_id"])
        self.assertEqual(row["actor"], "jacoboon")
        payload = json.loads(row["payload"])
        self.assertEqual(payload["before"], _STARTER)
        self.assertEqual(payload["after"], new)
        self.assertEqual(payload["reason"], "register tg-dev")
        self.assertEqual(payload["sha256_before"], pc.profile_sha256(_STARTER))
        self.assertEqual(payload["sha256_after"], pc.profile_sha256(new))
        # and the node now knows the seat, with no restart of anything
        self.assertIn("tg-dev", load_profile(self.node.toml).allowed_agents)

    def test_history_is_newest_first_with_decoded_payloads(self):
        first = _STARTER + "\n[x]\na = 1\n"
        second = first.replace("a = 1", "a = 2")
        self.node.change(first, reason="one")
        self.node.change(second, reason="two", actor="bob")
        rows = profile_history(db_path=self.node.db)
        self.assertEqual([r["reason"] for r in rows], ["two", "one"])
        self.assertEqual(rows[0]["actor"], "bob")
        self.assertEqual(rows[0]["before"], first)
        self.assertEqual(rows[0]["after"], second)
        self.assertEqual(len(profile_history(db_path=self.node.db, limit=1)), 1)

    def test_a_stale_read_is_refused_not_overwritten(self):
        read_at = pc.profile_sha256(self.node.text())
        # someone else edits it by hand in between (the droplet sed of #66@holloway)
        self.node.toml.write_text(_STARTER + "# by hand\n", encoding="utf-8", newline="\n")
        with self.assertRaises(pc.ProfileConflict):
            self.node.change(_STARTER + "\n[x]\na = 1\n", expected_sha256=read_at)
        self.assertEqual(self.node.text(), _STARTER + "# by hand\n")
        self.assertEqual(self.node.audit_rows(), 0)
        # the fresh fingerprint goes through
        self.node.change(
            _STARTER + "\n[x]\na = 1\n", expected_sha256=pc.profile_sha256(self.node.text())
        )

    def test_refusals_write_nothing(self):
        cases = {
            "not toml": ("[agents\ncode = 1", {}),
            "wrong shape": ('agents = "code"\n', {}),
            "a node rename": (_STARTER.replace('name = "n1"', 'name = "n2"'), {}),
            "dropping [node]": (_STARTER.split("\n\n", 1)[1], {}),
            "no change": (_STARTER, {}),
            "too large": (_STARTER + "# " + "x" * pc.MAX_PROFILE_BYTES + "\n", {}),
            "empty reason": (_STARTER + "# x\n", {"reason": "  "}),
            "empty actor": (_STARTER + "# x\n", {"actor": ""}),
        }
        for label, (text, kw) in cases.items():
            with self.subTest(label), self.assertRaises(ValueError):
                self.node.change(text, **kw)
        self.assertEqual(self.node.text(), _STARTER)
        self.assertEqual(self.node.audit_rows(), 0)

    def test_creates_a_profile_where_there_was_none(self):
        bare = _Node(toml=None)
        self.addCleanup(bare.close)
        self.assertEqual(pc.read_profile_text(bare.toml), "")
        text = '[agents]\ncode = "builds"\n'
        bare.change(text, expected_sha256=pc.profile_sha256(""))
        self.assertEqual(bare.text(), text)
        self.assertEqual(profile_history(db_path=bare.db)[0]["before"], "")

    def test_a_broken_profile_can_be_repaired(self):
        broken = _Node(toml="[agents\n")
        self.addCleanup(broken.close)
        broken.change(_STARTER)
        self.assertEqual(broken.text(), _STARTER)

    def test_a_failed_swap_leaves_no_audit_row(self):
        with mock.patch.object(pc, "_atomic_write", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.node.change(_STARTER + "# x\n")
        self.assertEqual(self.node.text(), _STARTER)
        self.assertEqual(self.node.audit_rows(), 0)
        self.assertEqual(list(self.node.toml.parent.glob(".boonyard.toml.*")), [])

    def test_a_failed_commit_puts_the_old_file_back(self):
        """The file must never say what the audit does not: if the row cannot be
        committed after the swap, the swap is undone."""
        real = pc.resolve_conn

        @contextmanager
        def commit_fails(conn, db_path, **kw):
            with real(conn, db_path, **kw) as c:
                yield c
                raise sqlite3.OperationalError("database is locked")

        with mock.patch.object(pc, "resolve_conn", commit_fails):
            with self.assertRaises(sqlite3.OperationalError):
                self.node.change(_STARTER + "# x\n")
        self.assertEqual(self.node.text(), _STARTER)
        self.assertEqual(self.node.audit_rows(), 0)

    @unittest.skipIf(os.name == "nt", "POSIX file modes")
    def test_the_file_keeps_its_mode(self):
        os.chmod(self.node.toml, 0o640)
        self.node.change(_STARTER + "# x\n")
        self.assertEqual(self.node.toml.stat().st_mode & 0o777, 0o640)

    def test_it_is_not_an_mcp_tool(self):
        """An agent that could rewrite the seat registry could register itself
        through the door the registry governs (boonyard #168)."""
        names = {t["name"] for t in TOOL_DEFS}
        self.assertFalse({n for n in names if "profile" in n or "seat" in n}, names)


class AddSeatTests(unittest.TestCase):
    def test_goes_after_the_last_seat_and_keeps_every_other_byte(self):
        out = pc.add_seat(_STARTER, "tg-dev", "the Tea Guru dev seat")
        self.assertEqual(
            out,
            _STARTER.replace(
                'system = "auto-generated entries"\n',
                'system = "auto-generated entries"\ntg-dev = "the Tea Guru dev seat"\n',
            ),
        )
        self.assertIn("tg-dev", pc.validate_profile_text(out, current=_STARTER).allowed_agents)

    def test_quotes_and_backslashes_are_escaped(self):
        out = pc.add_seat(_STARTER, "warden", 'says "no" \\ often')
        self.assertEqual(tomllib.loads(out)["agents"]["warden"], 'says "no" \\ often')

    def test_a_profile_without_agents_gets_the_table(self):
        for text in ("", '[node]\nname = "n1"\n', '[node]\nname = "n1"'):
            with self.subTest(text=text):
                out = pc.add_seat(text, "code", "builds")
                self.assertEqual(tomllib.loads(out)["agents"], {"code": "builds"})
                self.assertTrue(out.startswith(text))

    def test_an_empty_agents_table_and_a_missing_final_newline(self):
        self.assertEqual(pc.add_seat("[agents]", "code", "b"), '[agents]\ncode = "b"\n')
        self.assertEqual(
            pc.add_seat('[agents]\nchat = "c"', "code", "b"), '[agents]\nchat = "c"\ncode = "b"\n'
        )

    def test_refusals(self):
        cases = {
            "upper case": (_STARTER, "TG-dev", "x"),
            "a space": (_STARTER, "tg dev", "x"),
            "leading dash": (_STARTER, "-tg", "x"),
            "too long": (_STARTER, "a" * 41, "x"),
            "no lane": (_STARTER, "tg-dev", "  "),
            "a newline in the lane": (_STARTER, "tg-dev", "one\ntwo"),
            "a long lane": (_STARTER, "tg-dev", "x" * 201),
            "already there": (_STARTER, "code", "again"),
            "allowed-list form": ('[agents]\nallowed = ["code"]\n', "tg-dev", "x"),
            "broken toml": ("[agents\n", "tg-dev", "x"),
            "inline agents": ('agents = { code = "b" }\n', "tg-dev", "x"),
        }
        for label, (text, seat, lane) in cases.items():
            with self.subTest(label), self.assertRaises(ValueError):
                pc.add_seat(text, seat, lane)


if __name__ == "__main__":
    unittest.main()
