"""The provisioner: user → node → key lifecycle on a tmp root; the export path."""

import unittest
import zipfile
from pathlib import Path

from boonyardnn import adapter, provisioner
from boonyardnn.registry import RegistryError, SlugError

from .support import TmpRoot, payload_of, tool_call


class LifecycleTests(unittest.TestCase):
    def test_user_node_key_lifecycle(self):
        with TmpRoot() as t:
            user = provisioner.add_user(t.registry, "jacoboon", "jacob@example.test")
            node = provisioner.add_node(t.registry, "jacoboon", "test-0")
            raw, key = provisioner.add_key(t.registry, "jacoboon", "test-0", label="code")
            self.assertEqual(node.owner_id, user.user_id)
            self.assertEqual(key.scope, f"node:{node.node_id}")
            self.assertTrue(raw.startswith("bnyk_"))
            self.assertEqual(t.registry.authenticate(user, raw).key_id, key.key_id)

    def test_node_dir_is_a_real_initialised_node(self):
        # umbrella #315's stub trap: the journal must be the package's own init,
        # never a bare sqlite file. node_id == the journal's own meta.node_uuid.
        with TmpRoot() as t:
            provisioner.add_user(t.registry, "alice", "alice@example.test")
            node = provisioner.add_node(t.registry, "alice", "n1")
            ndir = t.root / node.storage_path
            self.assertTrue((ndir / "journal.db").exists())
            self.assertTrue((ndir / "boonyard.toml").exists())
            self.assertTrue((ndir / "backups").is_dir())
            self.assertEqual(node.node_id, adapter.node_uuid(ndir / "journal.db"))
            self.assertEqual(adapter.entry_count(ndir / "journal.db"), 0)
            self.assertIn('name = "n1"', (ndir / "boonyard.toml").read_text())

    def test_node_add_with_custom_profile(self):
        with TmpRoot() as t:
            provisioner.add_user(t.registry, "alice", "alice@example.test")
            custom = t.root.parent / "custom.toml"
            custom.write_text('[node]\nname = "custom"\n\n[agents]\nwarden = "the warden"\n')
            node = provisioner.add_node(t.registry, "alice", "n1", profile_path=custom)
            self.assertEqual(
                (t.root / node.storage_path / "boonyard.toml").read_text(), custom.read_text()
            )

    def test_unknown_user_or_node(self):
        with TmpRoot() as t:
            with self.assertRaises(RegistryError):
                provisioner.add_node(t.registry, "nobody", "n1")
            provisioner.add_user(t.registry, "alice", "alice@example.test")
            with self.assertRaises(RegistryError):
                provisioner.add_key(t.registry, "alice", "no-such-node")
            with self.assertRaises(RegistryError):
                provisioner.export_node(t.registry, "alice", "no-such-node")

    def test_reserved_and_malformed_slugs(self):
        with TmpRoot() as t:
            for bad in ("admin", "mcp", "Alice", "a_b", ""):
                with self.subTest(slug=bad), self.assertRaises(SlugError):
                    provisioner.add_user(t.registry, bad, "x@example.test")
            provisioner.add_user(t.registry, "alice", "alice@example.test")
            with self.assertRaises(SlugError):
                provisioner.add_node(t.registry, "alice", "_aggregate")

    def test_revoke(self):
        with TmpRoot() as t:
            raw = t.provision("alice", "n1")
            user = t.registry.get_user("alice")
            [key] = t.registry.list_keys(user, t.registry.get_node(user, "n1"))
            provisioner.revoke_key(t.registry, key.key_id)
            self.assertIsNone(t.registry.authenticate(user, raw))


class RawKeyNeverAtRestTests(unittest.TestCase):
    def test_raw_key_appears_nowhere_under_the_root(self):
        with TmpRoot() as t:
            raw = t.provision("alice", "n1", label="seat")
            hits = [p for p in t.root.rglob("*") if p.is_file() and raw.encode() in p.read_bytes()]
            self.assertEqual(hits, [])


class ExportTests(unittest.TestCase):
    def test_export_bundle_round_trips_through_the_package_import(self):
        with TmpRoot() as t:
            t.provision("alice", "n1")
            user = t.registry.get_user("alice")
            node = t.registry.get_node(user, "n1")
            db = t.root / node.storage_path / "journal.db"
            server = adapter.make_server(db)
            for i in range(3):
                resp = server.handle(
                    tool_call(
                        "log_entry", {"agent": "code", "entry_type": "note", "content": f"e{i}"}
                    )
                )
                self.assertIn("result", resp)
            self.assertEqual(
                payload_of(server.handle(tool_call("recent", {"limit": 1})))[0]["content"], "e2"
            )

            bundle = provisioner.export_node(
                t.registry, "alice", "n1", now="2026-09-06T21:00:00+00:00"
            )
            self.assertEqual(
                bundle, t.root / "users" / user.user_id / "exports" / "export_20260906T210000Z.zip"
            )
            with zipfile.ZipFile(bundle) as zf:
                self.assertIn("journal.db", zf.namelist())
                self.assertIn("boonyard.toml", zf.namelist())

            scratch = Path(t.root.parent) / "scratch" / "journal.db"
            adapter.import_node(bundle, scratch)
            self.assertEqual(adapter.entry_count(scratch), 3)
            self.assertEqual(adapter.node_uuid(scratch), node.node_id)


class UrlTests(unittest.TestCase):
    def test_key_urls_two_forms(self):
        urls = provisioner.key_urls("https://mcp.boonyardnn.com", "jacoboon", "test-0", "bnyk_x")
        self.assertEqual(urls["header"], "https://mcp.boonyardnn.com/jacoboon/test-0")
        self.assertEqual(urls["capability"], "https://mcp.boonyardnn.com/jacoboon/test-0/bnyk_x")

    def test_trailing_slash_on_base_is_tolerated(self):
        urls = provisioner.key_urls("http://127.0.0.1:8800/", "a", "b", "bnyk_x")
        self.assertEqual(urls["header"], "http://127.0.0.1:8800/a/b")
