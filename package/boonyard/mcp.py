"""The package's own MCP server (ADR-0008, arch 06) — stdlib ``http.server`` only.

Speaks MCP over JSON-RPC 2.0 (``initialize`` / ``tools/list`` / ``tools/call``).
Exposes **exactly** the arch-06 tool surface — no more, no fewer. ``retag`` is
deliberately absent (arch 06 §Tools that do NOT exist): it is a privileged
operational action, CLI/Python only, never an MCP tool an AI seat can invoke
casually.

Two modes (ADR-0008):
  * single-node — a writable node (``db_path``); this is what ships this phase.
  * aggregator  — read-only over-many (an :class:`Aggregator`); write tools return
    the ``read_only`` error.

Auth is off by default (local OSS, ADR-0008); an optional ``api_key`` enables
bearer-token checking (the per-node-key model, config-stubbed here).

The HTTP layer is ``http.server`` (ADR-0001: acceptable for local single-tenant;
the SaaS runs a real web layer in front of the same package).
"""

import json
from http.server import BaseHTTPRequestHandler, HTTPServer

from . import query
from .constants import DEFAULT_MCP_PORT
from .log import log_entry, log_skill_revision
from .query import search_by_tag_exact

_PROTOCOL_VERSION = "2024-11-05"

# arch 06 error code -> JSON-RPC numeric code
_JSONRPC_CODE = {
    "not_authenticated": -32001,
    "not_authorized": -32002,
    "not_found": -32003,
    "validation": -32602,
    "rate_limited": -32004,
    "quota_exceeded": -32005,
    "read_only": -32006,
    "internal": -32603,
}


class MCPError(Exception):
    """A structured MCP error (arch 06 error model): code + message + optional hint."""

    def __init__(self, code: str, message: str, hint: str | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint

    def data(self) -> dict:
        payload = {"error": self.code, "message": self.message}
        if self.hint:
            payload["hint"] = self.hint
        return payload


def _tool(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "name": name,
        "description": description,
        "inputSchema": {"type": "object", "properties": properties, "required": required},
    }


_STR = {"type": "string"}
_INT = {"type": "integer"}
_BOOL = {"type": "boolean"}
_SCOPE = {"description": "node scope: a name, a list of names, or 'all'"}

# The canonical tool surface (arch 06). retag is intentionally NOT here.
TOOL_DEFS: list[dict] = [
    _tool(
        "log_entry",
        "Append one entry (the universal write).",
        {
            "agent": _STR,
            "entry_type": _STR,
            "content": _STR,
            "related_id": _INT,
            "tags": {"description": "list or comma-separated string"},
            "extras": {"type": "object"},
            "scope": _SCOPE,
        },
        ["agent", "entry_type", "content"],
    ),
    _tool(
        "log_skill_revision",
        "Append a skill revision (root-anchored by slug, ADR-0004).",
        {
            "slug": _STR,
            "content": _STR,
            "agent": _STR,
            "extra_tags": {"type": "array"},
            "scope": _SCOPE,
        },
        ["slug", "content", "agent"],
    ),
    _tool(
        "recent",
        "Newest entries, optionally filtered.",
        {"limit": _INT, "agent": _STR, "entry_type": _STR, "scope": _SCOPE},
        [],
    ),
    _tool("by_id", "One entry by id, or null.", {"entry_id": _INT, "scope": _SCOPE}, ["entry_id"]),
    _tool(
        "get_thread",
        "Root entry + direct children (one level, ADR-0004).",
        {"root_id": _INT, "scope": _SCOPE},
        ["root_id"],
    ),
    _tool(
        "search_by_tag",
        "Substring tag match.",
        {"tag": _STR, "limit": _INT, "scope": _SCOPE},
        ["tag"],
    ),
    _tool(
        "search_by_tag_exact",
        "Exact tag equality (entry_tag).",
        {"tag": _STR, "limit": _INT, "scope": _SCOPE},
        ["tag"],
    ),
    _tool(
        "search_text",
        "FTS5 full-text search over content.",
        {"query": _STR, "limit": _INT, "scope": _SCOPE},
        ["query"],
    ),
    _tool(
        "list_tags",
        "The tag menu (count-ranked).",
        {"prefix": _STR, "tree": _BOOL, "scope": _SCOPE},
        [],
    ),
    _tool("list_agents", "Agents + counts.", {"scope": _SCOPE}, []),
    _tool("list_entry_types", "Entry types + counts.", {"scope": _SCOPE}, []),
    _tool("list_skills", "The skill catalog.", {"limit": _INT, "scope": _SCOPE}, []),
    _tool(
        "latest_skill",
        "Newest revision of a named skill, or null.",
        {"slug": _STR, "scope": _SCOPE},
        ["slug"],
    ),
    _tool("list_nodes", "Configured nodes + metadata.", {}, []),
    _tool("node_info", "Full node metadata.", {"scope": _STR}, []),
    _tool("audit_doctor", "The substrate self-audit.", {"scope": _STR}, []),
]

_TOOL_NAMES = {t["name"] for t in TOOL_DEFS}
_TOOL_REQUIRED = {t["name"]: t["inputSchema"]["required"] for t in TOOL_DEFS}
_WRITE_TOOLS = {"log_entry", "log_skill_revision"}


def _tags_to_str(tags) -> str | None:
    if tags is None:
        return None
    if isinstance(tags, list):
        return ",".join(str(t) for t in tags)
    return str(tags)


class MCPServer:
    """Dispatches MCP JSON-RPC requests against a node (or an aggregator).

    Construct with ``db_path`` (writable single node) or ``aggregator`` (read-only
    over-many). ``handle(request)`` is pure and testable without HTTP.
    """

    def __init__(self, db_path=None, *, aggregator=None, profile=None, api_key=None):
        if db_path is None and aggregator is None:
            raise ValueError("MCPServer requires a db_path or an aggregator")
        self._db = db_path
        self._agg = aggregator
        self._profile = profile
        self._api_key = api_key
        self._read_only = aggregator is not None

    # -- JSON-RPC entry ----------------------------------------------------
    def handle(self, request: dict) -> dict | None:
        """Handle one JSON-RPC request; return a response, or None for notifications."""
        rid = request.get("id")
        method = request.get("method")
        if method in ("notifications/initialized", "initialized"):
            return None
        try:
            if method == "initialize":
                result = {
                    "protocolVersion": _PROTOCOL_VERSION,
                    "capabilities": {"tools": {}},
                    "serverInfo": {
                        "name": "boonyard",
                        "version": __import__("boonyard").__version__,
                    },
                }
            elif method == "tools/list":
                result = {"tools": TOOL_DEFS}
            elif method == "tools/call":
                params = request.get("params") or {}
                payload = self._call_tool(params.get("name"), params.get("arguments") or {})
                result = {"content": [{"type": "text", "text": json.dumps(payload)}]}
            else:
                raise MCPError("validation", f"unknown method {method!r}")
            return {"jsonrpc": "2.0", "id": rid, "result": result}
        except MCPError as exc:
            return self._error(rid, exc)
        except ValueError as exc:
            return self._error(rid, MCPError("validation", str(exc)))
        except Exception as exc:  # noqa: BLE001 — surface as structured internal error
            return self._error(rid, MCPError("internal", str(exc)))

    def _error(self, rid, exc: MCPError) -> dict:
        return {
            "jsonrpc": "2.0",
            "id": rid,
            "error": {
                "code": _JSONRPC_CODE.get(exc.code, -32603),
                "message": exc.message,
                "data": exc.data(),
            },
        }

    # -- tool dispatch -----------------------------------------------------
    def _call_tool(self, name, args: dict):
        if name not in _TOOL_NAMES:
            raise MCPError("validation", f"unknown tool {name!r}", hint="call tools/list")
        for field_name in _TOOL_REQUIRED[name]:
            if args.get(field_name) is None:
                raise MCPError("validation", f"missing required parameter {field_name!r}")
        if self._read_only and name in _WRITE_TOOLS:
            raise MCPError(
                "read_only",
                "aggregator endpoint is read-only; address a specific node to write",
            )
        if self._agg is not None:
            return self._call_aggregator(name, args)
        return self._call_single(name, args)

    def _call_single(self, name, args: dict):
        db = self._db
        if name == "log_entry":
            new_id = log_entry(
                args["agent"],
                args["entry_type"],
                args["content"],
                related_id=args.get("related_id"),
                tags=_tags_to_str(args.get("tags")),
                extras=args.get("extras"),
                db_path=db,
                profile=self._profile,
            )
            return {"id": new_id}
        if name == "log_skill_revision":
            slug = args["slug"]
            existing = search_by_tag_exact(f"skill-{slug}", limit=10_000, db_path=db)
            root_id = min((r["id"] for r in existing), default=None)
            new_id = log_skill_revision(
                args["agent"],
                args["content"],
                root_id=root_id,
                slug=slug,
                tags=_tags_to_str(args.get("extra_tags")),
                db_path=db,
            )
            return {"id": new_id, "root_id": root_id if root_id is not None else new_id}
        if name == "recent":
            return query.recent(
                args.get("limit", 20), args.get("agent"), args.get("entry_type"), db_path=db
            )
        if name == "by_id":
            return query.by_id(args["entry_id"], db_path=db)
        if name == "get_thread":
            return query.get_thread(args["root_id"], db_path=db)
        if name == "search_by_tag":
            return query.search_by_tag(args["tag"], args.get("limit", 20), db_path=db)
        if name == "search_by_tag_exact":
            return query.search_by_tag_exact(args["tag"], args.get("limit", 20), db_path=db)
        if name == "search_text":
            return query.search_text(
                args.get("query") or args.get("text"), args.get("limit", 20), db_path=db
            )
        if name == "list_tags":
            return query.list_tags(args.get("prefix"), args.get("tree", False), db_path=db)
        if name == "list_agents":
            return query.list_agents(db_path=db)
        if name == "list_entry_types":
            return query.list_entry_types(db_path=db)
        if name == "list_skills":
            return query.list_skills(args.get("limit", 50), db_path=db)
        if name == "latest_skill":
            return query.latest_skill(args["slug"], db_path=db)
        if name == "node_info":
            return query.node_info(db_path=db, profile=self._profile)
        if name == "audit_doctor":
            return query.audit_doctor(db_path=db, profile=self._profile)
        if name == "list_nodes":
            info = query.node_info(db_path=db, profile=self._profile)
            return [
                {
                    "name": info["name"],
                    "slug": info["name"],
                    "created_at": info["created_at"],
                    "entry_count": info["entry_count"],
                    "last_write_at": info["last_write_at"],
                }
            ]
        raise MCPError("validation", f"tool {name!r} not available in this mode")

    def _call_aggregator(self, name, args: dict):
        agg = self._agg
        scope = args.get("scope")
        if name == "recent":
            return agg.recent(
                args.get("limit", 20), args.get("agent"), args.get("entry_type"), scope=scope
            )
        if name == "by_id":
            return agg.by_id(args["entry_id"], scope=scope)
        if name == "get_thread":
            return agg.get_thread(args["root_id"], scope=scope)
        if name == "search_by_tag":
            return agg.search_by_tag(args["tag"], args.get("limit", 20), scope=scope)
        if name == "search_by_tag_exact":
            return agg.search_by_tag_exact(args["tag"], args.get("limit", 20), scope=scope)
        if name == "search_text":
            return agg.search_text(
                args.get("query") or args.get("text"), args.get("limit", 20), scope=scope
            )
        if name == "list_tags":
            return agg.list_tags(args.get("prefix"), args.get("tree", False), scope=scope)
        if name == "list_agents":
            return agg.list_agents(scope=scope)
        if name == "list_entry_types":
            return agg.list_entry_types(scope=scope)
        if name == "list_nodes":
            return agg.list_nodes()
        raise MCPError("validation", f"tool {name!r} is not available on the aggregator endpoint")


# --------------------------------------------------------------------------
# HTTP transport (stateless JSON-RPC over POST)
# --------------------------------------------------------------------------
def make_handler(server: MCPServer):
    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # quiet by default
            pass

        def _send(self, status: int, payload: dict | None):
            body = b"" if payload is None else json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if body:
                self.wfile.write(body)

        def do_POST(self):
            if server._api_key:
                if self.headers.get("Authorization") != f"Bearer {server._api_key}":
                    self._send(
                        401,
                        {
                            "jsonrpc": "2.0",
                            "id": None,
                            "error": {
                                "code": _JSONRPC_CODE["not_authenticated"],
                                "message": "not authenticated",
                                "data": {"error": "not_authenticated"},
                            },
                        },
                    )
                    return
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b"{}"
            try:
                request = json.loads(raw)
            except json.JSONDecodeError:
                self._send(
                    400,
                    {
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {
                            "code": -32700,
                            "message": "parse error",
                            "data": {"error": "validation", "message": "invalid JSON"},
                        },
                    },
                )
                return
            response = server.handle(request)
            self._send(200 if response is not None else 204, response)

    return _Handler


def make_httpd(
    server: MCPServer, host: str = "127.0.0.1", port: int = DEFAULT_MCP_PORT
) -> HTTPServer:
    """Build (but don't start) an HTTPServer serving ``server``. Port 0 = ephemeral."""
    return HTTPServer((host, port), make_handler(server))


def serve(
    db_path=None,
    *,
    aggregator=None,
    profile=None,
    api_key=None,
    host: str = "127.0.0.1",
    port: int = DEFAULT_MCP_PORT,
) -> None:
    """Run the MCP server forever on ``host:port`` (blocks). Ctrl-C to stop."""
    server = MCPServer(db_path=db_path, aggregator=aggregator, profile=profile, api_key=api_key)
    httpd = make_httpd(server, host, port)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.shutdown()
