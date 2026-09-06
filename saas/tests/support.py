"""Shared fixtures for the slice-1 tests. Not a test module (no ``test_`` prefix).

Everything that touches the substrate goes through ``boonyardnn.adapter`` —
never ``import boonyard`` here (``test_adapter_rule`` greps for it).
"""

import json
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path

from boonyardnn import provisioner
from boonyardnn.registry import Registry
from boonyardnn.router import Router, make_httpd


def rpc(method: str, params: dict | None = None, rid: int = 1) -> dict:
    return {"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}


def tool_call(name: str, args: dict | None = None, rid: int = 1) -> dict:
    return rpc("tools/call", {"name": name, "arguments": args or {}}, rid=rid)


def payload_of(resp: dict) -> dict | list:
    """Unwrap a tools/call result envelope into the tool's JSON payload."""
    return json.loads(resp["result"]["content"][0]["text"])


class TmpRoot:
    """A throwaway data root with a Registry on it. Use as a context manager."""

    def __enter__(self) -> "TmpRoot":
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "data"
        self.registry = Registry(self.root)
        return self

    def __exit__(self, *exc) -> None:
        self._tmp.cleanup()

    def provision(self, user_slug: str, node_slug: str, *, label: str | None = None) -> str:
        """user add + node add + key add; returns the raw key."""
        if self.registry.get_user(user_slug) is None:
            provisioner.add_user(self.registry, user_slug, f"{user_slug}@example.test")
        provisioner.add_node(self.registry, user_slug, node_slug)
        raw, _key = provisioner.add_key(self.registry, user_slug, node_slug, label=label)
        return raw


class ServedRouter:
    """Start a router on an ephemeral port in a daemon thread; stop on exit."""

    def __init__(self, registry: Registry):
        self.router = Router(registry)
        self.httpd = make_httpd(self.router, host="127.0.0.1", port=0)
        self.port = self.httpd.server_address[1]
        self._thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self) -> "ServedRouter":
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()

    def url(self, path: str = "") -> str:
        return f"http://127.0.0.1:{self.port}/{path.lstrip('/')}"

    def post(self, path: str, body, headers: dict | None = None) -> tuple[int, dict | None, dict]:
        """POST JSON (or raw bytes) → (status, decoded body or None, response headers).

        HTTP errors are returned, not raised, so a 401 is an assertion target.
        """
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        req = urllib.request.Request(
            self.url(path),
            data=data,
            method="POST",
            headers={"Content-Type": "application/json", **(headers or {})},
        )
        return self._send(req)

    def get(self, path: str) -> tuple[int, dict | None, dict]:
        return self._send(urllib.request.Request(self.url(path), method="GET"))

    @staticmethod
    def _send(req) -> tuple[int, dict | None, dict]:
        try:
            with urllib.request.urlopen(req) as resp:
                raw = resp.read()
                return resp.status, (json.loads(raw) if raw else None), dict(resp.headers)
        except urllib.error.HTTPError as err:
            raw = err.read()
            return err.code, (json.loads(raw) if raw else None), dict(err.headers)
