"""The ONLY module in the SaaS layer that imports ``boonyard`` (PHASE_2.md's rule).

PHASE_2.md, Risks: *"the Flask layer drifts ahead of the package — mitigation:
enforce the 'boonyard_adapter.py is the only file that touches boonyard.* calls'
rule."* ``tests/test_adapter_rule.py`` greps the tree to keep it true. Everything
the provisioner and router need from the substrate is a small function here, so a
package change has exactly one place to land on this side of the line.

ADR-0006 — *the OSS package is the SaaS* — is literally this file: the hosted
layer constructs the same ``MCPServer`` the six live units run, against the same
``journal.db`` shape, via the same ``init_db``/``export_bundle``.

Coupling worth naming (a finding, not a failure): two names imported below are
private to ``boonyard.mcp`` (``_jsonrpc_error``, ``_JSONRPC_CODE``). They are the
package's own HTTP-layer error shape, and the router's 401/403/404/405 bodies must
be byte-compatible with ``make_handler``'s, so reusing the function is more honest
than copying it. Making them public is a 3.3.0 conversation, not a slice-1 edit
(no changes under ``package/`` in this order).
"""

import json
from pathlib import Path

import boonyard
from boonyard.db import init_db
from boonyard.export import export_bundle, import_bundle
from boonyard.mcp import _JSONRPC_CODE, TOOL_DEFS, MCPServer, _jsonrpc_error
from boonyard.profile import load_profile
from boonyard.query import node_info
from boonyard.retag import retag_entry


def package_version() -> str:
    """The installed substrate's version string (what ``/health`` reports).

    Example:
        package_version()  # -> "3.2.0"
    """
    return boonyard.__version__


def init_node(db_path: str | Path, *, node_name: str) -> str:
    """Create a real, initialised node at ``db_path`` and return its uuid.

    This is the package's own ``init_db`` — never a bare ``sqlite3.connect``
    (umbrella #315's stub trap). The node's identity is the ``meta.node_uuid`` the
    package minted, so the registry's ``node_id`` and the file agree.

    Example:
        init_node("users/<id>/nodes/test-0/journal.db", node_name="test-0")
    """
    init_db(db_path, node_name=node_name)
    return node_uuid(db_path)


def node_uuid(db_path: str | Path) -> str:
    """The ``meta.node_uuid`` of the node at ``db_path``.

    Example:
        node_uuid("node/journal.db")  # -> "bbb63f62-…"
    """
    return node_info(db_path=db_path)["uuid"]


def entry_count(db_path: str | Path) -> int:
    """How many entries the node at ``db_path`` holds.

    Example:
        entry_count("node/journal.db")  # -> 99
    """
    return node_info(db_path=db_path)["entry_count"]


def starter_profile_toml(node_name: str) -> str:
    """The starter ``boonyard.toml`` for a new hosted node.

    Mirrors the text ``boonyard init`` writes (``boonyard.cli.cmd_init``). That
    text is inline in the package's CLI rather than a callable, so it is repeated
    here — the second finding for 3.3.0 (a ``profile.starter_toml(name)`` would
    remove the copy).

    Example:
        starter_profile_toml("test-0").startswith("[node]")
    """
    return (
        f'[node]\nname = "{node_name}"\nschema_version = 3\n\n'
        "[agents]\n"
        "# Advisory seat registry (wall entry 97). Unknown seats warn, never reject.\n"
        'code = "the implementing seat"\n'
        'cowork = "the design seat"\n'
        'chat = "the consumer-chat seat"\n'
        'professor = "the human"\n'
        'system = "auto-generated entries"\n\n'
        "[tags.namespaces]\n"
        'model = "exact model string of the driving seat (model:claude-opus-4-8)"\n\n'
        "[extras]\nenabled = false\n"
    )


def make_server(
    db_path: str | Path,
    *,
    profile_path: str | Path | None = None,
    meter_path: str | Path | None = None,
) -> MCPServer:
    """One ``MCPServer`` for one node — the engine the router calls per request.

    ``api_key`` is always ``None`` here: authentication is the router's job (the
    per-node hashed keys of ADR-0008), done before this object exists. Construction
    is cheap — it stores paths; connections are opened per call (mcp.py's own
    docstring), which is why the router builds one per request.

    Example:
        make_server("…/journal.db", profile_path="…/boonyard.toml",
                    meter_path="…/meter.db").handle({"jsonrpc": "2.0", "id": 1,
                    "method": "tools/list"})
    """
    return MCPServer(
        db_path=str(db_path),
        profile=load_profile(profile_path),
        api_key=None,
        meter_path=meter_path,
    )


def call_tool(server: MCPServer, name: str, **arguments) -> dict | list:
    """Call one MCP tool in-process and return its JSON payload (the node browser's engine).

    The same ``MCPServer.handle()`` the router runs per request, without HTTP.
    ``None`` arguments are dropped. A tool error (validation, not found, …) raises
    :class:`ToolError` with the tool's own message.

    Example:
        call_tool(server, "recent", limit=5)
    """
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": name,
            "arguments": {k: v for k, v in arguments.items() if v is not None},
        },
    }
    response = server.handle(request) or {}
    if "error" in response:
        err = response["error"]
        raise ToolError(
            str(err.get("message", "tool error")), kind=(err.get("data") or {}).get("error")
        )
    result = response.get("result") or {}
    content = result.get("content") or [{}]
    text = content[0].get("text", "")
    if result.get("isError"):
        raise ToolError(text or "tool error")
    return json.loads(text) if text else {}


class ToolError(RuntimeError):
    """A tool refused the call; ``message`` is the package's own wording."""

    def __init__(self, message: str, *, kind: str | None = None):
        super().__init__(message)
        self.kind = kind


def retag(db_path: str | Path, entry_id: int, new_tags: str | None, reason: str, actor: str) -> int:
    """The package's audited retag (ADR-0005's one mutation); returns the ``meta_log`` id.

    Example:
        retag("…/journal.db", 12, "decision, boonyard", "wrong namespace", "jacoboon")
    """
    return retag_entry(entry_id, new_tags, reason, actor, db_path=db_path)


def tool_names() -> list[str]:
    """The package's canonical MCP tool names (arch 06), in declaration order.

    Example:
        len(tool_names())  # -> 18 at boonyard 3.2.0
    """
    return [t["name"] for t in TOOL_DEFS]


def jsonrpc_error(kind: str, message: str, *, code: int | None = None) -> dict:
    """The package's HTTP-layer JSON-RPC error body, by arch-06 error kind.

    ``kind`` is one of the arch-06 codes (``not_authenticated``, ``not_authorized``,
    ``not_found``, ``validation`` …); ``code`` overrides the numeric JSON-RPC code
    when the package uses a non-table value (its 405 uses ``-32601``).

    Example:
        jsonrpc_error("not_found", "no such node")["error"]["data"]
        # -> {"error": "not_found"}
    """
    return _jsonrpc_error(_JSONRPC_CODE[kind] if code is None else code, message, kind)


def export_node(
    dest_path: str | Path,
    *,
    db_path: str | Path,
    profile_path: str | Path | None = None,
    exported_at: str | None = None,
) -> Path:
    """Write the package's export bundle (journal + profile + manifest) to ``dest_path``.

    Example:
        export_node("exports/export_20260906T210000Z.zip", db_path="…/journal.db",
                    profile_path="…/boonyard.toml")
    """
    return export_bundle(
        dest_path, db_path=db_path, profile_path=profile_path, exported_at=exported_at
    )


def import_node(bundle_path: str | Path, dest_db_path: str | Path) -> Path:
    """Restore a boonyard export bundle to ``dest_db_path`` (bundle round-trip only).

    Example:
        import_node("export_….zip", "scratch/journal.db")
    """
    return import_bundle(bundle_path, dest_db_path)
