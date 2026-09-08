"""The package's own MCP server (ADR-0008, arch 06) — stdlib ``http.server`` only.

Speaks MCP over JSON-RPC 2.0 (``initialize`` / ``tools/list`` / ``tools/call``).
Exposes **exactly** the arch-06 tool surface — no more, no fewer. ``retag`` is
deliberately absent (arch 06 §Tools that do NOT exist): it is a privileged
operational action, CLI/Python only, never an MCP tool an AI seat can invoke
casually.

Three modes (ADR-0008, extended by ADR-0014):
  * single-node — a writable node (``db_path``); this is what ships this phase.
  * aggregator  — read-only over-many (an :class:`Aggregator`); write tools return
    the ``read_only`` error.
  * nodes       — several named nodes, WRITABLE (``nodes={slug: path}``): a call that
    names one node is served against that node's file exactly as single-node mode
    does; a read that names none, or several, is served by an ``Aggregator`` over
    the same map. This is the account door (ADR-0014) and it is equally the
    self-hoster with three local nodes (ADR-0006: the package is the SaaS).

⚠ READ-ONLY IS EXPLICIT, NEVER DERIVED. It used to be ``aggregator is not None``,
which was the entire protection on the ``_aggregate`` endpoint. ``nodes`` mode holds
an aggregator AND permits writes, so that derivation would have made ``_aggregate``
silently writable. The mode is set once in the constructor and the read-only flag
follows from it; ``tests/test_account_door.py`` asserts the two modes differ.

Auth is off by default (local OSS, ADR-0008); an optional ``api_key`` enables
bearer-token checking (the per-node-key model, config-stubbed here).

The HTTP layer is ``http.server`` (ADR-0001: acceptable for local single-tenant;
the SaaS runs a real web layer in front of the same package).
"""

import copy
import hmac
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import meter, query, views
from .aggregator import aggregator as _aggregator_factory
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
    _tool(
        "upcoming_dates",
        "Kill-date register: entries tagged <prefix>:YYYY-MM-DD, soonest first. "
        "Past dates are NOT dropped — they return with overdue=true and a negative "
        "days_out until a human retires them. Returns "
        "{today, within_days, prefix, dates[], warnings[]}.",
        {
            "within_days": _INT,
            "prefix": {**_STR, "description": "tag namespace to scan (default 'killdate')"},
            "today": {
                **_STR,
                "description": "pin today as YYYY-MM-DD; default is the server's LOCAL date",
            },
            "scope": _SCOPE,
        },
        [],
    ),
    _tool(
        "read_stats",
        "The meter: how often this wall is READ versus WRITTEN. Returns "
        "{window_days, since, until, totals{reads,writes,ratio}, by_tool, by_day, "
        "warnings}. A ratio below 1 means the wall is being written more than it is "
        "consulted. Tool name and timestamp only \u2014 arguments are never recorded.",
        {
            "within_days": _INT,
            "today": {
                **_STR,
                "description": "pin today as YYYY-MM-DD; default is the server's LOCAL date",
            },
            "scope": _SCOPE,
        },
        [],
    ),
    _tool(
        "list_nodes",
        "Configured nodes + metadata. Each row carries 'slug' and 'name': the SLUG is "
        "what you pass back as 'node' or 'scope'; 'name' is the human label and is not "
        "addressable.",
        {},
        [],
    ),
    _tool("node_info", "Full node metadata.", {"scope": _STR}, []),
    _tool("audit_doctor", "The substrate self-audit.", {"scope": _STR}, []),
    _tool(
        "instructions",
        "How to use this node: the package readme (read law, write conventions, "
        "registers, skills, every tool) plus this node's own readme if one was written "
        "(the skill with slug 'readme'). Returns {package, version, readme}.",
        {"scope": _STR},
        [],
    ),
    _tool(
        "ghosts",
        "The orphan sweep, derived (ADR-0013): root entries nobody threaded to and "
        "nobody read in the window, coldest first. Returns rows of "
        "{id, timestamp, agent, entry_type, first_line, tags, reads, last_read}.",
        {
            "limit": _INT,
            "older_than_days": {**_INT, "description": "window in days (default 30)"},
            "scope": _STR,
        },
        [],
    ),
]

_TOOL_NAMES = {t["name"] for t in TOOL_DEFS}
_TOOL_REQUIRED = {t["name"]: t["inputSchema"]["required"] for t in TOOL_DEFS}
_WRITE_TOOLS = {"log_entry", "log_skill_revision"}

# ADR-0014 §11 — name the node wherever the argument is node-local.
#
# CLASS A: the argument only means something inside one node, so a union of it is a
# WRONG answer rather than a slow one. `get_thread(1)` across two walls returned two
# unrelated roots stapled together; `by_id(1)` returned whichever node the registry
# happened to list first. `latest_skill` belongs here because ADR-0004 anchors a skill
# by slug WITHIN a node, so two walls each holding a `readme` is the normal case.
_NODE_LOCAL_TOOLS = frozenset({"by_id", "get_thread", "latest_skill"})

# CLASS B: a per-node fact with no union implementation at all. Required at the account
# door; NOT ADVERTISED at the aggregate door, which cannot serve them — a door
# advertises only what it can serve, rather than listing a tool and then answering it
# with an error that is true of the wrong thing.
_PER_NODE_TOOLS = frozenset({"node_info", "list_skills", "audit_doctor", "ghosts"})

# What `_call_aggregator` actually dispatches. Hand-maintained sets rot; the anti-drift
# test in tests/test_node_local_ids.py drives every tool through the real method and
# fails if this set and that method ever disagree.
_AGGREGATOR_TOOLS = frozenset(
    {
        "recent",
        "by_id",
        "get_thread",
        "search_by_tag",
        "search_by_tag_exact",
        "search_text",
        "list_tags",
        "list_agents",
        "list_entry_types",
        "upcoming_dates",
        "read_stats",
        "list_nodes",
        "instructions",
    }
)

_NODE_ARG = {
    "type": "string",
    "description": "which node — required here because this endpoint serves several; "
    "call list_nodes for the slugs, and note that every row names its node in 'source'",
}


def unknown_node_error(named, reachable) -> MCPError:
    """The one error for a node this endpoint does not reach — reads and writes alike.

    >>> unknown_node_error("tets-0", {"test-0": "…"}).message
    "unknown node 'tets-0'; this endpoint reaches: test-0"
    """
    reach = ", ".join(sorted(reachable)) if reachable else "(no nodes yet)"
    return MCPError(
        "validation",
        f"unknown node {named!r}; this endpoint reaches: {reach}",
        hint="call list_nodes for the available nodes",
    )


def _with_node_required(defs: list[dict], needs_node: frozenset[str]) -> list[dict]:
    """Copy ``defs``, adding a REQUIRED ``node`` to every tool named in ``needs_node``.

    One expression, derived from the sets above and never retyped, so a tool added to
    a class later cannot get its requirement in one place and not the others.
    """
    out = []
    for original in defs:
        tool = copy.deepcopy(original)
        if tool["name"] in needs_node:
            tool["inputSchema"]["properties"]["node"] = dict(_NODE_ARG)
            tool["inputSchema"]["required"] = [*tool["inputSchema"]["required"], "node"]
        out.append(tool)
    return out


def account_tool_defs(defs: list[dict] | None = None) -> list[dict]:
    """The account door's surface: ``node`` REQUIRED on classes A, B and D.

    ADR-0014 §3: ``tools/list`` is answered per connection, so a door that reaches
    several nodes advertises a different schema from one that reaches a single node.
    Requiring ``node`` is the structural half of §4's "no default node" and of §11's
    node-local rule: a misfile becomes a WRONG argument rather than a FORGOTTEN one,
    and on an append-only store a misfile can only be corrected, never taken back.
    The spanning reads (class C) are untouched — that is the door's whole value.

    >>> [t["inputSchema"]["required"] for t in account_tool_defs()
    ...  if t["name"] == "log_entry"]
    [['agent', 'entry_type', 'content', 'node']]
    >>> [t["inputSchema"]["required"] for t in account_tool_defs()
    ...  if t["name"] == "by_id"]
    [['entry_id', 'node']]
    >>> [t["inputSchema"]["required"] for t in account_tool_defs()
    ...  if t["name"] == "recent"]
    [[]]
    """
    source = defs if defs is not None else TOOL_DEFS
    return _with_node_required(source, _WRITE_TOOLS | _NODE_LOCAL_TOOLS | _PER_NODE_TOOLS)


def aggregator_tool_defs(defs: list[dict] | None = None) -> list[dict]:
    """The aggregate door's surface: what it can serve, plus the writes it refuses.

    A door advertises only what it can serve (ADR-0014 §11), so the class-B reads and
    ``latest_skill`` — which ``_call_aggregator`` has no union for — are dropped rather
    than listed and then answered with "not available on the aggregator endpoint", an
    error that is true of the wrong thing at the door a new user meets first.

    ⚠ THE TWO WRITES STAY LISTED, DELIBERATELY. Their refusal ("address a specific node
    to write") is the teaching surface ADR-0008 built, and the ``query_only`` guard
    behind it is a safety property worth exercising. The asymmetry is on purpose; do
    not tidy it away.

    >>> len(aggregator_tool_defs())
    15
    >>> [t["inputSchema"]["required"] for t in aggregator_tool_defs()
    ...  if t["name"] == "get_thread"]
    [['root_id', 'node']]
    """
    source = defs if defs is not None else TOOL_DEFS
    served = [t for t in source if t["name"] in _AGGREGATOR_TOOLS | _WRITE_TOOLS]
    return _with_node_required(served, _NODE_LOCAL_TOOLS)


def _dates_args(args: dict) -> dict:
    """The upcoming_dates kwargs, defaulted the same way in both server modes."""
    within = args.get("within_days")
    return {
        "within_days": 45 if within is None else int(within),
        "prefix": args.get("prefix") or "killdate",
        "today": args.get("today"),
    }


def _stats_args(args: dict) -> dict:
    """The read_stats kwargs, defaulted the same way in both server modes."""
    within = args.get("within_days")
    return {
        "within_days": 7 if within is None else int(within),
        "today": args.get("today"),
    }


def _stamp_source(payload, slug: str):
    """Stamp ``source = slug`` through a payload served from ONE node (ADR-0014 §11).

    Only ``nodes`` mode calls this. ``_call_single`` stamps nothing — it was written
    for a door where the node is the connector — so without this the account door
    answers a SPANNING read with provenance and a NODE-NAMED read without it, which is
    exactly backwards for a citation convention. Write receipts are included: a bare
    ``{"id": 412}`` from a door serving six walls is a number nobody can cite.

    It also overwrites ``source`` on dated rows, because a single-node
    ``upcoming_dates`` fills that key with the node's human LABEL while at a
    multi-node door the addressable value is the registry SLUG (§11, one namespace).

    >>> _stamp_source({"id": 412}, "umbrella")
    {'id': 412, 'source': 'umbrella'}
    """
    if isinstance(payload, list):
        for item in payload:
            _stamp_source(item, slug)
    elif isinstance(payload, dict):
        payload["source"] = slug
        for key in ("latest", "readme"):  # list_skills rows, instructions.readme
            if isinstance(payload.get(key), dict):
                payload[key]["source"] = slug
        for key in ("dates", "warnings"):  # the upcoming_dates envelope
            for row in payload.get(key) or []:
                if isinstance(row, dict):
                    row["source"] = slug
    return payload


def _tags_to_str(tags) -> str | None:
    if tags is None:
        return None
    if isinstance(tags, list):
        return ",".join(str(t) for t in tags)
    return str(tags)


class MCPServer:
    """Dispatches MCP JSON-RPC requests against a node, a node map, or an aggregator.

    Construct with exactly one of ``db_path`` (writable single node), ``nodes``
    (writable over several named nodes — ADR-0014's account door) or ``aggregator``
    (read-only over-many). ``handle(request)`` is pure and testable without HTTP.
    """

    def __init__(
        self,
        db_path=None,
        *,
        aggregator=None,
        nodes=None,
        profile=None,
        api_key=None,
        meter_path=None,
        tool_defs=None,
    ):
        given = [
            n
            for n, v in (("db_path", db_path), ("aggregator", aggregator), ("nodes", nodes))
            if v is not None
        ]
        if len(given) != 1:
            raise ValueError(
                "MCPServer requires exactly one of db_path, aggregator or nodes"
                + (f" (got {', '.join(given)})" if given else " (got none)")
            )
        self._db = db_path
        # `is not None`, never truthiness: an account with ZERO nodes is a real state
        # (a founder who just signed up), and an empty map must give a working, empty
        # door rather than falling through to single-node mode with no db_path.
        self._nodes = {str(k): str(v) for k, v in nodes.items()} if nodes is not None else None
        # In nodes mode the aggregator is OURS, built over the same map, and it exists
        # only to serve reads that span nodes. A write never touches it.
        self._agg = (
            aggregator
            if aggregator is not None
            else (_aggregator_factory(nodes=self._nodes) if self._nodes is not None else None)
        )
        self._profile = profile
        self._api_key = api_key
        # ⚠ EXPLICIT, NOT DERIVED (ADR-0014; order §0.2). `aggregator is not None` is
        # true in BOTH aggregator and nodes mode now, so deriving read-only from it
        # would open _aggregate to writes without a single line looking wrong.
        self._mode = (
            "aggregator"
            if aggregator is not None
            else ("nodes" if self._nodes is not None else "single")
        )
        self._read_only = self._mode == "aggregator"
        # The meter (umbrella #228 Layer 3) lives beside the node it measures. With no
        # single home node — aggregator or nodes mode — the caller supplies one; without
        # it, metering is off and read_stats says so in warnings rather than pretending
        # to be zero.
        if meter_path is None and db_path is not None:
            meter_path = meter.default_meter_path(db_path)
        if meter_path is None and self._mode == "nodes":
            # Refused rather than silently unmetered: an endpoint whose meter is a no-op
            # is this stack's recurring sin (an instrument with no reader), and it was
            # caught once already this week on the aggregate unit (boonyard #145).
            raise ValueError("MCPServer(nodes=…) requires a meter_path — no single home node")
        self._meter_path = meter_path
        self._profiles: dict[str, object] = {}
        # Per-instance tool surface (ADR-0014 §3): the module-level TOOL_DEFS stays the
        # default; this server validates against ITS OWN set, never the module's.
        self._tool_defs = (
            tool_defs
            if tool_defs is not None
            else {
                "nodes": account_tool_defs,
                "aggregator": aggregator_tool_defs,
                "single": lambda: TOOL_DEFS,
            }[self._mode]()
        )
        self._tool_names = {t["name"] for t in self._tool_defs}
        self._tool_required = {t["name"]: t["inputSchema"]["required"] for t in self._tool_defs}
        self._node_name: str | None = None
        self._node_name_resolved = False

    # -- JSON-RPC entry ----------------------------------------------------
    def handle(self, request: dict) -> dict | None:
        """Handle one JSON-RPC request; return a response, or None for notifications."""
        rid = request.get("id")
        method = request.get("method")
        if method in ("notifications/initialized", "initialized"):
            return None
        try:
            if method == "initialize":
                from .instructions import instructions_text  # lazy: instructions imports mcp

                result = {
                    "protocolVersion": _PROTOCOL_VERSION,
                    "capabilities": {"tools": {}},
                    "serverInfo": {
                        "name": "boonyard",
                        "version": __import__("boonyard").__version__,
                    },
                    # The package readme, handed to the model on every connect (boonyard #125).
                    "instructions": instructions_text(),
                }
            elif method == "tools/list":
                result = {"tools": self._tool_defs}
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

    # -- which node is this call about? ------------------------------------
    def _target_node(self, args: dict) -> str | None:
        """The single node a call names, or None when it spans (ADR-0014 §1, §11).

        A call names a node with ``node``, or with a ``scope`` that is one string
        naming a node in this server's map (ADR-0008's meaning of scope, unchanged).
        Anything else — no argument, ``'all'``, a list — spans, and spanning is the
        aggregator's job. Returns None in every mode but ``nodes``.

        ⚠ AN UNREACHABLE ``node`` RAISES; IT NEVER FALLS THROUGH TO THE UNION
        (ADR-0014 §11). Returning None for a name we do not recognise would mean a
        typo — ``node="tets-0"`` — silently spans and hands back a plausible row from
        the wrong wall: the same wrong answer this amendment exists to kill, wearing a
        different hat. Requiring the argument does not fix that on its own; refusing
        an unknown value does.
        """
        if self._mode != "nodes":
            return None
        named = args.get("node")
        if named is not None:
            return self._require_node(named)
        scope = args.get("scope")
        if isinstance(scope, str) and scope in self._nodes:
            return scope
        return None

    def _require_node(self, named) -> str:
        """``named`` if this server reaches it, else the error that says what it does.

        The required-parameter check produces the MISSING case; this is the WRONG one,
        and it names the reachable slugs so a model that guessed can fix itself in one
        turn instead of guessing again. Reads and writes share it, so they cannot
        diverge (ADR-0014 §11).
        """
        if isinstance(named, str) and named in self._nodes:
            return named
        raise unknown_node_error(named, self._nodes)

    def _resolve_write_node(self, args: dict) -> str:
        """The node a write names. Same rule, same error, as every other caller."""
        return self._require_node(args.get("node"))

    # -- the meter ---------------------------------------------------------
    def _meter_node(self, args: dict) -> str | None:
        """Which node this call was served against, for the meter's ``node`` column."""
        if self._mode == "nodes":
            # Attribution here is better than the aggregator's scope-string fallback:
            # a write always names its node, so the meter records the node ADDRESSED.
            target = self._target_node(args)
            if target is not None:
                return target
            scope = args.get("scope")
            if isinstance(scope, str):
                return scope
            return ",".join(str(s) for s in scope) if scope else "all"
        if self._agg is not None:
            scope = args.get("scope")
            if isinstance(scope, str):
                return scope
            return ",".join(str(s) for s in scope) if scope else "all"
        if not self._node_name_resolved:  # resolved once, then cached
            self._node_name_resolved = True
            try:
                self._node_name = query.node_info(db_path=self._db)["name"]
            except Exception:  # noqa: BLE001 — never let identity lookup break a call
                self._node_name = None
        return self._node_name

    def _meter(self, name: str, args: dict) -> None:
        """Count one tool call. Tool name, node and kind only — never arguments.

        ``args`` is passed in solely to name the node; nothing from it is stored,
        and :func:`boonyard.meter.record` does not accept arguments at all.
        Classification reuses ``_WRITE_TOOLS`` so it cannot drift from the
        read-only enforcement above.
        """
        node = self._meter_node(args)
        meter.record(
            self._meter_for(node),
            name,
            node=node,
            kind="write" if name in _WRITE_TOOLS else "read",
        )

    # -- tool dispatch -----------------------------------------------------
    def _call_tool(self, name, args: dict):
        # Validated against THIS server's surface, never the module's: the account door
        # advertises `node` as required on writes and must enforce what it advertised.
        if name not in self._tool_names:
            raise MCPError("validation", f"unknown tool {name!r}", hint="call tools/list")
        for field_name in self._tool_required[name]:
            if args.get(field_name) is None:
                raise MCPError("validation", f"missing required parameter {field_name!r}")
        if self._read_only and name in _WRITE_TOOLS:
            raise MCPError(
                "read_only",
                "aggregator endpoint is read-only; address a specific node to write",
            )
        # Resolved BEFORE the meter, because an unreachable node is a refused call and a
        # refused call should not be counted as an attempt against a node that does not
        # exist. Raises the reachable-slugs error (ADR-0014 §11).
        target = self._target_node(args) if self._mode == "nodes" else None
        # Counted before dispatch: an attempt that then errors is still an attempt,
        # and record() cannot raise, so this can never break the call below.
        self._meter(name, args)
        if self._mode == "nodes":
            # ADR-0014 §1: a call that names a node is served against that node's file,
            # exactly as single-node mode does; a read that names none, or several, is
            # served by the aggregator. A write ALWAYS names one, and every class-A and
            # class-B tool is advertised as requiring one (§11).
            if name in _WRITE_TOOLS:
                target = self._resolve_write_node(args)
            if target is not None:
                payload = self._call_single(name, args, db=self._nodes[target])
                # §11 provenance: at a door serving several walls, a payload that does
                # not name its node is a citation nobody can follow — write receipts
                # included. Stamped BEFORE the read-heat hook: it improves attribution
                # and must not change it.
                _stamp_source(payload, target)
            else:
                payload = self._call_aggregator(name, args)
        elif self._agg is not None:
            payload = self._call_aggregator(name, args)
        else:
            payload = self._call_single(name, args)
        # Read heat (ADR-0013 §2a): a SEPARATE hook, AFTER dispatch, on the ids the read
        # RETURNED — never the query, never the caller. record_hits() cannot raise and
        # this wrapper cannot either, so a broken sidecar never breaks a read.
        try:
            self._hits(name, args, payload)
        except Exception:  # noqa: BLE001 — telemetry must not break the read it measures
            pass
        return payload

    # -- read heat ---------------------------------------------------------
    @staticmethod
    def _returned_ids(name: str, payload) -> list[tuple[str | None, int]]:
        """(source-or-None, entry_id) pairs a READ tool returned; [] for everything else."""
        if payload is None:
            return []
        if name in ("recent", "search_text", "search_by_tag", "search_by_tag_exact", "get_thread"):
            return [
                (e.get("source"), e["id"]) for e in payload if isinstance(e, dict) and "id" in e
            ]
        if name == "list_skills":
            return [
                (s["latest"].get("source"), s["latest"]["id"])
                for s in payload
                if isinstance(s, dict) and isinstance(s.get("latest"), dict)
            ]
        if name in ("by_id", "latest_skill"):
            return [(payload.get("source"), payload["id"])] if isinstance(payload, dict) else []
        if name == "upcoming_dates":
            return [
                (d.get("source"), d["entry_id"])
                for d in payload.get("dates", [])
                if isinstance(d, dict) and d.get("entry_id") is not None
            ]
        if name == "instructions":
            readme = payload.get("readme") if isinstance(payload, dict) else None
            return [(readme.get("source"), readme["id"])] if isinstance(readme, dict) else []
        return []

    def _meter_for(self, node: str | None):
        """Which meter file a fact about ``node`` belongs in.

        ⚠ IN ``nodes`` MODE, EVERY PER-NODE FACT GOES IN THAT NODE'S OWN ``meter.db``,
        not the account's. Entry ids are per node — alpha's #5 and beta's #5 are
        different entries — and ``views.ghosts`` looks read-heat up by entry id without
        a node filter. Pooling several nodes' heat in one file would therefore let one
        node's reads mark another node's entries as read, and `ghosts` would quietly
        stop finding real orphans. Keeping heat where the node lives also means the
        account door and that node's own door agree about it, which is ADR-0006's
        promise. The account's own ``meter_path`` then holds exactly what has no single
        node: the spanning calls.
        """
        if self._mode == "nodes" and node is not None and node in self._nodes:
            return meter.default_meter_path(self._nodes[node])
        return self._meter_path

    def _hits(self, name: str, args: dict, payload) -> None:
        """Record the ids a read returned.

        Aggregator rows carry ``source`` (their node), so hits are attributed per row;
        a row without one falls back to the scope string, exactly as ``_meter_node``.
        """
        pairs = self._returned_ids(name, payload)
        if not pairs:
            return
        default_node = self._meter_node(args)
        by_node: dict[str | None, list[int]] = {}
        for source, eid in pairs:
            by_node.setdefault(source if source is not None else default_node, []).append(eid)
        for node, ids in by_node.items():
            meter.record_hits(self._meter_for(node), name, node=node, entry_ids=ids)

    def _profile_for(self, db):
        """The profile that governs soft validation for the node being served.

        In ``nodes`` mode there is no single profile, so each node's own
        ``boonyard.toml`` is loaded from beside its file and cached. Without this, a
        write through the account door would be soft-validated by nothing while the
        same write through that node's own door is validated by its profile — and
        ADR-0006 promises the two doors behave identically.
        """
        if self._mode != "nodes":
            return self._profile
        if db not in self._profiles:
            from pathlib import Path

            from .profile import load_profile

            try:
                self._profiles[db] = load_profile(Path(db).parent / "boonyard.toml")
            except Exception:  # noqa: BLE001 — a missing/broken profile must not block a write
                self._profiles[db] = None
        return self._profiles[db]

    def _call_single(self, name, args: dict, *, db=None):
        """Serve one call against ONE node file.

        ``db`` is explicit in ``nodes`` mode (the node the call named) and defaults to
        the server's own node in single-node mode.
        """
        db = db if db is not None else self._db
        profile = self._profile_for(db)
        # read_stats and ghosts read the meter; in nodes mode that is the NODE's meter,
        # so both doors answer the same question the same way (see _meter_for).
        meter_path = meter.default_meter_path(db) if self._mode == "nodes" else self._meter_path
        if name == "log_entry":
            new_id = log_entry(
                args["agent"],
                args["entry_type"],
                args["content"],
                related_id=args.get("related_id"),
                tags=_tags_to_str(args.get("tags")),
                extras=args.get("extras"),
                db_path=db,
                profile=profile,
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
        if name == "upcoming_dates":
            return query.upcoming_dates(db_path=db, **_dates_args(args))
        if name == "read_stats":
            return meter.read_stats(meter_path=meter_path, **_stats_args(args))
        if name == "node_info":
            return query.node_info(db_path=db, profile=profile)
        if name == "audit_doctor":
            return query.audit_doctor(db_path=db, profile=profile)
        if name == "instructions":
            from .instructions import instructions_text

            return {
                "package": instructions_text(),
                "version": __import__("boonyard").__version__,
                "readme": query.latest_skill("readme", db_path=db),
            }
        if name == "ghosts":
            return views.ghosts(
                int(args.get("limit") or 20),
                int(args.get("older_than_days") or 30),
                db_path=db,
                meter_path=meter_path,
            )
        if name == "list_nodes":
            info = query.node_info(db_path=db, profile=profile)
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
        if name in _NODE_LOCAL_TOOLS:
            # ADR-0014 §11: a node-local argument is read against exactly ONE node, so
            # the union is unreachable rather than merely discouraged. `get_thread(1)`
            # unioned here once and returned two unrelated roots as one thread.
            named = args.get("node")
            if not isinstance(named, str) or named not in agg.nodes():
                raise unknown_node_error(named, agg.nodes())
            scope = named
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
        if name == "upcoming_dates":
            return agg.upcoming_dates(scope=scope, **_dates_args(args))
        if name == "read_stats":
            return agg.read_stats(scope=scope, **_stats_args(args))
        if name == "list_nodes":
            return agg.list_nodes()
        if name == "instructions":
            # Like node_info, a readme is a per-node thing: the aggregator serves the
            # package half and points at the node's own endpoint for the rest.
            from .instructions import instructions_text

            return {
                "package": instructions_text(),
                "version": __import__("boonyard").__version__,
                "readme": None,
                "note": "aggregator endpoint: a node's readme is served by that node's endpoint",
            }
        raise MCPError("validation", f"tool {name!r} is not available on the aggregator endpoint")


# --------------------------------------------------------------------------
# HTTP transport (stateless JSON-RPC over POST)
# --------------------------------------------------------------------------
def _jsonrpc_error(code: int, message: str, err: str) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": None,
        "error": {"code": code, "message": message, "data": {"error": err}},
    }


def make_handler(server: MCPServer):
    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # quiet by default (never log the URL — it may carry the key)
            pass

        def _send(self, status: int, payload: dict | None, extra_headers: dict | None = None):
            body = b"" if payload is None else json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            for name, value in (extra_headers or {}).items():
                self.send_header(name, value)
            self.end_headers()
            if body:
                self.wfile.write(body)

        def _authenticated(self) -> bool:
            """True if no key is configured, or the key is presented via header or path.

            Capability-URL auth (design-seat call): the Claude app's connector dialog
            has no header field, so the key may arrive EITHER as
            ``Authorization: Bearer <key>`` OR as the leading URL path segment
            (``POST https://host/<key>``). Timing-safe on both paths.
            """
            if not server._api_key:
                return True
            header = self.headers.get("Authorization", "")
            if header and hmac.compare_digest(header, f"Bearer {server._api_key}"):
                return True
            segment = self.path.split("?", 1)[0].strip("/").split("/")[0]
            return bool(segment) and hmac.compare_digest(segment, server._api_key)

        def do_GET(self):
            # Streamable HTTP uses GET to open a server->client SSE stream. We don't
            # offer one (request/response only), so the spec-correct answer is 405.
            self._send(
                405,
                _jsonrpc_error(-32601, "method not allowed; POST JSON-RPC", "validation"),
                extra_headers={"Allow": "POST"},
            )

        def do_POST(self):
            if not self._authenticated():
                self._send(
                    401,
                    _jsonrpc_error(
                        _JSONRPC_CODE["not_authenticated"], "not authenticated", "not_authenticated"
                    ),
                )
                return
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b"{}"
            try:
                request = json.loads(raw)
            except json.JSONDecodeError:
                self._send(400, _jsonrpc_error(-32700, "parse error", "validation"))
                return
            response = server.handle(request)
            # A JSON-RPC response -> 200 with body; a notification (no response) ->
            # 202 Accepted with no body, per the MCP Streamable HTTP transport.
            self._send(200 if response is not None else 202, response)

    return _Handler


def make_httpd(
    server: MCPServer, host: str = "127.0.0.1", port: int = DEFAULT_MCP_PORT
) -> ThreadingHTTPServer:
    """Build (but don't start) a threaded HTTP server for ``server``. Port 0 = ephemeral.

    Threaded so one slow client can't block all seats — this is a standing service
    fronted by a tunnel, not a one-request-at-a-time toy. Each tool call opens its
    own SQLite connection (per-thread), so concurrency is safe (WAL readers don't
    block; writers serialize at the SQLite layer).
    """
    return ThreadingHTTPServer((host, port), make_handler(server))


def serve(
    db_path=None,
    *,
    aggregator=None,
    profile=None,
    api_key=None,
    meter_path=None,
    host: str = "127.0.0.1",
    port: int = DEFAULT_MCP_PORT,
) -> None:
    """Run the MCP server forever on ``host:port`` (blocks). Ctrl-C to stop."""
    server = MCPServer(
        db_path=db_path,
        aggregator=aggregator,
        profile=profile,
        api_key=api_key,
        meter_path=meter_path,
    )
    httpd = make_httpd(server, host, port)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.shutdown()
