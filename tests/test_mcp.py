"""M7 tests — the MCP server: tool surface, JSON-RPC dispatch, HTTP, read-only."""

import json
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

from boonyard import init_db, log_entry
from boonyard.aggregator import Aggregator
from boonyard.mcp import MCPServer, make_httpd


def _rpc(method, params=None, rid=1):
    return {"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}


def _call(server, name, args=None):
    """Call a tool and return (payload_or_None, error_or_None)."""
    resp = server.handle(_rpc("tools/call", {"name": name, "arguments": args or {}}))
    if "error" in resp:
        return None, resp["error"]
    text = resp["result"]["content"][0]["text"]
    return json.loads(text), None


class ToolSurfaceTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self._tmp.name) / "journal.db")
        init_db(self.db, node_name="test")
        self.server = MCPServer(db_path=self.db)

    def tearDown(self):
        self._tmp.cleanup()

    def test_initialize(self):
        resp = self.server.handle(_rpc("initialize"))
        self.assertEqual(resp["result"]["serverInfo"]["name"], "boonyard")
        self.assertIn("protocolVersion", resp["result"])

    def test_tools_list_is_the_canonical_set(self):
        resp = self.server.handle(_rpc("tools/list"))
        names = {t["name"] for t in resp["result"]["tools"]}
        expected = {
            "log_entry",
            "log_skill_revision",
            "recent",
            "by_id",
            "get_thread",
            "search_by_tag",
            "search_by_tag_exact",
            "search_text",
            "list_tags",
            "list_agents",
            "list_entry_types",
            "list_skills",
            "latest_skill",
            "list_nodes",
            "node_info",
            "audit_doctor",
        }
        self.assertEqual(names, expected)

    def test_retag_and_delete_are_not_tools(self):
        resp = self.server.handle(_rpc("tools/list"))
        names = {t["name"] for t in resp["result"]["tools"]}
        for forbidden in (
            "retag",
            "retag_entry",
            "delete_entry",
            "update_entry_content",
            "vector_search",
            "execute_sql",
        ):
            self.assertNotIn(forbidden, names)

    def test_notifications_get_no_response(self):
        self.assertIsNone(self.server.handle(_rpc("notifications/initialized")))

    def test_unknown_method(self):
        resp = self.server.handle(_rpc("frobnicate"))
        self.assertEqual(resp["error"]["data"]["error"], "validation")


class ToolCallTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self._tmp.name) / "journal.db")
        init_db(self.db, node_name="test")
        self.server = MCPServer(db_path=self.db)

    def tearDown(self):
        self._tmp.cleanup()

    def test_log_then_by_id(self):
        payload, err = _call(
            self.server,
            "log_entry",
            {"agent": "code", "entry_type": "note", "content": "over mcp", "tags": ["a", "b"]},
        )
        self.assertIsNone(err)
        new_id = payload["id"]
        entry, err = _call(self.server, "by_id", {"entry_id": new_id})
        self.assertEqual(entry["content"], "over mcp")
        self.assertEqual(set(entry["tags"]), {"a", "b", "note"})

    def test_log_entry_accepts_csv_tags_too(self):
        payload, _ = _call(
            self.server,
            "log_entry",
            {"agent": "code", "entry_type": "note", "content": "x", "tags": "p,q"},
        )
        entry, _ = _call(self.server, "by_id", {"entry_id": payload["id"]})
        self.assertIn("p", entry["tags"])

    def test_validation_error_shape(self):
        # missing required 'content'
        _, err = _call(self.server, "log_entry", {"agent": "code", "entry_type": "note"})
        self.assertEqual(err["data"]["error"], "validation")
        self.assertIn("message", err["data"])

    def test_unknown_tool_error(self):
        _, err = _call(self.server, "nonexistent_tool", {})
        self.assertEqual(err["data"]["error"], "validation")

    def test_search_text_and_tags(self):
        _call(
            self.server,
            "log_entry",
            {"agent": "code", "entry_type": "note", "content": "the quick fox", "tags": ["animal"]},
        )
        hits, _ = _call(self.server, "search_text", {"query": "quick"})
        self.assertEqual(len(hits), 1)
        tags, _ = _call(self.server, "list_tags", {})
        self.assertIn("animal", {t["tag"] for t in tags})

    def test_log_skill_revision_roots_by_slug(self):
        first, _ = _call(
            self.server,
            "log_skill_revision",
            {"slug": "fuse-boot", "content": "v1", "agent": "code"},
        )
        self.assertEqual(first["id"], first["root_id"])  # first revision is its own root
        second, _ = _call(
            self.server,
            "log_skill_revision",
            {"slug": "fuse-boot", "content": "v2", "agent": "code"},
        )
        self.assertEqual(second["root_id"], first["id"])  # anchored to the slug's root

    def test_node_info_and_audit_doctor(self):
        info, _ = _call(self.server, "node_info", {})
        self.assertEqual(info["schema_version"], 3)
        report, _ = _call(self.server, "audit_doctor", {})
        self.assertIn("warnings", report)

    def test_list_nodes_single(self):
        nodes, _ = _call(self.server, "list_nodes", {})
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0]["name"], "test")

    def test_all_single_node_readers_dispatch(self):
        root, _ = _call(
            self.server,
            "log_entry",
            {"agent": "code", "entry_type": "discussion", "content": "root", "tags": ["animal"]},
        )
        _call(
            self.server,
            "log_entry",
            {
                "agent": "code",
                "entry_type": "note",
                "content": "child",
                "related_id": root["id"],
                "tags": ["animal"],
            },
        )
        _call(
            self.server,
            "log_skill_revision",
            {"slug": "fuse-boot", "content": "SKILL: x", "agent": "code"},
        )
        # every reader returns a result with no error
        for name, args in [
            ("get_thread", {"root_id": root["id"]}),
            ("search_by_tag", {"tag": "animal"}),
            ("search_by_tag_exact", {"tag": "animal"}),
            ("list_agents", {}),
            ("list_entry_types", {}),
            ("list_skills", {}),
            ("latest_skill", {"slug": "fuse-boot"}),
        ]:
            payload, err = _call(self.server, name, args)
            self.assertIsNone(err, f"{name} errored: {err}")
            self.assertIsNotNone(payload)


class AggregatorModeTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        d = Path(self._tmp.name)
        self.a = str(d / "a" / "journal.db")
        self.b = str(d / "b" / "journal.db")
        init_db(self.a, node_name="alpha")
        init_db(self.b, node_name="beta")
        log_entry("code", "note", "from A", tags="shared", db_path=self.a)
        log_entry("code", "note", "from B", tags="shared", db_path=self.b)
        self.server = MCPServer(aggregator=Aggregator({"a": self.a, "b": self.b}))

    def tearDown(self):
        self._tmp.cleanup()

    def test_write_returns_read_only(self):
        _, err = _call(
            self.server, "log_entry", {"agent": "code", "entry_type": "note", "content": "nope"}
        )
        self.assertEqual(err["data"]["error"], "read_only")

    def test_skill_write_returns_read_only(self):
        _, err = _call(
            self.server, "log_skill_revision", {"slug": "x", "content": "y", "agent": "code"}
        )
        self.assertEqual(err["data"]["error"], "read_only")

    def test_recent_unions_with_source(self):
        rows, _ = _call(self.server, "recent", {})
        self.assertEqual(len(rows), 2)
        self.assertEqual({r["source"] for r in rows}, {"a", "b"})

    def test_scoped_recent(self):
        rows, _ = _call(self.server, "recent", {"scope": ["a"]})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source"], "a")

    def test_all_aggregator_readers_dispatch(self):
        for name, args in [
            ("by_id", {"entry_id": 1}),
            ("get_thread", {"root_id": 1}),
            ("search_by_tag", {"tag": "shared"}),
            ("search_by_tag_exact", {"tag": "shared"}),
            ("search_text", {"query": "from"}),
            ("list_tags", {}),
            ("list_agents", {}),
            ("list_entry_types", {}),
            ("list_nodes", {}),
        ]:
            payload, err = _call(self.server, name, args)
            self.assertIsNone(err, f"{name} errored: {err}")

    def test_node_info_not_available_on_aggregator(self):
        _, err = _call(self.server, "node_info", {})
        self.assertEqual(err["data"]["error"], "validation")

    def test_requires_db_or_aggregator(self):
        with self.assertRaises(ValueError):
            MCPServer()


class HttpTransportTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self._tmp.name) / "journal.db")
        init_db(self.db, node_name="test")

    def tearDown(self):
        self._tmp.cleanup()

    def _serve(self, server) -> tuple:
        httpd = make_httpd(server, port=0)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        # Ensure the listening socket is always closed (no ResourceWarnings / port races).
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        return httpd, httpd.server_address[1]

    def _post(self, port, payload, headers=None):
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", **(headers or {})},
        )
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read())

    def test_log_then_recent_over_http(self):
        httpd, port = self._serve(MCPServer(db_path=self.db))
        try:
            status, resp = self._post(
                port,
                _rpc(
                    "tools/call",
                    {
                        "name": "log_entry",
                        "arguments": {
                            "agent": "code",
                            "entry_type": "note",
                            "content": "http roundtrip",
                        },
                    },
                ),
            )
            self.assertEqual(status, 200)
            self.assertNotIn("error", resp)
            status, resp = self._post(port, _rpc("tools/call", {"name": "recent", "arguments": {}}))
            payload = json.loads(resp["result"]["content"][0]["text"])
            self.assertEqual(payload[0]["content"], "http roundtrip")
        finally:
            httpd.shutdown()

    def test_tools_list_over_http(self):
        httpd, port = self._serve(MCPServer(db_path=self.db))
        try:
            _, resp = self._post(port, _rpc("tools/list"))
            self.assertIn("log_entry", {t["name"] for t in resp["result"]["tools"]})
        finally:
            httpd.shutdown()

    def test_auth_required_when_key_set(self):
        httpd, port = self._serve(MCPServer(db_path=self.db, api_key="bnyk_secret"))
        try:
            # no bearer → 401 not_authenticated
            import urllib.error

            with self.assertRaises(urllib.error.HTTPError) as ctx:
                self._post(port, _rpc("tools/list"))
            self.assertEqual(ctx.exception.code, 401)
            # correct bearer → ok
            status, resp = self._post(
                port, _rpc("tools/list"), headers={"Authorization": "Bearer bnyk_secret"}
            )
            self.assertEqual(status, 200)
        finally:
            httpd.shutdown()

    def test_server_is_threaded(self):
        from http.server import ThreadingHTTPServer

        httpd = make_httpd(MCPServer(db_path=self.db), port=0)
        try:
            self.assertIsInstance(httpd, ThreadingHTTPServer)
        finally:
            httpd.server_close()

    def test_concurrent_requests(self):
        httpd, port = self._serve(MCPServer(db_path=self.db))
        results = []

        def hit():
            _, resp = self._post(port, _rpc("tools/list"))
            results.append("result" in resp)

        threads = [threading.Thread(target=hit) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        httpd.shutdown()
        self.assertEqual(len(results), 8)
        self.assertTrue(all(results))

    def test_malformed_json_over_http(self):
        import urllib.error

        httpd, port = self._serve(MCPServer(db_path=self.db))
        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}",
                data=b"{not json",
                headers={"Content-Type": "application/json"},
            )
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)
            self.assertEqual(ctx.exception.code, 400)
        finally:
            httpd.shutdown()


if __name__ == "__main__":
    unittest.main()
