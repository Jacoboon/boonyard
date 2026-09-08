"""ADR-0014 at the router: ``/{user}`` — one door, every node the key reaches.

The package half is proven in the package's own suite (`tests/test_account_door.py`,
including the assertion that aggregator mode still refuses writes). This file proves
the SaaS half: the route, the `user:` scope, per-ACCOUNT rate accounting, and the node
map that is rebuilt on every request so a node created a minute ago is reachable
without a restart.
"""

import unittest

from boonyardnn import provisioner
from boonyardnn.registry import Registry
from boonyardnn.router import Router

from .support import ServedRouter, TmpRoot, payload_of, rpc, tool_call


class AccountDoorCase(unittest.TestCase):
    def setUp(self):
        self._root = TmpRoot().__enter__()
        self.addCleanup(self._root.__exit__, None, None, None)
        self.reg: Registry = self._root.registry
        # alice owns two nodes; the node key is for n1 only.
        self.node_key = self._root.provision("alice", "n1", label="n1 seat")
        provisioner.add_node(self.reg, "alice", "n2")
        self.account_key, self.account_record = provisioner.add_account_key(
            self.reg, "alice", label="laptop"
        )
        self.served = ServedRouter(self.reg).__enter__()
        self.addCleanup(self.served.__exit__, None, None, None)

    def account(self, request, key=None):
        return self.served.post(
            "/alice", request, {"Authorization": f"Bearer {key or self.account_key}"}
        )

    def counts(self):
        user = self.reg.get_user("alice")
        out = {}
        for node in self.reg.list_nodes(user):
            body = self.served.post(
                f"/alice/{node.slug}",
                tool_call("recent", {"limit": 1000}),
                {"Authorization": f"Bearer {self.account_key}"},
            )[1]
            out[node.slug] = len(payload_of(body))
        return out


class RouteTests(AccountDoorCase):
    def test_the_account_door_lists_twenty_tools_with_node_required_on_writes(self):
        status, body, _ = self.account(rpc("tools/list"))
        self.assertEqual(status, 200)
        schemas = {t["name"]: t["inputSchema"] for t in body["result"]["tools"]}
        self.assertEqual(len(schemas), 20)
        for tool in ("log_entry", "log_skill_revision"):
            self.assertIn("node", schemas[tool]["required"], tool)

    def test_the_per_node_door_still_advertises_no_node(self):
        status, body, _ = self.served.post(
            "/alice/n1", rpc("tools/list"), {"Authorization": f"Bearer {self.node_key}"}
        )
        self.assertEqual(status, 200)
        schemas = {t["name"]: t["inputSchema"] for t in body["result"]["tools"]}
        self.assertNotIn("node", schemas["log_entry"]["required"])

    def test_list_nodes_returns_every_node_the_key_reaches(self):
        _status, body, _ = self.account(tool_call("list_nodes"))
        self.assertEqual({n["name"] for n in payload_of(body)}, {"n1", "n2"})

    def test_the_transport_suffix_still_reaches_the_account_door(self):
        status, body, _ = self.account(rpc("tools/list"))
        suffixed = self.served.post(
            "/alice/sse", rpc("tools/list"), {"Authorization": f"Bearer {self.account_key}"}
        )
        self.assertEqual(suffixed[0], status)
        self.assertEqual(len(suffixed[1]["result"]["tools"]), len(body["result"]["tools"]))


class ScopeTests(AccountDoorCase):
    def test_a_node_key_at_the_account_door_is_refused(self):
        status, body, _ = self.account(rpc("tools/list"), key=self.node_key)
        self.assertEqual(status, 403)
        self.assertIn("scoped to a single node", body["error"]["message"])

    def test_the_same_node_key_still_works_at_its_own_node(self):
        status, _body, _ = self.served.post(
            "/alice/n1", rpc("tools/list"), {"Authorization": f"Bearer {self.node_key}"}
        )
        self.assertEqual(status, 200)

    def test_an_account_key_is_a_superset_and_works_at_a_node_door(self):
        status, _body, _ = self.served.post(
            "/alice/n2", rpc("tools/list"), {"Authorization": f"Bearer {self.account_key}"}
        )
        self.assertEqual(status, 200)

    def test_no_key_is_401(self):
        status, _body, _ = self.served.post("/alice", rpc("tools/list"), {})
        self.assertEqual(status, 401)

    def test_another_users_account_key_is_not_authenticated_here(self):
        self._root.provision("bob", "b1")
        other, _ = provisioner.add_account_key(self.reg, "bob")
        status, _body, _ = self.account(rpc("tools/list"), key=other)
        self.assertEqual(status, 401)

    def test_a_revoked_account_key_stops_working(self):
        provisioner.revoke_key(self.reg, self.account_record.key_id)
        self.assertEqual(self.account(rpc("tools/list"))[0], 401)


class WriteTests(AccountDoorCase):
    def test_a_write_lands_in_the_node_it_names(self):
        before = self.counts()
        status, body, _ = self.account(
            tool_call(
                "log_entry",
                {"agent": "code", "entry_type": "note", "content": "for n2", "node": "n2"},
            )
        )
        self.assertEqual(status, 200)
        self.assertIsInstance(payload_of(body)["id"], int)
        after = self.counts()
        self.assertEqual(after["n2"], before["n2"] + 1)
        self.assertEqual(after["n1"], before["n1"], "the write leaked into another node")

    def test_a_write_with_no_node_is_refused(self):
        status, body, _ = self.account(
            tool_call("log_entry", {"agent": "code", "entry_type": "note", "content": "x"})
        )
        self.assertEqual(status, 200)  # a JSON-RPC error rides a 200
        self.assertIn("'node'", body["error"]["message"])

    def test_an_unknown_node_names_the_available_ones(self):
        status, body, _ = self.account(
            tool_call(
                "log_entry", {"agent": "code", "entry_type": "note", "content": "x", "node": "nope"}
            )
        )
        self.assertEqual(status, 200)
        message = body["error"]["message"]
        self.assertIn("n1", message)
        self.assertIn("n2", message)

    def test_a_read_spans_the_nodes_and_names_each_source(self):
        for slug in ("n1", "n2"):
            self.account(
                tool_call(
                    "log_entry",
                    {
                        "agent": "code",
                        "entry_type": "note",
                        "content": f"hello {slug}",
                        "node": slug,
                    },
                )
            )
        _status, body, _ = self.account(tool_call("recent", {"limit": 50}))
        self.assertEqual({r["source"] for r in payload_of(body)}, {"n1", "n2"})


class LiveMapTests(AccountDoorCase):
    def test_a_node_created_after_the_connector_is_reachable_with_no_restart(self):
        """The promise the ADR is named for — and the reason the map is per request."""
        provisioner.add_node(self.reg, "alice", "n3")
        _status, body, _ = self.account(tool_call("list_nodes"))
        self.assertIn("n3", {n["name"] for n in payload_of(body)})
        status, body, _ = self.account(
            tool_call(
                "log_entry",
                {
                    "agent": "code",
                    "entry_type": "note",
                    "content": "born after the connector",
                    "node": "n3",
                },
            )
        )
        self.assertEqual(status, 200)
        self.assertIsInstance(payload_of(body)["id"], int)

    def test_building_the_map_is_cheap_enough_to_do_every_time(self):
        for i in range(48):
            provisioner.add_node(self.reg, "alice", f"bulk-{i}")
        self.account(tool_call("list_nodes"))
        per_request = self.served.router.last_node_map_ms
        self.assertLess(per_request, 250.0, f"node map took {per_request:.1f} ms for 50 nodes")


class LimitTests(unittest.TestCase):
    """ADR-0014 §7: an account key's bucket is the ACCOUNT, so more keys ≠ more ceiling."""

    def setUp(self):
        self._root = TmpRoot().__enter__()
        self.addCleanup(self._root.__exit__, None, None, None)
        self.reg = self._root.registry
        self._root.provision("alice", "n1")
        self.k1, _ = provisioner.add_account_key(self.reg, "alice", label="one")
        self.k2, _ = provisioner.add_account_key(self.reg, "alice", label="two")
        # two reads a minute, burst 1: the third read of the minute must wait.
        self.router = Router(self.reg, limits={"free": (2, 2)}, burst=1)
        self.served = ServedRouter(self.reg, router=self.router).__enter__()
        self.addCleanup(self.served.__exit__, None, None, None)

    def _read(self, key):
        return self.served.post("/alice", rpc("tools/list"), {"Authorization": f"Bearer {key}"})[0]

    def test_two_account_keys_share_one_bucket(self):
        self.assertEqual(self._read(self.k1), 200)
        self.assertEqual(self._read(self.k2), 200)
        self.assertEqual(self._read(self.k2), 429, "minting a second key doubled the ceiling")

    def test_the_429_says_per_account(self):
        for _ in range(3):
            status, body, headers = self.served.post(
                "/alice", rpc("tools/list"), {"Authorization": f"Bearer {self.k1}"}
            )
        self.assertEqual(status, 429)
        self.assertIn("per account", body["error"]["message"])
        self.assertTrue(headers.get("Retry-After"))


class AggregateStillReadOnlyTests(AccountDoorCase):
    def test_the_router_has_no_aggregate_endpoint_and_says_404(self):
        """`/{user}/_aggregate` is Phase 3 and was never built here — and an underscore
        is not a legal slug, so it cannot be mistaken for a node either."""
        status, _body, _ = self.served.post(
            "/alice/_aggregate",
            rpc("tools/list"),
            {"Authorization": f"Bearer {self.account_key}"},
        )
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main(verbosity=2)
