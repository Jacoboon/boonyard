"""M7 tests — the MCP server: tool surface, JSON-RPC dispatch, HTTP, read-only."""

import json
import sqlite3
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

from boonyard import init_db, log_entry, upcoming_dates
from boonyard import meter as boonyard_meter
from boonyard.aggregator import Aggregator
from boonyard.mcp import MCPServer, make_httpd

# Pinned so the tool and the Python call are compared against the same day.
PINNED = "2026-08-24"


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
            "upcoming_dates",
            "read_stats",
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
            ("upcoming_dates", {}),
            ("read_stats", {}),
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
            ("upcoming_dates", {}),
            ("read_stats", {}),
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

    def _post(self, port, payload, headers=None, path=""):
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/{path}",
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

    def test_capability_url_path_auth(self):
        # The key as the leading URL path segment (no header) authenticates.
        httpd, port = self._serve(MCPServer(db_path=self.db, api_key="bnyk_secret"))
        try:
            status, resp = self._post(port, _rpc("tools/list"), path="bnyk_secret")
            self.assertEqual(status, 200)
            self.assertIn("log_entry", {t["name"] for t in resp["result"]["tools"]})
        finally:
            httpd.shutdown()

    def test_both_auth_paths_wrong_is_401(self):
        import urllib.error

        httpd, port = self._serve(MCPServer(db_path=self.db, api_key="bnyk_secret"))
        try:
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                self._post(port, _rpc("tools/list"), path="wrongkey")  # wrong path, no header
            self.assertEqual(ctx.exception.code, 401)
        finally:
            httpd.shutdown()

    def test_header_auth_wins_even_with_nonmatching_path(self):
        httpd, port = self._serve(MCPServer(db_path=self.db, api_key="bnyk_secret"))
        try:
            status, _ = self._post(
                port,
                _rpc("tools/list"),
                headers={"Authorization": "Bearer bnyk_secret"},
                path="somethingelse",
            )
            self.assertEqual(status, 200)
        finally:
            httpd.shutdown()

    def test_get_returns_405_with_allow(self):
        import urllib.error

        httpd, port = self._serve(MCPServer(db_path=self.db))
        try:
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/")
            self.assertEqual(ctx.exception.code, 405)
            self.assertEqual(ctx.exception.headers.get("Allow"), "POST")
        finally:
            httpd.shutdown()

    def test_notification_returns_202_no_body(self):
        httpd, port = self._serve(MCPServer(db_path=self.db))
        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/",
                data=json.dumps(_rpc("notifications/initialized")).encode(),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req) as resp:
                self.assertEqual(resp.status, 202)
                self.assertEqual(resp.read(), b"")
        finally:
            httpd.shutdown()

    def test_initialize_lifecycle_over_http(self):
        httpd, port = self._serve(MCPServer(db_path=self.db))
        try:
            status, resp = self._post(port, _rpc("initialize", {"protocolVersion": "2024-11-05"}))
            self.assertEqual(status, 200)
            self.assertIn("protocolVersion", resp["result"])
            self.assertEqual(resp["result"]["serverInfo"]["name"], "boonyard")
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


class UpcomingDatesToolTests(unittest.TestCase):
    """The MCP tool IS the deliverable: the morning wave is a cloud session with
    no filesystem, so a CLI-only tripwire would be a control with no reader."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        d = Path(self._tmp.name)
        self.db = str(d / "umbrella" / "journal.db")
        init_db(self.db, node_name="umbrella")
        log_entry(
            "conductor", "note", "R1 falsification", tags="killdate:2026-09-23", db_path=self.db
        )
        log_entry(
            "conductor", "note", "the unread gate", tags="killdate:2026-08-20", db_path=self.db
        )
        log_entry("conductor", "note", "vague", tags="killdate:soon", db_path=self.db)
        self.server = MCPServer(db_path=self.db)

        self.other = str(d / "jrhood" / "journal.db")
        init_db(self.other, node_name="jrhood")
        log_entry("code", "note", "R2 clock", tags="killdate:2026-09-11", db_path=self.other)
        self.v2 = d / "v2" / "journal.db"
        self.v2.parent.mkdir(parents=True)
        conn = sqlite3.connect(self.v2)
        conn.execute("CREATE TABLE journal (id INTEGER PRIMARY KEY)")
        conn.commit()
        conn.close()
        self.agg_server = MCPServer(
            aggregator=Aggregator(
                {"umbrella": self.db, "jrhood": self.other, "v2_wall": str(self.v2)}
            )
        )

    def tearDown(self):
        self._tmp.cleanup()

    def test_tool_is_advertised_with_its_parameters(self):
        resp = self.server.handle(_rpc("tools/list"))
        tool = next(t for t in resp["result"]["tools"] if t["name"] == "upcoming_dates")
        self.assertEqual(
            set(tool["inputSchema"]["properties"]), {"within_days", "prefix", "today", "scope"}
        )
        self.assertEqual(tool["inputSchema"]["required"], [])
        self.assertIn("overdue", tool["description"])

    def test_tool_payload_matches_the_python_call(self):
        payload, err = _call(self.server, "upcoming_dates", {"within_days": 45, "today": PINNED})
        self.assertIsNone(err)
        expected = upcoming_dates(45, today=PINNED, db_path=self.db)
        # Round-trip the Python result through JSON: the tool's payload is JSON.
        self.assertEqual(payload, json.loads(json.dumps(expected)))

    def test_overdue_survives_the_wire(self):
        payload, _ = _call(self.server, "upcoming_dates", {"today": PINNED})
        self.assertEqual(payload["dates"][0]["date"], "2026-08-20")
        self.assertTrue(payload["dates"][0]["overdue"])
        self.assertEqual(payload["dates"][0]["days_out"], -4)

    def test_malformed_tag_arrives_as_a_warning_not_an_error(self):
        payload, err = _call(self.server, "upcoming_dates", {"today": PINNED})
        self.assertIsNone(err)
        self.assertEqual(payload["warnings"][0]["kind"], "malformed_date_tag")

    def test_defaults_apply_when_no_arguments_are_given(self):
        payload, err = _call(self.server, "upcoming_dates", {})
        self.assertIsNone(err)
        self.assertEqual(payload["within_days"], 45)
        self.assertEqual(payload["prefix"], "killdate")

    def test_bad_today_is_a_validation_error_not_a_crash(self):
        _, err = _call(self.server, "upcoming_dates", {"today": "tomorrow"})
        self.assertEqual(err["data"]["error"], "validation")

    def test_scope_all_over_the_aggregator_with_a_broken_node(self):
        """§ACCEPTANCE 1 + 3 in one call: the register merges across nodes, and the
        dead node comes back as a warning instead of taking the answer down."""
        payload, err = _call(self.agg_server, "upcoming_dates", {"scope": "all", "today": PINNED})
        self.assertIsNone(err)
        self.assertEqual(
            [(r["date"], r["node"]) for r in payload["dates"]],
            [
                ("2026-08-20", "umbrella"),
                ("2026-09-11", "jrhood"),
                ("2026-09-23", "umbrella"),
            ],
        )
        skipped = [w for w in payload["warnings"] if w["kind"] == "node_skipped"]
        self.assertEqual(skipped[0]["node"], "v2_wall")

    def test_aggregator_scope_narrowing_through_the_tool(self):
        payload, _ = _call(
            self.agg_server, "upcoming_dates", {"scope": ["jrhood"], "today": PINNED}
        )
        self.assertEqual([r["node"] for r in payload["dates"]], ["jrhood"])

    def test_register_is_readable_over_real_http(self):
        """The connector shape end to end: JSON-RPC over a socket, no filesystem."""
        httpd = make_httpd(self.agg_server, port=0)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        port = httpd.server_address[1]
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/",
            data=json.dumps(
                _rpc(
                    "tools/call",
                    {
                        "name": "upcoming_dates",
                        "arguments": {"scope": "all", "today": PINNED},
                    },
                )
            ).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req) as resp:
            body = json.loads(resp.read())
        payload = json.loads(body["result"]["content"][0]["text"])
        self.assertEqual(len(payload["dates"]), 3)
        self.assertTrue(payload["dates"][0]["overdue"])


class MeterTests(unittest.TestCase):
    """The meter, at the layer that actually serves traffic (umbrella #228 Layer 3)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        d = Path(self._tmp.name)
        self.db = str(d / "node" / "journal.db")
        init_db(self.db, node_name="umbrella")
        log_entry("code", "note", "a thing worth finding", tags="seed", db_path=self.db)
        self.meter_db = Path(self.db).parent / "meter.db"
        self.server = MCPServer(db_path=self.db)

    def tearDown(self):
        self._tmp.cleanup()

    def _meter_rows(self):
        conn = sqlite3.connect(self.meter_db)
        conn.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in conn.execute("SELECT ts, tool, node, kind FROM meter")]
        finally:
            conn.close()

    def test_meter_defaults_to_the_node_s_sibling(self):
        _call(self.server, "recent", {})
        self.assertTrue(self.meter_db.exists(), "the sidecar lands beside journal.db")

    def test_a_read_records_exactly_one_read_row(self):
        _call(self.server, "search_text", {"query": "thing"})
        rows = self._meter_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["tool"], "search_text")
        self.assertEqual(rows[0]["kind"], "read")
        self.assertEqual(rows[0]["node"], "umbrella")

    def test_a_write_records_exactly_one_write_row(self):
        _call(
            self.server,
            "log_entry",
            {"agent": "code", "entry_type": "note", "content": "written"},
        )
        rows = self._meter_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["tool"], rows[0]["kind"]), ("log_entry", "write"))

    def test_classification_follows_the_existing_write_tool_set(self):
        """Reuses _WRITE_TOOLS rather than a second list that could drift from it."""
        from boonyard.mcp import _WRITE_TOOLS

        _call(self.server, "log_skill_revision", {"slug": "s", "content": "c", "agent": "code"})
        _call(self.server, "list_tags", {})
        kinds = {r["tool"]: r["kind"] for r in self._meter_rows()}
        self.assertEqual(kinds["log_skill_revision"], "write")
        self.assertEqual(kinds["list_tags"], "read")
        self.assertEqual(_WRITE_TOOLS, {"log_entry", "log_skill_revision"})

    def test_an_unknown_tool_is_not_counted(self):
        _call(self.server, "no_such_tool", {})
        self.assertFalse(self.meter_db.exists())

    def test_the_meter_cannot_break_a_read(self):
        """A METER THAT CAN BREAK A READ IS WORSE THAN NO METER.

        The sidecar's parent is a FILE here, so every insert fails. The read must
        still return its rows. Reintroduce a raising insert and this fails.
        """
        blocker = Path(self._tmp.name) / "blocker"
        blocker.write_text("not a directory", encoding="utf-8")
        broken = MCPServer(db_path=self.db, meter_path=blocker / "meter.db")
        payload, err = _call(broken, "recent", {})
        self.assertIsNone(err, f"a dead meter must not surface as a tool error: {err}")
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["content"], "a thing worth finding")
        payload, err = _call(broken, "search_text", {"query": "thing"})
        self.assertIsNone(err)
        self.assertEqual(len(payload), 1)

    def test_arguments_are_never_persisted(self):
        """A search query can carry a homeowner's name. It must not reach the disk.

        Sentinel through the real tool path, then the sidecar is read as RAW BYTES
        — not via SQL — so a value hidden in any column or index still fails this.
        """
        sentinel = "SENTINEL_STRING_XYZ"
        _call(self.server, "search_text", {"query": sentinel})
        _call(self.server, "search_by_tag", {"tag": sentinel})
        _call(self.server, "latest_skill", {"slug": sentinel})
        _call(
            self.server,
            "log_entry",
            {"agent": "code", "entry_type": "note", "content": sentinel},
        )
        blob = self.meter_db.read_bytes()
        self.assertNotIn(sentinel.encode(), blob, "an argument reached the meter")
        # ...and the rows that DO exist are the four calls, by name only.
        self.assertEqual(len(self._meter_rows()), 4)

    def test_read_stats_reports_the_traffic_it_just_served(self):
        for _ in range(3):
            _call(self.server, "recent", {})
        _call(self.server, "log_entry", {"agent": "code", "entry_type": "note", "content": "x"})
        payload, err = _call(self.server, "read_stats", {})
        self.assertIsNone(err)
        # 3 recents + 1 write + this read_stats call itself (the observer effect).
        self.assertEqual(payload["totals"]["writes"], 1)
        self.assertEqual(payload["totals"]["reads"], 4)
        self.assertEqual(payload["totals"]["ratio"], 4.0)
        self.assertEqual(payload["by_tool"]["recent"], 3)
        self.assertEqual(payload["by_tool"]["log_entry"], 1)

    def test_read_stats_tool_matches_the_python_call(self):
        _call(self.server, "recent", {})
        payload, err = _call(self.server, "read_stats", {"within_days": 7, "today": "2026-08-25"})
        self.assertIsNone(err)
        expected = boonyard_meter.read_stats(7, today="2026-08-25", meter_path=self.meter_db)
        # The tool call itself was metered before the Python call ran, so compare
        # the shape and the by_tool counts that both saw.
        self.assertEqual(set(payload), set(expected))
        self.assertEqual(payload["since"], expected["since"])
        self.assertEqual(payload["until"], expected["until"])
        self.assertEqual(payload["by_tool"]["recent"], expected["by_tool"]["recent"])

    def test_read_stats_defaults_to_a_seven_day_window(self):
        payload, _ = _call(self.server, "read_stats", {})
        self.assertEqual(payload["window_days"], 7)

    def test_read_stats_over_real_http(self):
        """The only reader this meter has is a cloud session with no filesystem."""
        _call(self.server, "recent", {})
        httpd = make_httpd(self.server, port=0)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        req = urllib.request.Request(
            f"http://127.0.0.1:{httpd.server_address[1]}/",
            data=json.dumps(_rpc("tools/call", {"name": "read_stats", "arguments": {}})).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req) as resp:
            body = json.loads(resp.read())
        payload = json.loads(body["result"]["content"][0]["text"])
        self.assertGreaterEqual(payload["totals"]["reads"], 1)


class MeterAggregatorTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        d = Path(self._tmp.name)
        self.a = str(d / "a" / "journal.db")
        self.b = str(d / "b" / "journal.db")
        init_db(self.a, node_name="alpha")
        init_db(self.b, node_name="beta")
        self.v2 = d / "v2" / "journal.db"
        self.v2.parent.mkdir(parents=True)
        conn = sqlite3.connect(self.v2)
        conn.execute("CREATE TABLE journal (id INTEGER PRIMARY KEY)")
        conn.commit()
        conn.close()
        # Each node meters itself; the aggregator unions them.
        boonyard_meter.record(
            boonyard_meter.default_meter_path(self.a), "search_text", node="alpha", kind="read"
        )
        boonyard_meter.record(
            boonyard_meter.default_meter_path(self.b), "log_entry", node="beta", kind="write"
        )
        self.agg = Aggregator({"a": self.a, "b": self.b, "v2_wall": str(self.v2)})
        self.server = MCPServer(aggregator=self.agg, meter_path=d / "agg_meter.db")

    def tearDown(self):
        self._tmp.cleanup()

    def test_aggregator_unions_the_per_node_meters(self):
        payload, err = _call(self.server, "read_stats", {"scope": "all"})
        self.assertIsNone(err)
        self.assertEqual(payload["totals"]["reads"], 1)
        self.assertEqual(payload["totals"]["writes"], 1)
        self.assertEqual(payload["by_tool"], {"log_entry": 1, "search_text": 1})

    def test_a_broken_node_warns_and_the_healthy_ones_still_report(self):
        payload, err = _call(self.server, "read_stats", {"scope": "all"})
        self.assertIsNone(err)
        skipped = [w for w in payload["warnings"] if w["kind"] == "node_skipped"]
        self.assertEqual(skipped[0]["node"], "v2_wall")
        self.assertEqual(payload["totals"]["reads"], 1)

    def test_aggregator_meters_one_row_per_call_not_one_per_node(self):
        """Six nodes in scope must not inflate the read count sixfold."""
        _call(self.server, "recent", {"scope": "all"})
        conn = sqlite3.connect(Path(self._tmp.name) / "agg_meter.db")
        try:
            rows = conn.execute("SELECT tool, node, kind FROM meter").fetchall()
        finally:
            conn.close()
        self.assertEqual(len([r for r in rows if r[0] == "recent"]), 1)
        self.assertEqual([r for r in rows if r[0] == "recent"][0][1], "all")

    def test_scope_narrowing_is_recorded_by_name(self):
        _call(self.server, "recent", {"scope": ["a"]})
        conn = sqlite3.connect(Path(self._tmp.name) / "agg_meter.db")
        try:
            node = conn.execute("SELECT node FROM meter WHERE tool = 'recent'").fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(node, "a")


if __name__ == "__main__":
    unittest.main()
