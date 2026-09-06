"""The registry: slugs, the JSON-per-user store (ADR-0007), keys at rest (ADR-0008)."""

import hashlib
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

from boonyardnn.registry import (
    RESERVED_SLUGS,
    Registry,
    RegistryError,
    SlugError,
    hash_key,
    mint_key,
    validate_slug,
)


class SlugTests(unittest.TestCase):
    def test_valid_shapes(self):
        for slug in ("a", "jacoboon", "test-0", "a-b-c", "a" * 40, "0day"):
            self.assertEqual(validate_slug(slug), slug)

    def test_invalid_shapes(self):
        for slug in ("", "A", "-a", "a-", "a--", "a" * 41, "a_b", "a.b", "a/b", "..", "é"):
            with self.subTest(slug=slug), self.assertRaises(SlugError):
                validate_slug(slug)

    def test_reserved_names_are_refused(self):
        for name in ("_aggregate", "api", "admin", "health", "static", "www", "mcp", "sse"):
            self.assertIn(name, RESERVED_SLUGS)
            with self.subTest(name=name), self.assertRaises(SlugError):
                validate_slug(name)

    def test_uppercase_is_not_silently_lowercased(self):
        with self.assertRaises(SlugError):
            validate_slug("Jacoboon")


class KeyMaterialTests(unittest.TestCase):
    def test_mint_key_shape(self):
        raw = mint_key()
        self.assertTrue(raw.startswith("bnyk_"))
        self.assertEqual(len(raw), len("bnyk_") + 64)  # token_hex(32) → 64 hex chars
        self.assertNotEqual(raw, mint_key())

    def test_hash_is_sha256_hex(self):
        raw = "bnyk_" + "ab" * 32
        self.assertEqual(hash_key(raw), hashlib.sha256(raw.encode()).hexdigest())


class RegistryTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "data"
        self.reg = Registry(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    @staticmethod
    def _fake_init(node_dir: Path) -> str:
        (node_dir / "journal.db").write_bytes(b"")
        return "node-uuid-" + node_dir.name


class UserTests(RegistryTestCase):
    def test_create_user_layout(self):
        user = self.reg.create_user("alice", "alice@example.test")
        self.assertEqual(user.slug, "alice")
        self.assertEqual(user.plan, "free")
        self.assertEqual(user.status, "active")
        udir = self.root / "users" / user.user_id
        self.assertTrue((udir / "metadata.json").exists())
        self.assertTrue((udir / "api_keys.json").exists())
        self.assertTrue((udir / "nodes").is_dir())
        self.assertTrue((udir / "exports").is_dir())
        index = json.loads((self.root / "users.json").read_text())
        self.assertEqual(index["users"]["alice"], user.user_id)

    def test_user_id_is_a_uuid_not_derived_from_slug_or_email(self):
        user = self.reg.create_user("alice", "alice@example.test")
        self.assertEqual(len(user.user_id), 36)
        self.assertNotIn("alice", user.user_id)

    def test_taken_slug_refused(self):
        self.reg.create_user("alice", "alice@example.test")
        with self.assertRaises(RegistryError):
            self.reg.create_user("alice", "other@example.test")

    def test_bad_slug_refused_before_touching_disk(self):
        with self.assertRaises(SlugError):
            self.reg.create_user("admin", "x@example.test")
        self.assertFalse((self.root / "users.json").exists())

    def test_get_and_list(self):
        self.assertIsNone(self.reg.get_user("nobody"))
        self.reg.create_user("bob", "bob@example.test")
        self.reg.create_user("alice", "alice@example.test")
        self.assertEqual(self.reg.get_user("bob").email, "bob@example.test")
        self.assertEqual([u.slug for u in self.reg.list_users()], ["alice", "bob"])


class NodeTests(RegistryTestCase):
    def test_create_node_calls_init_and_records_it(self):
        user = self.reg.create_user("alice", "alice@example.test")
        node = self.reg.create_node(user, "n1", init=self._fake_init)
        self.assertEqual(node.node_id, "node-uuid-n1")
        self.assertEqual(node.owner_id, user.user_id)
        ndir = self.reg.node_dir(user, node)
        self.assertEqual(ndir, self.root / "users" / user.user_id / "nodes" / "n1")
        self.assertTrue((ndir / "backups").is_dir())
        self.assertEqual(node.storage_path, ndir.relative_to(self.root).as_posix())
        self.assertEqual(self.reg.get_node(user, "n1"), node)
        self.assertEqual([n.slug for n in self.reg.list_nodes(user)], ["n1"])

    def test_duplicate_node_slug_refused(self):
        user = self.reg.create_user("alice", "alice@example.test")
        self.reg.create_node(user, "n1", init=self._fake_init)
        with self.assertRaises(RegistryError):
            self.reg.create_node(user, "n1", init=self._fake_init)

    def test_reserved_node_slug_refused(self):
        user = self.reg.create_user("alice", "alice@example.test")
        with self.assertRaises(SlugError):
            self.reg.create_node(user, "_aggregate", init=self._fake_init)

    def test_node_slugs_are_per_user(self):
        a = self.reg.create_user("alice", "alice@example.test")
        b = self.reg.create_user("bob", "bob@example.test")
        self.reg.create_node(a, "n1", init=self._fake_init)
        self.reg.create_node(b, "n1", init=self._fake_init)
        self.assertIsNotNone(self.reg.get_node(a, "n1"))
        self.assertIsNotNone(self.reg.get_node(b, "n1"))
        self.assertEqual(self.reg.counts(), {"users": 2, "nodes": 2})


class KeyTests(RegistryTestCase):
    def setUp(self):
        super().setUp()
        self.user = self.reg.create_user("alice", "alice@example.test")
        self.node = self.reg.create_node(self.user, "n1", init=self._fake_init)

    def _store_text(self) -> str:
        return (self.root / "users" / self.user.user_id / "api_keys.json").read_text()

    def test_create_key_stores_hash_only(self):
        raw, key = self.reg.create_key(self.user, self.node, label="code seat")
        self.assertTrue(raw.startswith("bnyk_"))
        self.assertEqual(key.hashed_secret, hash_key(raw))
        self.assertEqual(key.scope, f"node:{self.node.node_id}")
        self.assertEqual(key.label, "code seat")
        self.assertIsNone(key.last_used_at)
        self.assertIsNone(key.revoked_at)
        self.assertNotIn(raw, self._store_text())
        self.assertIn(key.hashed_secret, self._store_text())

    def test_authenticate(self):
        raw, key = self.reg.create_key(self.user, self.node)
        self.assertEqual(self.reg.authenticate(self.user, raw).key_id, key.key_id)
        self.assertIsNone(self.reg.authenticate(self.user, "bnyk_" + "0" * 64))
        self.assertIsNone(self.reg.authenticate(self.user, ""))
        self.assertIsNone(
            self.reg.authenticate(self.user, key.hashed_secret)
        )  # the hash is not the key

    def test_revoked_key_no_longer_authenticates_but_keeps_its_row(self):
        raw, key = self.reg.create_key(self.user, self.node)
        revoked = self.reg.revoke_key(key.key_id)
        self.assertIsNotNone(revoked.revoked_at)
        self.assertIsNone(self.reg.authenticate(self.user, raw))
        rows = self.reg.list_keys(self.user, self.node)
        self.assertEqual([k.key_id for k in rows], [key.key_id])
        self.assertIsNotNone(rows[0].revoked_at)

    def test_revoke_unknown_key(self):
        with self.assertRaises(RegistryError):
            self.reg.revoke_key("no-such-key")

    def test_touch_updates_last_used_coarsely(self):
        _raw, key = self.reg.create_key(self.user, self.node)
        self.assertTrue(self.reg.touch_key(self.user, key.key_id, now="2026-09-06T20:00:00+00:00"))
        # Within the interval → no write.
        self.assertFalse(self.reg.touch_key(self.user, key.key_id, now="2026-09-06T20:00:30+00:00"))
        self.assertTrue(self.reg.touch_key(self.user, key.key_id, now="2026-09-06T20:02:00+00:00"))
        [row] = self.reg.list_keys(self.user, self.node)
        self.assertEqual(row.last_used_at, "2026-09-06T20:02:00+00:00")

    def test_keys_are_scoped_to_their_node(self):
        other = self.reg.create_node(self.user, "n2", init=self._fake_init)
        self.reg.create_key(self.user, self.node)
        self.reg.create_key(self.user, other)
        self.assertEqual(len(self.reg.list_keys(self.user, self.node)), 1)
        self.assertEqual(len(self.reg.list_keys(self.user, other)), 1)


@unittest.skipIf(
    os.name == "nt",
    "POSIX file modes are not enforceable on Windows (the laptop); the droplet is Linux",
)
class PosixModeTests(RegistryTestCase):
    def _mode(self, path: Path) -> int:
        return stat.S_IMODE(os.stat(path).st_mode)

    def test_user_dir_node_dir_and_key_file_modes(self):
        user = self.reg.create_user("alice", "alice@example.test")
        node = self.reg.create_node(user, "n1", init=self._fake_init)
        self.reg.create_key(user, node)
        udir = self.root / "users" / user.user_id
        self.assertEqual(self._mode(udir), 0o700)
        self.assertEqual(self._mode(self.reg.node_dir(user, node)), 0o700)
        self.assertEqual(self._mode(udir / "api_keys.json"), 0o600)
        self.assertEqual(self._mode(udir / "metadata.json"), 0o600)
