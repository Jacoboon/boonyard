"""The web app — signup, verification, sign-in and the dashboard (slice 2).

Mounted at ``/app`` on its own loopback port behind nginx (``boonyard.com/app/…``).
Stdlib ``http.server`` like the router: the pages are forms over calls that already
exist — ``provisioner.add_user/add_node/add_key/revoke_key/export_node`` — so this
file adds screens, not a second provisioning path. Everything a user writes is
escaped on the way out; every state-changing POST carries the session's CSRF token.

Routes (all under ``/app``):

    GET  /signup              POST /signup            GET /verify?t=…
    GET  /login               POST /login             GET /login/link?t=…
    POST /logout              GET  /                  (the dashboard)
    POST /nodes               POST /nodes/{slug}/keys POST /keys/{id}/revoke
    GET  /nodes/{slug}/export POST /password
    GET  /founders.json       GET  /privacy           GET /health

Never logs a URL: verification and sign-in links carry their token in the query
string, so ``log_message`` is a no-op here as in the router, and the nginx location
in front of this port runs with ``access_log off``.
"""

import html
import http.cookies
import json
import sys
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import NamedTuple
from urllib.parse import parse_qs, quote, urlencode

from . import __version__, provisioner
from .accounts import PASSWORD_MIN, Account, AccountError, Accounts, TokenError
from .mailer import MailError, login_mail, verify_mail
from .registry import Registry, RegistryError, SlugError, validate_slug

PREFIX = "/app"
COOKIE = "bnys"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_WEB_PORT = 8801
MAX_BODY = 64 * 1024
MAX_LABEL = 64
FREE_NODE_CAP = 3  # ADR-0007 / arch 07: Free = 3 nodes. Founders are Pro for a year: no cap.
SESSION_MAX_AGE = 30 * 24 * 3600

Response = tuple[int, list[tuple[str, str]], bytes]


class _Session(NamedTuple):
    """A signed-in request: the account and its CSRF token."""

    account: Account
    csrf: str


_FLASH = {
    "node-created": "Node created. Mint a key to connect a seat to it.",
    "key-revoked": "Key revoked. Any seat using it is now refused.",
    "password-set": "Password saved. You can sign in with it or with an emailed link.",
    "signed-in": "Signed in.",
}


@dataclass
class Request:
    """One HTTP request, already split from the transport."""

    method: str
    path: str  # relative to PREFIX; always starts with "/"
    query: dict[str, str]
    headers: Mapping[str, str]
    body: bytes
    ip: str
    cookies: dict[str, str] = field(default_factory=dict)

    @property
    def form(self) -> dict[str, str]:
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype != "application/x-www-form-urlencoded" or not self.body:
            return {}
        return _first(parse_qs(self.body.decode("utf-8", "replace"), keep_blank_values=True))


def _first(qs: dict[str, list[str]]) -> dict[str, str]:
    return {k: v[0] for k, v in qs.items() if v}


def _esc(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _date(iso: str | None) -> str:
    return (iso or "")[:10]


# --------------------------------------------------------------------------
# HTML
# --------------------------------------------------------------------------
_CSS = """
:root{--bg:#0e1116;--panel:#161b22;--text:#d6dde6;--muted:#8b96a5;--accent:#e8b44c;
 --accent-dim:#9c7a35;--border:#2a313b;--bad:#e06c75;
 --mono:"SF Mono","Cascadia Code",Consolas,monospace}
*{margin:0;padding:0;box-sizing:border-box}
body{background:var(--bg);color:var(--text);font:16px/1.6 Georgia,"Times New Roman",serif}
main{max-width:720px;margin:0 auto;padding:3rem 1.25rem 2rem}
h1{font-family:var(--mono);font-size:1.6rem;color:var(--accent);margin-bottom:.25rem}
h1 a{color:var(--accent);text-decoration:none}
h2{font-family:var(--mono);font-size:1rem;color:var(--accent);margin:2rem 0 .6rem;
 text-transform:lowercase}
h2::before{content:"## ";color:var(--accent-dim)}
p{margin-bottom:.9rem}.muted{color:var(--muted)}
a{color:var(--accent)}
code,.key{font-family:var(--mono);font-size:.85em;background:var(--panel);
 border:1px solid var(--border);border-radius:4px;padding:.1em .4em}
.key{display:block;padding:.6rem .8rem;word-break:break-all;font-size:.95em;margin:.5rem 0}
.panel{background:var(--panel);border:1px solid var(--border);border-radius:8px;
 padding:1rem 1.25rem;margin-bottom:1rem}
label{display:block;font-family:var(--mono);font-size:.8rem;color:var(--muted);
 margin:.6rem 0 .2rem}
input[type=text],input[type=email],input[type=password]{width:100%;padding:.5rem .6rem;
 background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:4px;
 font:inherit}
button{font-family:var(--mono);font-size:.85rem;padding:.45rem .9rem;margin-top:.7rem;
 background:var(--accent);color:#0e1116;border:0;border-radius:4px;cursor:pointer}
button.quiet{background:transparent;color:var(--muted);border:1px solid var(--border)}
button.danger{background:transparent;color:var(--bad);border:1px solid var(--bad);
 margin-top:0;padding:.2rem .5rem;font-size:.75rem}
.err{color:var(--bad);font-family:var(--mono);font-size:.85rem;margin:.5rem 0}
.ok{color:var(--accent);font-family:var(--mono);font-size:.85rem;margin:.5rem 0}
table{width:100%;border-collapse:collapse;font-family:var(--mono);font-size:.78rem;
 margin:.5rem 0}
th,td{text-align:left;padding:.35rem .4rem;border-bottom:1px solid var(--border);
 vertical-align:top}
th{color:var(--muted);font-weight:normal}
.inline{display:inline}
.tag{font-family:var(--mono);font-size:.75rem;color:var(--accent);
 border:1px solid var(--accent-dim);border-radius:4px;padding:.05em .4em}
footer{margin-top:3rem;padding-top:1rem;border-top:1px solid var(--border);
 color:var(--muted);font-family:var(--mono);font-size:.75rem}
footer a{color:var(--muted)}
"""


def _layout(title: str, body: str, *, nav: str = "") -> bytes:
    page = (
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{_esc(title)} · Boonyard</title><style>{_CSS}</style></head><body><main>"
        f'<h1><a href="{PREFIX}/">Boonyard</a></h1>'
        f'<p class="muted">{nav}</p>{body}'
        '<footer><a href="https://boonyard.com/">boonyard.com</a> · '
        f'<a href="{PREFIX}/privacy">privacy</a> · '
        '<a href="https://github.com/Jacoboon/boonyard">source</a> · '
        f"boonyardnn {_esc(__version__)}</footer></main></body></html>"
    )
    return page.encode("utf-8")


class WebApp:
    """Pure request → response; ``make_web_handler`` is the transport.

    Example:
        app = WebApp(Registry(root), Accounts(root), LogMailer(),
                     web_base="http://127.0.0.1:8801", mcp_base="http://127.0.0.1:8800")
        status, headers, body = app.handle(Request("GET", "/signup", {}, {}, b"", "127.0.0.1"))
    """

    def __init__(
        self,
        registry: Registry,
        accounts: Accounts,
        mailer,
        *,
        web_base: str,
        mcp_base: str,
        secure_cookies: bool | None = None,
    ):
        self.registry = registry
        self.accounts = accounts
        self.mailer = mailer
        self.web_base = web_base.rstrip("/")
        self.mcp_base = mcp_base.rstrip("/")
        self.secure_cookies = (
            self.web_base.startswith("https://") if secure_cookies is None else secure_cookies
        )
        self._started = time.monotonic()

    # -- dispatch -------------------------------------------------------------
    def handle(self, req: Request) -> Response:
        """Route one request. Unknown paths are 404; wrong methods are 405."""
        parts = [p for p in req.path.split("/") if p]
        get, post = req.method == "GET", req.method == "POST"
        if not parts:
            return self.dashboard(req) if get else self._method_not_allowed("GET")
        head = parts[0]
        if head == "signup" and len(parts) == 1:
            return self.signup_form(req) if get else self.signup(req)
        if head == "verify" and len(parts) == 1 and get:
            return self.verify(req)
        if head == "login":
            if len(parts) == 1:
                return self.login_form(req) if get else self.login(req)
            if len(parts) == 2 and parts[1] == "link" and get:
                return self.login_link(req)
        if head == "logout" and len(parts) == 1:
            return self.logout(req) if post else self._method_not_allowed("POST")
        if head == "nodes":
            if len(parts) == 1:
                return self.create_node(req) if post else self._method_not_allowed("POST")
            if len(parts) == 3 and parts[2] == "keys" and post:
                return self.mint_key(req, parts[1])
            if len(parts) == 3 and parts[2] == "export" and get:
                return self.export(req, parts[1])
        if head == "keys" and len(parts) == 3 and parts[2] == "revoke" and post:
            return self.revoke_key(req, parts[1])
        if head == "password" and len(parts) == 1:
            return self.set_password(req) if post else self._method_not_allowed("POST")
        if head == "founders.json" and len(parts) == 1 and get:
            return self.founders_json()
        if head == "privacy" and len(parts) == 1 and get:
            return self.privacy()
        if head == "health" and len(parts) == 1 and get:
            return self.health()
        return self._page("Not found", "<p>Nothing here.</p>", status=404)

    # -- response helpers -----------------------------------------------------
    @staticmethod
    def _security_headers() -> list[tuple[str, str]]:
        return [
            ("X-Content-Type-Options", "nosniff"),
            ("Referrer-Policy", "no-referrer"),
            ("X-Frame-Options", "DENY"),
            (
                "Content-Security-Policy",
                "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; "
                "base-uri 'none'; frame-ancestors 'none'",
            ),
        ]

    def _page(
        self,
        title: str,
        body: str,
        *,
        status: int = 200,
        headers: list[tuple[str, str]] | None = None,
        nav: str = "",
        private: bool = False,
    ) -> Response:
        hdrs = [("Content-Type", "text/html; charset=utf-8"), *self._security_headers()]
        hdrs.append(("Cache-Control", "no-store" if private else "no-cache"))
        hdrs.extend(headers or [])
        return status, hdrs, _layout(title, body, nav=nav)

    def _redirect(self, location: str, *, headers: list[tuple[str, str]] | None = None) -> Response:
        hdrs = [("Location", location), ("Cache-Control", "no-store"), *self._security_headers()]
        hdrs.extend(headers or [])
        return 303, hdrs, b""

    def _json(self, payload: dict, *, cache: str = "no-store") -> Response:
        body = json.dumps(payload).encode("utf-8")
        return 200, [("Content-Type", "application/json"), ("Cache-Control", cache)], body

    def _method_not_allowed(self, allow: str) -> Response:
        status, hdrs, body = self._page("Method not allowed", "<p>Wrong method.</p>", status=405)
        return status, [*hdrs, ("Allow", allow)], body

    def _cookie(self, raw: str | None) -> tuple[str, str]:
        parts = [f"{COOKIE}={raw or ''}", f"Path={PREFIX}", "HttpOnly", "SameSite=Lax"]
        parts.append(f"Max-Age={SESSION_MAX_AGE if raw else 0}")
        if self.secure_cookies:
            parts.append("Secure")
        return "Set-Cookie", "; ".join(parts)

    def _link(self, path: str, token: str) -> str:
        return f"{self.web_base}{PREFIX}{path}?{urlencode({'t': token})}"

    # -- session --------------------------------------------------------------
    def _current(self, req: Request) -> tuple[Account, str] | None:
        return self.accounts.session(req.cookies.get(COOKIE))

    def _require(self, req: Request, *, csrf: bool) -> _Session | Response:
        found = self._current(req)
        if found is None:
            return self._redirect(f"{PREFIX}/login")
        if csrf and req.form.get("csrf", "") != found[1]:
            return self._page(
                "Refused",
                "<p>That form has expired. Go back and try again.</p>",
                status=403,
                private=True,
            )
        return _Session(*found)

    def _rate(self, req: Request, kind: str) -> Response | None:
        if self.accounts.ip_allowed(req.ip, kind):
            return None
        return self._page(
            "Slow down",
            "<p>Too many attempts from your address. Try again in an hour.</p>",
            status=429,
        )

    def _mail(self, req: Request, to: str, kind: str, subject: str, text: str) -> Response | None:
        """Send, or return the page that explains why not (never a stack trace)."""
        if not self.accounts.mail_allowed(to, kind):
            return self._page(
                "Slow down",
                "<p>That address has had several emails from us in the last hour. "
                "Check your inbox (and spam) before asking for another.</p>",
                status=429,
            )
        try:
            self.mailer.send(to, subject, text)
        except MailError as exc:
            print(f"boonyardnn: mail failed: {type(exc).__name__}", file=sys.stderr)
            return self._page(
                "Email not sent",
                "<p>We could not send the email just now. Nothing was lost — try "
                "again in a few minutes, or write to "
                '<a href="mailto:hello@boonyard.com">hello@boonyard.com</a>.</p>',
                status=503,
            )
        return None

    # -- public pages ---------------------------------------------------------
    def _founders_line(self) -> str:
        f = self.accounts.founders()
        if f["open"] > 0:
            return (
                f"<span class=\"tag\">founders: {f['taken']} of {f['seats']} seats taken</span> "
                "<span class=\"muted\">— the first twenty accounts get a year free.</span>"
            )
        return '<span class="tag">founder seats: all taken</span>'

    def signup_form(
        self,
        req: Request,
        *,
        error: str | None = None,
        values: dict[str, str] | None = None,
        status: int = 200,
    ) -> Response:
        v = values or {}
        body = (
            f"<p>{self._founders_line()}</p>"
            f"{'<p class=\"err\">' + _esc(error) + '</p>' if error else ''}"
            f"<form method=\"post\" action=\"{PREFIX}/signup\" class=\"panel\">"
            "<label for=\"email\">email</label>"
            f"<input id=\"email\" name=\"email\" type=\"email\" required maxlength=\"254\" "
            f"value=\"{_esc(v.get('email', ''))}\" autocomplete=\"email\">"
            "<label for=\"slug\">username — lowercase letters, digits, hyphens; it becomes part of "
            "your MCP URL</label>"
            f"<input id=\"slug\" name=\"slug\" type=\"text\" required maxlength=\"40\" "
            f"value=\"{_esc(v.get('slug', ''))}\" autocomplete=\"username\" "
            "pattern=\"[a-z0-9]([a-z0-9-]{0,38}[a-z0-9])?\">"
            f"<label for=\"password\">password — optional (at least {PASSWORD_MIN} characters). "
            "Leave it blank to sign in by emailed link only.</label>"
            '<input id="password" name="password" type="password" '
            'autocomplete="new-password" '
            f"minlength=\"{PASSWORD_MIN}\" maxlength=\"256\">"
            "<button type=\"submit\">Create account</button>"
            "</form>"
            f"<p class=\"muted\">Already have one? <a href=\"{PREFIX}/login\">Sign in</a>. "
            f"What we store and what we can see: <a href=\"{PREFIX}/privacy\">privacy</a>.</p>"
        )
        return self._page("Sign up", body, status=status, nav="create your account")

    def signup(self, req: Request) -> Response:
        limited = self._rate(req, "signup")
        if limited:
            return limited
        form = req.form
        email, slug = form.get("email", ""), form.get("slug", "").strip()
        password = form.get("password", "") or None
        try:
            account, kind, token = self.accounts.begin_signup(
                email, slug, password, slug_available=lambda s: self.registry.get_user(s) is None
            )
        except (AccountError, SlugError) as exc:
            return self.signup_form(
                req, error=str(exc), values={"email": email, "slug": slug}, status=400
            )
        if kind == "verify":
            subject, text = verify_mail(self._link("/verify", token), slug=account.slug)
        else:
            subject, text = login_mail(self._link("/login/link", token))
        failed = self._mail(req, account.email, kind, subject, text)
        if failed:
            return failed
        return self._page(
            "Check your email",
            '<p class="ok">Check your email.</p>'
            "<p>If that address is new here, a confirmation link is on its way "
            "(it works for 24 hours). If it already had an account, we sent a "
            "sign-in link instead.</p>"
            '<p class="muted">Nothing arrived? Look in spam, then '
            f'<a href="{PREFIX}/signup">try again</a>.</p>',
            nav="one more step",
        )

    def verify(self, req: Request) -> Response:
        try:
            account = self.accounts.verify(req.query.get("t", ""))
        except TokenError as exc:
            return self._page(
                "Link not valid",
                f'<p class="err">{_esc(exc)}</p>'
                f'<p><a href="{PREFIX}/signup">Sign up again</a> or '
                f'<a href="{PREFIX}/login">sign in</a>.</p>',
                status=400,
            )
        if self.registry.get_user(account.slug) is None:
            try:
                provisioner.add_user(self.registry, account.slug, account.email)
            except RegistryError as exc:
                print(f"boonyardnn: provisioning failed: {type(exc).__name__}", file=sys.stderr)
                return self._page(
                    "Something went wrong",
                    "<p>Your address is confirmed but your workspace could not be "
                    "created. Write to hello@boonyard.com and we will fix it.</p>",
                    status=500,
                )
        raw, _csrf = self.accounts.open_session(account.account_id)
        return self._redirect(f"{PREFIX}/?m=signed-in", headers=[self._cookie(raw)])

    def login_form(
        self, req: Request, *, error: str | None = None, email: str = "", status: int = 200
    ) -> Response:
        body = (
            f"{'<p class=\"err\">' + _esc(error) + '</p>' if error else ''}"
            f"<form method=\"post\" action=\"{PREFIX}/login\" class=\"panel\">"
            "<label for=\"email\">email</label>"
            f"<input id=\"email\" name=\"email\" type=\"email\" required maxlength=\"254\" "
            f"value=\"{_esc(email)}\" autocomplete=\"email\">"
            "<label for=\"password\">password — if you set one</label>"
            "<input id=\"password\" name=\"password\" type=\"password\" "
            "autocomplete=\"current-password\" maxlength=\"256\">"
            '<button type="submit" name="action" value="password">'
            "Sign in with password</button> "
            "<button type=\"submit\" name=\"action\" value=\"link\" class=\"quiet\">"
            "Email me a sign-in link</button>"
            "</form>"
            f"<p class=\"muted\">New here? <a href=\"{PREFIX}/signup\">Create an account</a>.</p>"
        )
        return self._page("Sign in", body, status=status, nav="sign in")

    def login(self, req: Request) -> Response:
        limited = self._rate(req, "login")
        if limited:
            return limited
        form = req.form
        email = form.get("email", "")
        if form.get("action") == "link":
            found = self.accounts.request_login(email)
            if found is not None:
                account, token = found
                subject, text = login_mail(self._link("/login/link", token))
                failed = self._mail(req, account.email, "login", subject, text)
                if failed:
                    return failed
            return self._page(
                "Check your email",
                '<p class="ok">Check your email.</p>'
                "<p>If that address has a confirmed account, a sign-in link is on "
                "its way. It works once and expires in 20 minutes.</p>",
                nav="one more step",
            )
        account = self.accounts.login_with_password(email, form.get("password", ""))
        if account is None:
            return self.login_form(
                req,
                error="Wrong email or password — or no password is set "
                "on that account; use the emailed link instead.",
                email=email,
                status=400,
            )
        raw, _csrf = self.accounts.open_session(account.account_id)
        return self._redirect(f"{PREFIX}/?m=signed-in", headers=[self._cookie(raw)])

    def login_link(self, req: Request) -> Response:
        try:
            account = self.accounts.consume_login(req.query.get("t", ""))
        except TokenError as exc:
            return self._page(
                "Link not valid",
                f'<p class="err">{_esc(exc)}</p>'
                f'<p><a href="{PREFIX}/login">Ask for a new one</a>.</p>',
                status=400,
            )
        raw, _csrf = self.accounts.open_session(account.account_id)
        return self._redirect(f"{PREFIX}/?m=signed-in", headers=[self._cookie(raw)])

    def logout(self, req: Request) -> Response:
        found = self._current(req)
        if found is not None and req.form.get("csrf", "") == found[1]:
            self.accounts.close_session(req.cookies.get(COOKIE))
        return self._redirect(f"{PREFIX}/login", headers=[self._cookie(None)])

    def founders_json(self) -> Response:
        return self._json(self.accounts.founders(), cache="public, max-age=60")

    def health(self) -> Response:
        return self._json(
            {
                "status": "ok",
                "version": __version__,
                "uptime_s": int(time.monotonic() - self._started),
                "accounts": len(self.accounts.list_accounts()),
                "founders": self.accounts.founders(),
            }
        )

    def privacy(self) -> Response:
        body = (
            "<h2>what we store</h2>"
            "<p>Your email address, your username, a salted hash of your password if you set one, "
            "and the nodes you create: one SQLite file per node, in a directory only the service "
            "process can read. We keep no analytics and no tracking pixels.</p>"
            "<h2>who can read your entries</h2>"
            "<p>Everything between you and this server is encrypted in transit. On the server, "
            "the service reads your entries only to answer your own requests — search, threads, "
            "tags — and for nothing else: not analytics, not training, not curiosity. The "
            "honest part: a server that can search your entries can technically read them, and "
            "so can the person who runs it. We don't. If that is not good enough for what you "
            "are storing, run the same software yourself: it is open source and free, and a "
            "self-hosted node is unreadable to us because it never touches our disk.</p>"
            "<h2>leaving</h2>"
            "<p>Export any node at any time from the dashboard; the file is yours and opens in any "
            "SQLite tool. Keys can be revoked instantly. To close your account, write to "
            '<a href="mailto:hello@boonyard.com">hello@boonyard.com</a>.</p>'
        )
        return self._page("Privacy", body, nav="what we store, and who can see it")

    # -- the dashboard --------------------------------------------------------
    def _plan_line(self, account: Account) -> str:
        if account.plan == "founder":
            return (
                f'<span class="tag">founder #{account.founder_no}</span> free until '
                f"{_esc(_date(account.founder_until))} — thank you for being early."
            )
        if account.plan == "owner":
            return '<span class="tag">owner</span>'
        return f'<span class="tag">free</span> up to {FREE_NODE_CAP} nodes.'

    def _node_cap(self, account: Account) -> int | None:
        return FREE_NODE_CAP if account.plan == "free" else None

    def _keys_table(self, account: Account, node, csrf: str) -> str:
        user = self.registry.get_user(account.slug)
        keys = self.registry.list_keys(user, node)
        if not keys:
            return '<p class="muted">No keys yet.</p>'
        rows = []
        for k in keys:
            status = "revoked" if k.revoked_at else "active"
            action = ""
            if not k.revoked_at:
                action = (
                    f'<form method="post" action="{PREFIX}/keys/{_esc(k.key_id)}/revoke" '
                    f'class="inline"><input type="hidden" name="csrf" value="{_esc(csrf)}">'
                    '<button type="submit" class="danger">revoke</button></form>'
                )
            rows.append(
                f"<tr><td>{_esc(k.label or '-')}</td><td>{status}</td>"
                f"<td>{_esc(_date(k.created_at))}</td><td>{_esc(_date(k.last_used_at))}</td>"
                f"<td>{action}</td></tr>"
            )
        return (
            "<table><tr><th>label</th><th>status</th><th>created</th>"
            "<th>last used</th><th></th></tr>" + "".join(rows) + "</table>"
        )

    def _node_panel(self, account: Account, node, csrf: str) -> str:
        url = f"{self.mcp_base}/{account.slug}/{node.slug}"
        return (
            f'<div class="panel"><b><code>{_esc(node.slug)}</code></b> '
            f'<span class="muted">created {_esc(_date(node.created_at))}</span>'
            f'<p style="margin-top:.5rem">MCP URL: <code>{_esc(url)}</code><br>'
            '<span class="muted">In a connector dialog: that URL, transport Streamable HTTP, '
            "authentication none, and a request header "
            "<code>Authorization: Bearer &lt;key&gt;</code>."
            "</span></p>"
            f"{self._keys_table(account, node, csrf)}"
            f'<form method="post" action="{PREFIX}/nodes/{_esc(node.slug)}/keys">'
            f'<input type="hidden" name="csrf" value="{_esc(csrf)}">'
            "<label>new key label (which seat will hold it)</label>"
            f'<input type="text" name="label" maxlength="{MAX_LABEL}" '
            'placeholder="claude.ai connector">'
            '<button type="submit">Mint a key</button> '
            f'<a href="{PREFIX}/nodes/{_esc(node.slug)}/export">export this node (.zip)</a>'
            "</form></div>"
        )

    def _dashboard_body(
        self, account: Account, csrf: str, *, flash: str = "", error: str | None = None
    ) -> str:
        user = self.registry.get_user(account.slug)
        nodes = self.registry.list_nodes(user) if user else []
        cap = self._node_cap(account)
        at_cap = cap is not None and len(nodes) >= cap
        panels = "".join(self._node_panel(account, n, csrf) for n in nodes) or (
            '<p class="muted">No nodes yet. A node is one journal — one project\'s memory. '
            "Create one, mint a key, paste both into a connector.</p>"
        )
        create = (
            '<p class="muted">The free plan holds three nodes. Export one to make room, or wait '
            "for paid plans.</p>"
            if at_cap
            else f'<form method="post" action="{PREFIX}/nodes" class="panel">'
            f'<input type="hidden" name="csrf" value="{_esc(csrf)}">'
            '<label for="node">node name — lowercase letters, digits, hyphens</label>'
            '<input id="node" name="slug" type="text" required maxlength="40" '
            'pattern="[a-z0-9]([a-z0-9-]{0,38}[a-z0-9])?" placeholder="my-project">'
            '<button type="submit">Create node</button></form>'
        )
        password = (
            f"<form method=\"post\" action=\"{PREFIX}/password\" class=\"panel\">"
            f"<input type=\"hidden\" name=\"csrf\" value=\"{_esc(csrf)}\">"
            f"<label>{'change' if account.has_password else 'set a'} password (at least "
            f"{PASSWORD_MIN} characters) — optional; emailed links always work</label>"
            f'<input type="password" name="password" minlength="{PASSWORD_MIN}" '
            'maxlength="256" '
            "autocomplete=\"new-password\" required>"
            "<button type=\"submit\" class=\"quiet\">Save password</button></form>"
        )
        return (
            f"{'<p class=\"ok\">' + _esc(flash) + '</p>' if flash else ''}"
            f"{'<p class=\"err\">' + _esc(error) + '</p>' if error else ''}"
            f"<div class=\"panel\"><code>{_esc(account.slug)}</code> · {_esc(account.email)}<br>"
            f"{self._plan_line(account)}</div>"
            "<h2>nodes</h2>"
            + panels
            + create
            + "<h2>account</h2>"
            + password
            + f'<form method="post" action="{PREFIX}/logout">'
            f'<input type="hidden" name="csrf" value="{_esc(csrf)}">'
            '<button type="submit" class="quiet">Sign out</button></form>'
        )

    def dashboard(self, req: Request, *, error: str | None = None, status: int = 200) -> Response:
        found = self._require(req, csrf=False)
        if not isinstance(found, _Session):
            return found
        account, csrf = found
        flash = _FLASH.get(req.query.get("m", ""), "")
        return self._page(
            "Dashboard",
            self._dashboard_body(account, csrf, flash=flash, error=error),
            status=status,
            nav="your nodes and keys",
            private=True,
        )

    def create_node(self, req: Request) -> Response:
        found = self._require(req, csrf=True)
        if not isinstance(found, _Session):
            return found
        account, _csrf = found
        slug = req.form.get("slug", "").strip()
        user = self.registry.get_user(account.slug)
        cap = self._node_cap(account)
        if cap is not None and len(self.registry.list_nodes(user)) >= cap:
            return self.dashboard(req, error=f"The free plan holds {cap} nodes.", status=400)
        try:
            validate_slug(slug, kind="node name")
            provisioner.add_node(self.registry, account.slug, slug)
        except (SlugError, RegistryError) as exc:
            return self.dashboard(req, error=str(exc), status=400)
        return self._redirect(f"{PREFIX}/?m=node-created")

    def mint_key(self, req: Request, node_slug: str) -> Response:
        found = self._require(req, csrf=True)
        if not isinstance(found, _Session):
            return found
        account, csrf = found
        user = self.registry.get_user(account.slug)
        node = self.registry.get_node(user, node_slug) if user else None
        if node is None:
            return self._page("Not found", "<p>No such node.</p>", status=404, private=True)
        label = req.form.get("label", "").strip()[:MAX_LABEL] or None
        raw, _key = provisioner.add_key(self.registry, account.slug, node_slug, label=label)
        urls = provisioner.key_urls(self.mcp_base, account.slug, node_slug, raw)
        body = (
            f"<p class=\"ok\">New key for <code>{_esc(node_slug)}</code>"
            f"{' — ' + _esc(label) if label else ''}. Shown once; copy it now.</p>"
            f"<span class=\"key\">{_esc(raw)}</span>"
            "<h2>connect a seat</h2>"
            f"<div class=\"panel\"><p>URL: <code>{_esc(urls['header'])}</code></p>"
            "<p>Request header: <code>Authorization: Bearer &lt;the key above&gt;</code></p>"
            "<p class=\"muted\">In the Claude connector dialog: transport Streamable HTTP, "
            "authentication none, one request header as above. Clients without a header field "
            "can use the key as the last path segment instead: "
            f"<code>{_esc(urls['header'])}/&lt;key&gt;"
            "</code> — mind that intermediaries may log that form.</p></div>"
            f"<p><a href=\"{PREFIX}/\">Back to the dashboard</a></p>"
        )
        return self._page("Your new key", body, nav="copy it now — it is not stored", private=True)

    def _owns_key(self, account: Account, key_id: str):
        user = self.registry.get_user(account.slug)
        if user is None:
            return None
        for node in self.registry.list_nodes(user):
            for k in self.registry.list_keys(user, node):
                if k.key_id == key_id:
                    return k
        return None

    def revoke_key(self, req: Request, key_id: str) -> Response:
        found = self._require(req, csrf=True)
        if not isinstance(found, _Session):
            return found
        account, _csrf = found
        if self._owns_key(account, key_id) is None:
            return self._page("Not found", "<p>No such key.</p>", status=404, private=True)
        provisioner.revoke_key(self.registry, key_id)
        return self._redirect(f"{PREFIX}/?m=key-revoked")

    def export(self, req: Request, node_slug: str) -> Response:
        found = self._require(req, csrf=False)
        if not isinstance(found, _Session):
            return found
        account, _csrf = found
        user = self.registry.get_user(account.slug)
        if user is None or self.registry.get_node(user, node_slug) is None:
            return self._page("Not found", "<p>No such node.</p>", status=404, private=True)
        path = provisioner.export_node(self.registry, account.slug, node_slug)
        data = path.read_bytes()
        filename = f"boonyard-{account.slug}-{node_slug}-{path.stem.split('_', 1)[-1]}.zip"
        return (
            200,
            [
                ("Content-Type", "application/zip"),
                ("Content-Disposition", f'attachment; filename="{quote(filename)}"'),
                ("Cache-Control", "no-store"),
                *self._security_headers(),
            ],
            data,
        )

    def set_password(self, req: Request) -> Response:
        found = self._require(req, csrf=True)
        if not isinstance(found, _Session):
            return found
        account, _csrf = found
        try:
            self.accounts.set_password(account.account_id, req.form.get("password", ""))
        except AccountError as exc:
            return self.dashboard(req, error=str(exc), status=400)
        return self._redirect(f"{PREFIX}/?m=password-set")


# --------------------------------------------------------------------------
# HTTP transport
# --------------------------------------------------------------------------
def make_web_handler(app: WebApp):
    """A ``BaseHTTPRequestHandler`` bound to one app. Never logs the URL."""

    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # the URL may carry a one-time token — never log it
            pass

        def _client_ip(self) -> str:
            forwarded = self.headers.get("CF-Connecting-IP") or self.headers.get("X-Forwarded-For")
            if forwarded:
                return forwarded.split(",")[0].strip()[:64]
            return self.client_address[0]

        def _request(self, method: str) -> Request | None:
            full = self.path
            path, _, query = full.partition("?")
            if path == PREFIX:
                rel = "/"
            elif path.startswith(PREFIX + "/"):
                rel = path[len(PREFIX) :]
            else:
                return None
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                return Request(method, rel, {}, self.headers, b"", self._client_ip())
            body = self.rfile.read(length) if length else b""
            jar = http.cookies.SimpleCookie()
            try:
                jar.load(self.headers.get("Cookie") or "")
            except http.cookies.CookieError:
                jar = http.cookies.SimpleCookie()
            cookies = {k: m.value for k, m in jar.items()}
            return Request(
                method,
                rel,
                _first(parse_qs(query, keep_blank_values=True)),
                self.headers,
                body,
                self._client_ip(),
                cookies,
            )

        def _send(self, status: int, headers: list[tuple[str, str]], body: bytes) -> None:
            self.send_response(status)
            has_len = False
            for name, value in headers:
                self.send_header(name, value)
                has_len = has_len or name.lower() == "content-length"
            if not has_len:
                self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if body:
                self.wfile.write(body)

        def _serve(self, method: str) -> None:
            req = self._request(method)
            if req is None:
                self._send(404, [("Content-Type", "text/plain")], b"not found\n")
                return
            if req.method == "POST" and int(self.headers.get("Content-Length") or 0) > MAX_BODY:
                self._send(413, [("Content-Type", "text/plain")], b"too large\n")
                return
            try:
                status, headers, body = app.handle(req)
            except Exception as exc:  # noqa: BLE001 — type name only; no path, no token
                print(f"boonyardnn: internal error: {type(exc).__name__}", file=sys.stderr)
                status, headers, body = app._page(
                    "Something went wrong", "<p>Internal error. Nothing was lost.</p>", status=500
                )
            self._send(status, headers, body)

        def do_GET(self):
            self._serve("GET")

        def do_POST(self):
            self._serve("POST")

    return _Handler


def make_web_httpd(app: WebApp, host: str = DEFAULT_HOST, port: int = DEFAULT_WEB_PORT):
    """Build (but don't start) the threaded server. Port 0 = ephemeral (tests)."""
    return ThreadingHTTPServer((host, port), make_web_handler(app))


def serve_web(app: WebApp, *, host: str = DEFAULT_HOST, port: int = DEFAULT_WEB_PORT) -> None:
    """Run the web app forever on ``host:port`` (blocks). Ctrl-C to stop."""
    httpd = make_web_httpd(app, host, port)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.shutdown()
    finally:
        httpd.server_close()
