"""Shared fixtures for the slice-1 tests. Not a test module (no ``test_`` prefix).

Everything that touches the substrate goes through ``boonyardnn.adapter`` —
never ``import boonyard`` here (``test_adapter_rule`` greps for it).
"""

import json
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from boonyardnn import provisioner
from boonyardnn.accounts import Accounts
from boonyardnn.mailer import LogMailer
from boonyardnn.registry import Registry
from boonyardnn.router import Router, make_httpd
from boonyardnn.web import PREFIX, WebApp, make_web_httpd


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

    def __init__(self, registry: Registry, *, router: Router | None = None):
        self.router = router or Router(registry)
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


class ServedWeb:
    """Start the web app on an ephemeral port with a LogMailer; a tiny cookie-keeping client.

    Redirects are NOT followed (a 303 is an assertion target); cookies from
    ``Set-Cookie`` are kept per client and sent back on every request.
    """

    def __init__(
        self, registry: Registry, accounts: Accounts, *, mcp_base: str = "http://mcp.test"
    ):
        self.mailer = LogMailer()
        self.app = WebApp(
            registry,
            accounts,
            self.mailer,
            web_base="http://127.0.0.1:0",  # patched once the port is known
            mcp_base=mcp_base,
            secure_cookies=False,
        )
        self.httpd = make_web_httpd(self.app, host="127.0.0.1", port=0)
        self.port = self.httpd.server_address[1]
        self.app.web_base = f"http://127.0.0.1:{self.port}"
        self._thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.cookies: dict[str, str] = {}

    def __enter__(self) -> "ServedWeb":
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()

    def url(self, path: str = "/") -> str:
        return f"http://127.0.0.1:{self.port}{PREFIX}{path}"

    def _send(self, req) -> tuple[int, dict, bytes]:
        if self.cookies:
            req.add_header("Cookie", "; ".join(f"{k}={v}" for k, v in self.cookies.items()))
        opener = urllib.request.build_opener(_NoRedirect)
        try:
            with opener.open(req) as resp:
                status, headers, body = resp.status, resp.headers, resp.read()
        except urllib.error.HTTPError as err:
            status, headers, body = err.code, err.headers, err.read()
        for value in headers.get_all("Set-Cookie") or []:
            name, _, rest = value.partition("=")
            val = rest.split(";", 1)[0]
            if "Max-Age=0" in value or not val:
                self.cookies.pop(name.strip(), None)
            else:
                self.cookies[name.strip()] = val
        return status, dict(headers), body

    def get(self, path: str, headers: dict | None = None) -> tuple[int, dict, bytes]:
        return self._send(urllib.request.Request(self.url(path), headers=headers or {}))

    def post(self, path: str, form: dict, headers: dict | None = None) -> tuple[int, dict, bytes]:
        data = urllib.parse.urlencode(form).encode()
        req = urllib.request.Request(
            self.url(path),
            data=data,
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded", **(headers or {})},
        )
        return self._send(req)

    def last_link(self) -> str:
        """The first http(s) URL in the most recent captured mail."""
        text = self.mailer.sent[-1]["text"]
        for token in text.split():
            if token.startswith("http://") or token.startswith("https://"):
                return token
        raise AssertionError("no link in the last mail")

    def csrf(self) -> str:
        """The CSRF token of the current session, read from the dashboard form."""
        status, _headers, body = self.get("/")
        assert status == 200, status
        marker = b'name="csrf" value="'
        start = body.index(marker) + len(marker)
        return body[start : body.index(b'"', start)].decode()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None
