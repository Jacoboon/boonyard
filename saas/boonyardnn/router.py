"""The router — one door, path-routed, per-request dispatch (ADR-0008, arch 05).

``POST /{user_slug}/{node_slug}[/{key}]`` resolves user → node → directory through
the registry, authenticates the per-node key, then constructs the package's own
``MCPServer`` for that node and returns ``server.handle(request)``. The tool
surface is therefore byte-identical to a self-hosted node (ADR-0006): this file
adds a door, not a dialect.

Access-control order is arch 05's, verbatim: resolve user (404) → resolve node
(404, same body — never reveal whether the user exists) → authenticate the key
(401) → check scope (403) → check the user is active (403) → dispatch. Rate limits
(ADR-0008's table) and ``_aggregate`` are Phase 3 / paid tier and are NOT here —
there is no placeholder pretending otherwise.

Auth forms (both, always): ``Authorization: Bearer bnyk_…`` (preferred — the
claude.ai connector dialog gained a header field by 2026-09-06) OR the key as the
trailing path segment — the capability-URL shape for clients that still lack one.
Comparison is ``hmac.compare_digest`` on sha256 hashes (registry).

**The URL is never logged.** It may carry the key. ``log_message`` is a no-op,
exactly as in the package; an unexpected exception logs its type name only.

Stdlib ``http.server`` only (design call (a), umbrella #335): no framework until
there is a dashboard to need one.
"""

import json
import sys
import time
from collections.abc import Callable, Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import __version__, adapter
from .registry import Registry, SlugError, validate_slug

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8800

# ADR-0008 spells the endpoint ``…/{node_slug}/sse`` (or ``/http``). The router
# is request/response only, so the suffix carries no meaning — but it must not
# 404 someone who typed the URL as the ADR wrote it.
_TRANSPORT_SUFFIXES = frozenset({"sse", "http"})

# (status, JSON body or None, extra headers)
Response = tuple[int, dict | None, dict[str, str]]


def _bearer(headers: Mapping[str, str]) -> str | None:
    value = headers.get("Authorization") or ""
    scheme, _, token = value.strip().partition(" ")
    if scheme.lower() == "bearer" and token.strip():
        return token.strip()
    return None


def _clean(path: str) -> str:
    return path.split("?", 1)[0].rstrip("/") or "/"


class Router:
    """Pure request dispatch — testable without sockets; ``make_handler`` wraps it.

    Example:
        router = Router(Registry("/data"))
        status, body, headers = router.handle_post("/jacoboon/test-0", {"Authorization":
            "Bearer bnyk_…"}, b'{"jsonrpc":"2.0","id":1,"method":"tools/list"}')
    """

    def __init__(self, registry: Registry, *, clock: Callable[[], float] = time.monotonic):
        self._registry = registry
        self._clock = clock
        self._started = clock()

    # -- path -----------------------------------------------------------------
    @staticmethod
    def parse_path(path: str) -> tuple[str, str, str | None] | None:
        """``/{user}/{node}[/sse|/http][/{key}]`` -> ``(user, node, key_or_None)``, else None.

        Both slugs must pass the slug rule (so ``..`` and uppercase never reach the
        filesystem); anything else in the path is a 404. The query string is ignored.

        Example:
            Router.parse_path("/jacoboon/test-0/bnyk_abc")  # -> ("jacoboon", "test-0", "bnyk_abc")
        """
        parts = [p for p in path.split("?", 1)[0].split("/") if p]
        if len(parts) > 2 and parts[2] in _TRANSPORT_SUFFIXES:
            del parts[2]
        if len(parts) not in (2, 3):
            return None
        try:
            user, node = validate_slug(parts[0]), validate_slug(parts[1])
        except SlugError:
            return None
        return user, node, (parts[2] if len(parts) == 3 else None)

    # -- responses ------------------------------------------------------------
    @staticmethod
    def _error(status: int, kind: str, message: str, *, code: int | None = None) -> Response:
        return status, adapter.jsonrpc_error(kind, message, code=code), {}

    @classmethod
    def _not_found(cls) -> Response:
        # One body for "no such user" and "no such node" (arch 05 rule 2).
        return cls._error(404, "not_found", "not found")

    def health(self) -> dict:
        """``/health``: versions, uptime and counts. No slugs, no paths.

        Example:
            router.health()  # -> {"status": "ok", "version": …, "users": 1, "nodes": 1, …}
        """
        counts = self._registry.counts()
        return {
            "status": "ok",
            "version": __version__,
            "boonyard": adapter.package_version(),
            "uptime_s": int(self._clock() - self._started),
            "users": counts["users"],
            "nodes": counts["nodes"],
        }

    def handle_get(self, path: str) -> Response:
        """GET: ``/health`` → 200; everything else → 405 (the package's stance: no SSE stream)."""
        if _clean(path) == "/health":
            return 200, self.health(), {}
        return (
            405,
            adapter.jsonrpc_error("validation", "method not allowed; POST JSON-RPC", code=-32601),
            {"Allow": "POST"},
        )

    def handle_post(self, path: str, headers: Mapping[str, str], body: bytes) -> Response:
        """POST: resolve, authenticate, dispatch to ``MCPServer.handle()``.

        Returns 200 with the JSON-RPC response, or 202 with no body for a
        notification — byte-compatible with the package's ``make_handler``.
        """
        if _clean(path) == "/health":
            return (
                405,
                adapter.jsonrpc_error("validation", "method not allowed; GET /health", code=-32601),
                {"Allow": "GET"},
            )
        parsed = self.parse_path(path)
        if parsed is None:
            return self._not_found()
        user_slug, node_slug, path_key = parsed

        user = self._registry.get_user(user_slug)
        if user is None:
            return self._not_found()
        node = self._registry.get_node(user, node_slug)
        if node is None:
            return self._not_found()

        presented = _bearer(headers) or path_key
        key = self._registry.authenticate(user, presented) if presented else None
        if key is None:
            return self._error(401, "not_authenticated", "not authenticated")
        if key.scope != f"node:{node.node_id}":
            return self._error(403, "not_authorized", "key is not authorized for this node")
        if user.status != "active":
            return self._error(403, "not_authorized", "user is not active")

        try:
            request = json.loads(body or b"{}")
        except json.JSONDecodeError:
            request = None
        if not isinstance(request, dict):
            return self._error(400, "validation", "parse error", code=-32700)

        node_dir = self._registry.node_dir(user, node)
        server = adapter.make_server(
            node_dir / "journal.db",
            profile_path=node_dir / "boonyard.toml",
            meter_path=node_dir / "meter.db",
        )
        response = server.handle(request)

        # Hygiene, not audit: coarse, and a failed touch must not fail the call (§2.1).
        try:
            self._registry.touch_key(user, key.key_id)
        except Exception:  # noqa: BLE001 — never let bookkeeping break a served request
            pass

        return (200 if response is not None else 202), response, {}


# --------------------------------------------------------------------------
# HTTP transport
# --------------------------------------------------------------------------
def make_handler(router: Router):
    """A ``BaseHTTPRequestHandler`` bound to one router. Never logs the URL."""

    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # the URL may carry the key — never log it
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

        def _dispatch(self, fn):
            try:
                status, payload, headers = fn()
            except Exception as exc:  # noqa: BLE001 — type name only; no path, no key
                print(f"boonyardnn: internal error: {type(exc).__name__}", file=sys.stderr)
                status, payload, headers = (
                    500,
                    adapter.jsonrpc_error("internal", "internal error"),
                    {},
                )
            self._send(status, payload, headers)

        def do_GET(self):
            self._dispatch(lambda: router.handle_get(self.path))

        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            self._dispatch(lambda: router.handle_post(self.path, self.headers, raw))

    return _Handler


def make_httpd(
    router: Router, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT
) -> ThreadingHTTPServer:
    """Build (but don't start) the threaded server. Port 0 = ephemeral (tests).

    Threaded for the same reason the package is: one slow seat must not block the
    door for everyone. Each request opens its own SQLite connections (WAL).

    Example:
        httpd = make_httpd(Router(reg), port=0); httpd.server_address[1]
    """
    return ThreadingHTTPServer((host, port), make_handler(router))


def serve(registry: Registry, *, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
    """Run the router forever on ``host:port`` (blocks). Ctrl-C to stop."""
    httpd = make_httpd(Router(registry), host, port)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.shutdown()
    finally:
        httpd.server_close()
