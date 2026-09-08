"""The router: one door, per-request dispatch to ``MCPServer.handle()`` (ADR-0008)."""

import contextlib
import io
import json
import logging
import unittest

from boonyardnn import adapter
from boonyardnn.router import Router

from .support import ServedRouter, TmpRoot, payload_of, rpc, tool_call


class PathParseTests(unittest.TestCase):
    def test_shapes(self):
        p = Router.parse_path
        self.assertEqual(p("/alice/n1"), ("alice", "n1", None))
        self.assertEqual(p("/alice/n1/"), ("alice", "n1", None))
        self.assertEqual(p("/alice/n1/bnyk_abc"), ("alice", "n1", "bnyk_abc"))
        self.assertEqual(p("/alice/n1?x=1"), ("alice", "n1", None))
        # ADR-0008 spells the URL with a transport suffix; tolerate it.
        self.assertEqual(p("/alice/n1/sse"), ("alice", "n1", None))
        self.assertEqual(p("/alice/n1/http/bnyk_abc"), ("alice", "n1", "bnyk_abc"))

    def test_rejects(self):
        p = Router.parse_path
        for bad in (
            "/",
            "/alice/n1/bnyk_a/extra",
            "/Alice/n1",
            "/../n1",
            "/alice/n1/sse/x/y",
        ):
            with self.subTest(path=bad):
                self.assertIsNone(p(bad))


class RouterHttpTestCase(unittest.TestCase):
    def setUp(self):
        self._root = TmpRoot().__enter__()
        self.addCleanup(self._root.__exit__, None, None, None)
        self.reg = self._root.registry
        self.raw = self._root.provision("alice", "n1", label="seat")
        self.served = ServedRouter(self.reg).__enter__()
        self.addCleanup(self.served.__exit__, None, None, None)

    def bearer(self, raw: str | None = None) -> dict:
        return {"Authorization": f"Bearer {raw or self.raw}"}


class ToolSurfaceTests(RouterHttpTestCase):
    def test_tools_list_is_the_packages_tools(self):
        status, body, _ = self.served.post("/alice/n1", rpc("tools/list"), self.bearer())
        self.assertEqual(status, 200)
        names = sorted(t["name"] for t in body["result"]["tools"])
        self.assertEqual(len(names), 20)  # 18 at 3.2.0; instructions + ghosts at 3.3.0
        self.assertEqual(names, sorted(adapter.tool_names()))
        self.assertNotIn("retag", names)

    def test_initialize(self):
        status, body, _ = self.served.post("/alice/n1", rpc("initialize"), self.bearer())
        self.assertEqual(status, 200)
        self.assertEqual(body["result"]["serverInfo"]["name"], "boonyard")

    def test_log_entry_then_recent_round_trip(self):
        status, body, _ = self.served.post(
            "/alice/n1",
            tool_call(
                "log_entry", {"agent": "code", "entry_type": "note", "content": "hello wall"}
            ),
            self.bearer(),
        )
        self.assertEqual(status, 200)
        new_id = payload_of(body)["id"]
        status, body, _ = self.served.post(
            "/alice/n1", tool_call("recent", {"limit": 1}), self.bearer()
        )
        [entry] = payload_of(body)
        self.assertEqual(entry["id"], new_id)
        self.assertEqual(entry["content"], "hello wall")

    def test_meter_sidecar_lives_in_the_node_dir(self):
        self.served.post("/alice/n1", tool_call("recent"), self.bearer())
        user = self.reg.get_user("alice")
        ndir = self.reg.node_dir(user, self.reg.get_node(user, "n1"))
        self.assertTrue((ndir / "meter.db").exists())
        status, body, _ = self.served.post("/alice/n1", tool_call("read_stats"), self.bearer())
        self.assertGreaterEqual(payload_of(body)["totals"]["reads"], 1)

    def test_notification_is_202_no_body(self):
        status, body, _ = self.served.post(
            "/alice/n1", {"jsonrpc": "2.0", "method": "notifications/initialized"}, self.bearer()
        )
        self.assertEqual(status, 202)
        self.assertIsNone(body)

    def test_malformed_json_is_400(self):
        status, body, _ = self.served.post("/alice/n1", b"{not json", self.bearer())
        self.assertEqual(status, 400)
        self.assertEqual(body["error"]["data"]["error"], "validation")


class AuthTests(RouterHttpTestCase):
    def test_header_form_accepted(self):
        status, _, _ = self.served.post("/alice/n1", rpc("tools/list"), self.bearer())
        self.assertEqual(status, 200)

    def test_capability_url_form_accepted(self):
        status, body, _ = self.served.post(f"/alice/n1/{self.raw}", rpc("tools/list"))
        self.assertEqual(status, 200)
        self.assertIn("log_entry", {t["name"] for t in body["result"]["tools"]})

    def test_transport_suffix_tolerated(self):
        status, _, _ = self.served.post("/alice/n1/sse", rpc("tools/list"), self.bearer())
        self.assertEqual(status, 200)

    def test_no_key_is_401(self):
        status, body, _ = self.served.post("/alice/n1", rpc("tools/list"))
        self.assertEqual(status, 401)
        self.assertEqual(body["error"]["data"]["error"], "not_authenticated")

    def test_wrong_key_is_401(self):
        status, _, _ = self.served.post(
            "/alice/n1", rpc("tools/list"), self.bearer("bnyk_" + "0" * 64)
        )
        self.assertEqual(status, 401)
        status, _, _ = self.served.post("/alice/n1/bnyk_" + "0" * 64, rpc("tools/list"))
        self.assertEqual(status, 401)

    def test_revoked_key_is_401(self):
        user = self.reg.get_user("alice")
        [key] = self.reg.list_keys(user, self.reg.get_node(user, "n1"))
        self.reg.revoke_key(key.key_id)
        status, body, _ = self.served.post("/alice/n1", rpc("tools/list"), self.bearer())
        self.assertEqual(status, 401)
        self.assertEqual(body["error"]["data"]["error"], "not_authenticated")

    def test_same_user_key_for_another_node_is_403(self):
        other_raw = self._root.provision("alice", "n2")
        status, body, _ = self.served.post("/alice/n1", rpc("tools/list"), self.bearer(other_raw))
        self.assertEqual(status, 403)
        self.assertEqual(body["error"]["data"]["error"], "not_authorized")

    def test_user_a_key_cannot_read_user_b_node_adr_0007_isolation(self):
        # ADR-0007's isolation clause: user A's tooling must not reach user B's data.
        # Only the TARGET user's key file is ever consulted, so A's key is simply
        # unknown at B's door — 401, and B's node is never opened.
        raw_b = self._root.provision("bob", "n1")
        self.served.post(
            "/bob/n1",
            tool_call(
                "log_entry", {"agent": "code", "entry_type": "note", "content": "bob's secret"}
            ),
            self.bearer(raw_b),
        )
        status, body, _ = self.served.post("/bob/n1", tool_call("recent"), self.bearer(self.raw))
        self.assertEqual(status, 401)
        self.assertNotIn("bob's secret", json.dumps(body))
        status, body, _ = self.served.post(f"/bob/n1/{self.raw}", tool_call("recent"))
        self.assertEqual(status, 401)
        # And the reverse: B's key at A's door.
        status, _, _ = self.served.post("/alice/n1", tool_call("recent"), self.bearer(raw_b))
        self.assertEqual(status, 401)

    def test_last_used_at_is_touched(self):
        user = self.reg.get_user("alice")
        node = self.reg.get_node(user, "n1")
        [before] = self.reg.list_keys(user, node)
        self.assertIsNone(before.last_used_at)
        self.served.post("/alice/n1", rpc("tools/list"), self.bearer())
        [after] = self.reg.list_keys(user, node)
        self.assertIsNotNone(after.last_used_at)


class NotFoundAndMethodTests(RouterHttpTestCase):
    def test_unknown_node_is_404(self):
        status, body, _ = self.served.post("/alice/nope", rpc("tools/list"), self.bearer())
        self.assertEqual(status, 404)
        self.assertEqual(body["error"]["data"]["error"], "not_found")

    def test_unknown_user_is_404_same_shape_as_unknown_node(self):
        s1, b1, _ = self.served.post("/nobody/n1", rpc("tools/list"), self.bearer())
        s2, b2, _ = self.served.post("/alice/nope", rpc("tools/list"), self.bearer())
        self.assertEqual((s1, b1), (s2, b2))

    def test_malformed_path_is_404(self):
        status, _, _ = self.served.post("/", rpc("tools/list"), self.bearer())
        self.assertEqual(status, 404)

    def test_a_node_key_at_the_account_door_is_refused_not_degraded(self):
        """ADR-0014 §9. /{user} is a real endpoint now; a node key must not open it."""
        status, body, _ = self.served.post("/alice", rpc("tools/list"), self.bearer())
        self.assertEqual(status, 403)
        self.assertIn("scoped to a single node", body["error"]["message"])

    def test_get_is_405_with_allow(self):
        status, body, headers = self.served.get("/alice/n1")
        self.assertEqual(status, 405)
        self.assertEqual(headers.get("Allow"), "POST")
        self.assertEqual(body["error"]["data"]["error"], "validation")

    def test_post_to_health_is_405(self):
        status, _, headers = self.served.post("/health", rpc("tools/list"))
        self.assertEqual(status, 405)
        self.assertEqual(headers.get("Allow"), "GET")


class HealthTests(RouterHttpTestCase):
    def test_health_lists_counts_and_no_slugs(self):
        self._root.provision("bob", "n1")
        status, body, _ = self.served.get("/health")
        self.assertEqual(status, 200)
        self.assertEqual(body["users"], 2)
        self.assertEqual(body["nodes"], 2)
        self.assertIn("version", body)
        self.assertIn("uptime_s", body)
        self.assertNotIn("alice", json.dumps(body))
        self.assertNotIn("bob", json.dumps(body))


class NeverLogTheUrlTests(RouterHttpTestCase):
    def test_url_and_key_never_appear_in_logs(self):
        stderr = io.StringIO()
        log_buf = io.StringIO()
        handler = logging.StreamHandler(log_buf)
        root = logging.getLogger()
        root.addHandler(handler)
        old_level = root.level
        root.setLevel(logging.DEBUG)
        try:
            with contextlib.redirect_stderr(stderr):
                self.served.post(f"/alice/n1/{self.raw}", rpc("tools/list"))
                self.served.post("/alice/n1", rpc("tools/list"), self.bearer())
                self.served.post("/alice/n1/bnyk_" + "1" * 64, rpc("tools/list"))
                self.served.get("/alice/n1/bnyk_" + "1" * 64)
                self.served.get("/health")
        finally:
            root.removeHandler(handler)
            root.setLevel(old_level)
        captured = stderr.getvalue() + log_buf.getvalue()
        self.assertNotIn(self.raw, captured)
        self.assertNotIn("bnyk_", captured)
        self.assertNotIn("/alice/n1", captured)
