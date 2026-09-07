"""Slice 3: the node browser, rate limits, the free cap, node tombstones, the backup config."""

import re
import tempfile
import tomllib
import unittest
import urllib.parse
from pathlib import Path

from boonyardnn import provisioner
from boonyardnn.accounts import Accounts
from boonyardnn.registry import NotFoundError, RegistryError
from boonyardnn.router import FREE_ENTRY_CAP, RateLimiter, Router, tier_of
from boonyardnn.web import PREFIX

from .support import ServedRouter, ServedWeb, TmpRoot, payload_of, rpc, tool_call

_KEY_RE = re.compile(rb"bnyk_[0-9a-f]{64}")


class _Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


# --------------------------------------------------------------------------
# registry / provisioner
# --------------------------------------------------------------------------
class RegistryTests(unittest.TestCase):
    def setUp(self):
        self._root = TmpRoot().__enter__()
        self.addCleanup(self._root.__exit__, None, None, None)
        self.reg = self._root.registry

    def test_set_plan_mirrors_and_validates(self):
        self.reg.create_user("alice", "a@example.test")
        user = self.reg.get_user("alice")
        self.assertEqual(user.plan, "free")
        self.assertEqual(self.reg.set_plan(user, "founder").plan, "founder")
        self.assertEqual(self.reg.get_user("alice").plan, "founder")
        with self.assertRaises(RegistryError):
            self.reg.set_plan(user, "not a plan")
        with self.assertRaises(NotFoundError):
            provisioner.set_plan(self.reg, "nobody", "free")

    def test_remove_node_tombstones_and_revokes(self):
        raw = self._root.provision("alice", "n1", label="seat")
        user = self.reg.get_user("alice")
        node = self.reg.get_node(user, "n1")
        src = self.reg.node_dir(user, node)
        self.assertTrue((src / "journal.db").exists())
        grave = provisioner.remove_node(self.reg, "alice", "n1")
        self.assertFalse(src.exists())
        self.assertTrue((grave / "journal.db").exists())
        self.assertIn(".tombstoned", grave.parts)
        self.assertIsNone(self.reg.get_node(user, "n1"))
        self.assertIsNone(self.reg.authenticate(user, raw))  # revoked
        self.assertEqual(self.reg.counts()["nodes"], 0)
        with self.assertRaises(NotFoundError):
            provisioner.remove_node(self.reg, "alice", "n1")
        # the slug is free again, and the old file is untouched by the new node
        provisioner.add_node(self.reg, "alice", "n1")
        self.assertTrue((grave / "journal.db").exists())

    def test_backup_config_lists_base_and_hosted_nodes(self):
        self._root.provision("alice", "n1")
        self._root.provision("bob", "wall-2")
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "umbrella.toml"
            base.write_text(
                "[nodes]\numbrella = '/var/lib/x/umbrella/journal.db'\n", encoding="utf-8"
            )
            text = provisioner.backup_config(self.reg, base)
        data = tomllib.loads(text)
        nodes = data["nodes"]
        self.assertEqual(nodes["umbrella"], "/var/lib/x/umbrella/journal.db")
        self.assertIn("alice__n1", nodes)
        self.assertIn("bob__wall-2", nodes)
        self.assertTrue(Path(nodes["alice__n1"]).exists())
        self.assertTrue(nodes["alice__n1"].endswith("journal.db"))
        self.assertEqual(len(nodes), 3)
        self.assertEqual(len(self.reg.all_nodes()), 2)
        # without a base file: hosted only
        self.assertEqual(
            list(tomllib.loads(provisioner.backup_config(self.reg))["nodes"]),
            ["alice__n1", "bob__wall-2"],
        )


# --------------------------------------------------------------------------
# router: rate limits + the free cap
# --------------------------------------------------------------------------
class RateLimiterTests(unittest.TestCase):
    def test_bucket_refills_with_time(self):
        clock = _Clock()
        rl = RateLimiter(burst=1, clock=clock)
        # rate 2/min, burst 1× -> capacity 2 tokens, one new token every 30 s
        self.assertEqual(rl.take("k", "write", 2), 0)
        self.assertEqual(rl.take("k", "write", 2), 0)
        wait = rl.take("k", "write", 2)
        self.assertGreaterEqual(wait, 1)
        self.assertLessEqual(wait, 30)
        clock.t += 30.0
        self.assertEqual(rl.take("k", "write", 2), 0)
        self.assertEqual(rl.take("other", "write", 2), 0)  # keys are independent
        # ADR-0008's burst: capacity is rate × 10
        big = RateLimiter(clock=clock)
        self.assertTrue(all(big.take("b", "write", 30) == 0 for _ in range(300)))
        self.assertGreaterEqual(big.take("b", "write", 30), 1)

    def test_tiers(self):
        self.assertEqual(tier_of("free"), "free")
        self.assertEqual(tier_of(None), "free")
        for plan in ("founder", "owner", "pro", "team"):
            self.assertEqual(tier_of(plan), "pro")


class RouterLimitTests(unittest.TestCase):
    def setUp(self):
        self._root = TmpRoot().__enter__()
        self.addCleanup(self._root.__exit__, None, None, None)
        self.reg = self._root.registry
        self.raw = self._root.provision("alice", "n1")
        self.clock = _Clock()

    def _served(self, **kw):
        served = ServedRouter(self.reg, router=Router(self.reg, clock=self.clock, **kw))
        served.__enter__()
        self.addCleanup(served.__exit__, None, None, None)
        return served

    def _post(self, served, body):
        return served.post("/alice/n1", body, {"Authorization": f"Bearer {self.raw}"})

    def test_write_limit_is_429_with_retry_after(self):
        served = self._served(limits={"free": (2, 100)}, burst=1)
        note = tool_call("log_entry", {"agent": "code", "entry_type": "note", "content": "x"})
        self.assertEqual(self._post(served, note)[0], 200)
        self.assertEqual(self._post(served, note)[0], 200)
        status, body, headers = self._post(served, note)
        self.assertEqual(status, 429)
        self.assertEqual(body["error"]["data"]["error"], "rate_limited")
        self.assertTrue(int(headers["Retry-After"]) >= 1)
        # reads are a separate bucket
        self.assertEqual(self._post(served, rpc("tools/list"))[0], 200)
        self.clock.t += 60.0
        self.assertEqual(self._post(served, note)[0], 200)

    def test_pro_plan_gets_the_pro_bucket(self):
        served = self._served(limits={"free": (1, 1), "pro": (100, 100)}, burst=1)
        user = self.reg.get_user("alice")
        self.reg.set_plan(user, "founder")
        note = tool_call("log_entry", {"agent": "code", "entry_type": "note", "content": "x"})
        for _ in range(5):
            self.assertEqual(self._post(served, note)[0], 200)

    def test_free_entry_cap_refuses_writes_but_not_reads(self):
        served = self._served(entry_cap=2)
        note = tool_call("log_entry", {"agent": "code", "entry_type": "note", "content": "x"})
        self.assertEqual(self._post(served, note)[0], 200)
        self.assertEqual(self._post(served, note)[0], 200)
        status, body, _ = self._post(served, note)
        self.assertEqual(status, 403)
        self.assertEqual(body["error"]["data"]["error"], "quota_exceeded")
        status, body, _ = self._post(served, tool_call("recent", {"limit": 5}))
        self.assertEqual(status, 200)
        self.assertEqual(len(payload_of(body)), 2)
        # founders are not capped
        self.reg.set_plan(self.reg.get_user("alice"), "founder")
        self.assertEqual(self._post(served, note)[0], 200)

    def test_default_cap_is_the_canon_number(self):
        self.assertEqual(FREE_ENTRY_CAP, 10_000)


# --------------------------------------------------------------------------
# the node browser, served
# --------------------------------------------------------------------------
class BrowserTests(unittest.TestCase):
    def setUp(self):
        self._root = TmpRoot().__enter__()
        self.addCleanup(self._root.__exit__, None, None, None)
        self.reg = self._root.registry
        self.acc = Accounts(self._root.root, founder_seats=2)
        self.web = ServedWeb(self.reg, self.acc).__enter__()
        self.addCleanup(self.web.__exit__, None, None, None)
        # sign up, verify, create a node
        self.web.post("/signup", {"email": "alice@example.test", "slug": "alice", "password": ""})
        link = self.web.last_link()
        self.web.get(link[link.index(PREFIX) + len(PREFIX) :])
        self.csrf = self.web.csrf()
        self.web.post("/nodes", {"csrf": self.csrf, "slug": "n1"})

    def test_plan_is_mirrored_into_the_registry_at_verify(self):
        self.assertEqual(self.reg.get_user("alice").plan, "founder")

    def test_dashboard_links_to_the_browser(self):
        status, _h, body = self.web.get("/")
        self.assertEqual(status, 200)
        self.assertIn(b'href="/app/nodes/n1">open</a>', body)

    def test_read_write_thread_search_retag(self):
        status, _h, body = self.web.get("/nodes/n1")
        self.assertEqual(status, 200)
        self.assertIn(b"Nothing here yet", body)
        self.assertIn(b"0 entries", body)
        # write
        status, headers, _b = self.web.post(
            "/nodes/n1/entries",
            {
                "csrf": self.csrf,
                "agent": "jacoboon",
                "entry_type": "decision",
                "content": "First <b>entry</b> from the browser",
                "tags": "decision, launch",
            },
        )
        self.assertEqual(status, 303)
        self.assertIn("/nodes/n1/entries/1?m=entry-written", headers["Location"])
        status, _h, body = self.web.get(headers["Location"][len(PREFIX) :])
        self.assertEqual(status, 200)
        self.assertIn(b"Entry written", body)
        self.assertIn(b"First &lt;b&gt;entry&lt;/b&gt; from the browser", body)  # escaped
        self.assertIn(b"jacoboon", body)
        self.assertIn(b"decision", body)
        # reply = the only kind of "edit"
        status, headers, _b = self.web.post(
            "/nodes/n1/entries",
            {
                "csrf": self.csrf,
                "agent": "jacoboon",
                "entry_type": "note",
                "content": "correction: it was the second",
                "related_id": "1",
                "tags": "",
            },
        )
        self.assertEqual(status, 303)
        status, _h, body = self.web.get("/nodes/n1/entries/1")
        self.assertIn(b"correction: it was the second", body)  # in the thread below #1
        status, _h, body = self.web.get("/nodes/n1/entries/2")
        self.assertIn(b"#1</a>", body)  # the parent link
        # search by text and by tag
        status, _h, body = self.web.get(
            "/nodes/n1/search?" + urllib.parse.urlencode({"q": "browser"})
        )
        self.assertEqual(status, 200)
        self.assertIn(b"from the browser", body)
        self.assertNotIn(b"correction: it was", body)
        status, _h, body = self.web.get("/nodes/n1/search?tag=launch")
        self.assertIn(b"from the browser", body)
        # retag with a reason; the content is untouched
        status, headers, _b = self.web.post(
            "/nodes/n1/entries/1/retag",
            {"csrf": self.csrf, "tags": "decision, soft-launch", "reason": "namespace fixed"},
        )
        self.assertEqual(status, 303)
        status, _h, body = self.web.get("/nodes/n1/entries/1")
        self.assertIn(b"soft-launch", body)
        self.assertIn(b"from the browser", body)
        status, _h, body = self.web.post(
            "/nodes/n1/entries/1/retag", {"csrf": self.csrf, "tags": "x", "reason": ""}
        )
        self.assertEqual(status, 400)
        # the router sees the same entries (same engine)
        with ServedRouter(self.reg) as router:
            raw, _key = provisioner.add_key(self.reg, "alice", "n1")
            status, resp, _h = router.post(
                "/alice/n1", tool_call("recent", {"limit": 5}), {"Authorization": f"Bearer {raw}"}
            )
            self.assertEqual([e["id"] for e in payload_of(resp)], [2, 1])

    def test_refusals(self):
        status, _h, body = self.web.post(
            "/nodes/n1/entries",
            {"csrf": self.csrf, "agent": "x", "entry_type": "note", "content": "  "},
        )
        self.assertEqual(status, 400)
        self.assertIn(b"Content is empty", body)
        status, _h, _b = self.web.post(
            "/nodes/n1/entries",
            {"csrf": "wrong", "agent": "x", "entry_type": "note", "content": "hi"},
        )
        self.assertEqual(status, 403)
        status, _h, _b = self.web.get("/nodes/nope")
        self.assertEqual(status, 404)
        status, _h, _b = self.web.get("/nodes/n1/entries/999")
        self.assertEqual(status, 404)
        status, _h, _b = self.web.get("/nodes/n1/entries/abc")
        self.assertEqual(status, 404)
        # another user's node is not reachable
        self._root.provision("bob", "bn")
        status, _h, _b = self.web.get("/nodes/bn")
        self.assertEqual(status, 404)
        # signed out: redirect
        self.web.cookies.clear()
        status, _h, _b = self.web.get("/nodes/n1")
        self.assertEqual(status, 303)

    def test_tombstone_needs_the_typed_name_and_revokes_keys(self):
        status, _h, body = self.web.post("/nodes/n1/keys", {"csrf": self.csrf, "label": "seat"})
        raw = _KEY_RE.search(body).group(0).decode()
        status, _h, body = self.web.post("/nodes/n1/delete", {"csrf": self.csrf, "confirm": "nope"})
        self.assertEqual(status, 400)
        self.assertIn(b"Type the node name", body)
        status, headers, _b = self.web.post(
            "/nodes/n1/delete", {"csrf": self.csrf, "confirm": "n1"}
        )
        self.assertEqual(status, 303)
        self.assertIn("m=node-removed", headers["Location"])
        status, _h, body = self.web.get("/?m=node-removed")
        self.assertIn(b"tombstoned", body)
        self.assertNotIn(b'href="/app/nodes/n1">open</a>', body)
        user = self.reg.get_user("alice")
        self.assertIsNone(self.reg.get_node(user, "n1"))
        self.assertIsNone(self.reg.authenticate(user, raw))
        graves = list((self._root.root / ".tombstoned").rglob("journal.db"))
        self.assertEqual(len(graves), 1)
        status, _h, _b = self.web.get("/nodes/n1")
        self.assertEqual(status, 404)
