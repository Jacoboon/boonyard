"""The node browser — arch 07's "single-node view", as forms over the tools the router serves.

Mounted under the web app at ``/app/nodes/{slug}``. Every read is one of the package's
own MCP tools called in-process (``adapter.call_tool`` → ``MCPServer.handle()``), so what
the browser shows is byte-for-byte what a connected seat would see. Writes:

* ``POST …/entries`` — ``log_entry`` as the human seat (the one thing a person without a
  connector could not do until now).
* ``POST …/entries/{id}/retag`` — the audited tags-only mutation (ADR-0005), with a reason.
* ``POST …/delete`` — tombstone the NODE (arch 05's grace shape): the directory moves
  aside, its keys are revoked, nothing is destroyed. Typed confirmation required.

What is deliberately absent: editing an entry, deleting an entry. "Edit" is a new entry
threaded to the old one — the reply form on every entry page does exactly that.

Routes (relative to ``/app/nodes/{slug}``):

    GET  /                 the node: info, write form, search, recent entries, tags
    GET  /entries/{id}     one entry + the thread below it + reply and retag forms
    POST /entries          write an entry
    POST /entries/{id}/retag
    GET  /search?q=… | ?tag=…
    POST /delete           tombstone (form field ``confirm`` must equal the slug)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from . import adapter, provisioner
from .accounts import Account
from .adapter import ToolError
from .registry import RegistryError, SlugError, validate_slug
from .web import PREFIX, Request, Response, _date, _esc

if TYPE_CHECKING:
    from .web import WebApp

RECENT_LIMIT = 30
SEARCH_LIMIT = 50
MAX_CONTENT = 64 * 1024
MAX_TAGS = 512
MAX_REASON = 256
DEFAULT_AGENT = "human"
_HINT = '<p class="muted">Type something.</p>'


# --------------------------------------------------------------------------
# entry rendering
# --------------------------------------------------------------------------
def _tags_html(slug: str, tags) -> str:
    if not tags:
        return ""
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    return " ".join(
        f'<a class="tag" href="{PREFIX}/nodes/{_esc(slug)}/search?tag={_esc(t)}">{_esc(t)}</a>'
        for t in tags
    )


def _entry_html(slug: str, e: dict, *, full: bool = False) -> str:
    base = f"{PREFIX}/nodes/{_esc(slug)}"
    eid = e.get("id")
    content = str(e.get("content") or "")
    if not full and len(content) > 600:
        content = content[:600].rstrip() + " …"
    parent = e.get("related_id")
    parent_html = (
        f' · <a href="{base}/entries/{_esc(parent)}">↳ #{_esc(parent)}</a>' if parent else ""
    )
    return (
        '<div class="panel">'
        f'<a href="{base}/entries/{_esc(eid)}"><code>#{_esc(eid)}</code></a> '
        f'<span class="muted">{_esc(e.get("timestamp", ""))}</span> · '
        f"<b>{_esc(e.get('agent', ''))}</b> · {_esc(e.get('entry_type', ''))}{parent_html}"
        f'<pre style="white-space:pre-wrap;font:inherit;margin:.5rem 0">{_esc(content)}</pre>'
        f'<div>{_tags_html(slug, e.get("tags"))}</div></div>'
    )


def _entries_html(slug: str, entries) -> str:
    if not entries:
        return '<p class="muted">Nothing here yet.</p>'
    return "".join(_entry_html(slug, e) for e in entries)


def _write_form(
    slug: str, csrf: str, entry_types: list[str], *, related_id: int | None = None
) -> str:
    base = f"{PREFIX}/nodes/{_esc(slug)}"
    options = "".join(
        f'<option value="{_esc(t)}"{" selected" if t == "note" else ""}>{_esc(t)}</option>'
        for t in entry_types
    )
    related = (
        f'<input type="hidden" name="related_id" value="{_esc(related_id)}">'
        f'<p class="muted">Reply — threaded to #{_esc(related_id)}. This is how an entry is '
        '"edited": the old one stays, the new one says what changed.</p>'
        if related_id
        else '<label for="related_id">related_id — optional, threads this under an entry</label>'
        '<input id="related_id" name="related_id" type="text" inputmode="numeric" pattern="[0-9]*">'
    )
    return (
        f'<form method="post" action="{base}/entries" class="panel">'
        f'<input type="hidden" name="csrf" value="{_esc(csrf)}">'
        f"{related}"
        '<label for="agent">agent — who is writing (your seat name)</label>'
        f'<input id="agent" name="agent" type="text" maxlength="40" value="{DEFAULT_AGENT}" '
        "required>"
        '<label for="entry_type">entry type</label>'
        f'<select id="entry_type" name="entry_type" style="font:inherit;padding:.4rem">{options}'
        '<option value="__other">other…</option></select>'
        '<input name="entry_type_other" type="text" maxlength="40" '
        'placeholder="type name if other">'
        '<label for="content">content</label>'
        f'<textarea id="content" name="content" rows="6" required maxlength="{MAX_CONTENT}" '
        'style="width:100%;font:inherit;padding:.5rem;background:var(--bg);color:var(--text);'
        'border:1px solid var(--border);border-radius:4px"></textarea>'
        '<label for="tags">tags — comma separated, lowercase-hyphen</label>'
        f'<input id="tags" name="tags" type="text" maxlength="{MAX_TAGS}" '
        'placeholder="decision, project-x">'
        '<button type="submit">Write entry</button></form>'
    )


# --------------------------------------------------------------------------
# the browser
# --------------------------------------------------------------------------
class NodeBrowser:
    """One node, one signed-in account; every method returns a web ``Response``."""

    def __init__(self, app: WebApp, account: Account, csrf: str, node):
        self.app = app
        self.account = account
        self.csrf = csrf
        self.node = node
        self.slug = node.slug
        self.base = f"{PREFIX}/nodes/{self.slug}"
        user = app.registry.get_user(account.slug)
        self.node_dir = app.registry.node_dir(user, node)
        self.db_path = self.node_dir / "journal.db"
        self.server = adapter.make_server(
            self.db_path,
            profile_path=self.node_dir / "boonyard.toml",
            meter_path=self.node_dir / "meter.db",
        )

    def call(self, name: str, **args):
        return adapter.call_tool(self.server, name, **args)

    def _entry_types(self) -> list[str]:
        try:
            info = self.call("node_info")
            types = list((info.get("profile") or {}).get("allowed_entry_types") or [])
        except ToolError:
            types = []
        return types or ["note", "decision", "discussion", "implementation", "error"]

    def _page(self, title: str, body: str, *, status: int = 200, nav: str = "") -> Response:
        crumbs = (
            f'<a href="{PREFIX}/">dashboard</a> › <a href="{self.base}">{_esc(self.slug)}</a>'
            f"{' › ' + nav if nav else ''}"
        )
        return self.app._page(title, body, status=status, nav=crumbs, private=True)

    def _search_form(self, q: str = "", tag: str = "") -> str:
        return (
            f'<form method="get" action="{self.base}/search" class="panel" style="display:flex;'
            'gap:.5rem;align-items:end;flex-wrap:wrap">'
            '<div style="flex:2"><label for="q">search text</label>'
            f'<input id="q" name="q" type="text" maxlength="200" value="{_esc(q)}"></div>'
            '<div style="flex:1"><label for="tag">or by tag</label>'
            f'<input id="tag" name="tag" type="text" maxlength="80" value="{_esc(tag)}"></div>'
            '<button type="submit">Search</button></form>'
        )

    # -- pages ------------------------------------------------------------------
    def node_page(self, req: Request, *, error: str | None = None, status: int = 200) -> Response:
        try:
            info = self.call("node_info")
            recent = self.call("recent", limit=RECENT_LIMIT)
        except ToolError as exc:
            return self._page("Node", f'<p class="err">{_esc(exc)}</p>', status=500)
        try:
            tags = self.call("list_tags")
        except ToolError:
            tags = []
        tag_names = [t.get("tag") if isinstance(t, dict) else str(t) for t in (tags or [])][:60]
        flash = self.app._flash_text(req)
        mcp_url = f"{self.app.mcp_base}/{self.account.slug}/{self.slug}"
        body = (
            f"{'<p class=\"ok\">' + _esc(flash) + '</p>' if flash else ''}"
            f"{'<p class=\"err\">' + _esc(error) + '</p>' if error else ''}"
            f'<div class="panel"><b><code>{_esc(self.slug)}</code></b> · '
            f"{_esc(info.get('entry_count', 0))} entries · "
            f"born {_esc(_date(info.get('created_at')))}"
            f" · last write {_esc(info.get('last_write_at') or '-')}<br>"
            f'<span class="muted">MCP URL <code>{_esc(mcp_url)}</code> · '
            f'<a href="{self.base}/export">export (.zip)</a></span></div>'
            "<h2>write</h2>"
            f"{_write_form(self.slug, self.csrf, self._entry_types())}"
            "<h2>find</h2>"
            f"{self._search_form()}"
            f"{('<p>' + _tags_html(self.slug, tag_names) + '</p>') if tag_names else ''}"
            f"<h2>recent</h2>{_entries_html(self.slug, recent)}"
            "<h2>danger</h2>"
            f'<form method="post" action="{self.base}/delete" class="panel">'
            f'<input type="hidden" name="csrf" value="{_esc(self.csrf)}">'
            "<p class=\"muted\">Tombstone this node: its directory moves aside and every key "
            "scoped to it is revoked. Nothing is destroyed, and no entry can ever be deleted "
            "one at a time. Type the node name to confirm.</p>"
            f'<input name="confirm" type="text" placeholder="{_esc(self.slug)}" autocomplete="off">'
            '<button type="submit" class="danger" style="margin-left:.5rem">Tombstone node</button>'
            "</form>"
        )
        return self._page(self.slug, body, status=status)

    def entry_page(self, req: Request, entry_id: int) -> Response:
        try:
            entry = self.call("by_id", entry_id=entry_id)
        except ToolError as exc:
            return self._page("Not found", f'<p class="err">{_esc(exc)}</p>', status=404)
        if not entry:
            return self._page("Not found", "<p>No such entry.</p>", status=404)
        try:
            thread = self.call("get_thread", root_id=entry_id)
        except ToolError:
            thread = []
        below = [e for e in (thread or []) if e.get("id") != entry_id]
        flash = self.app._flash_text(req)
        current_tags = entry.get("tags") or []
        if isinstance(current_tags, list):
            current_tags = ", ".join(current_tags)
        body = (
            f"{'<p class=\"ok\">' + _esc(flash) + '</p>' if flash else ''}"
            f"{_entry_html(self.slug, entry, full=True)}"
            "<h2>reply</h2>"
            f"{_write_form(self.slug, self.csrf, self._entry_types(), related_id=entry_id)}"
            "<h2>retag</h2>"
            f'<form method="post" action="{self.base}/entries/{entry_id}/retag" class="panel">'
            f'<input type="hidden" name="csrf" value="{_esc(self.csrf)}">'
            '<label for="tags">new tags — replaces the whole set; logged to meta_log '
            "with your reason</label>"
            f'<input id="tags" name="tags" type="text" maxlength="{MAX_TAGS}" '
            f'value="{_esc(current_tags)}">'
            '<label for="reason">reason</label>'
            f'<input id="reason" name="reason" type="text" maxlength="{MAX_REASON}" required>'
            '<button type="submit" class="quiet">Replace tags</button></form>'
            f"<h2>thread below #{entry_id}</h2>{_entries_html(self.slug, below)}"
        )
        return self._page(f"#{entry_id}", body, nav=f"#{entry_id}")

    def search_page(self, req: Request) -> Response:
        q = req.query.get("q", "").strip()[:200]
        tag = req.query.get("tag", "").strip()[:80]
        results = []
        error = None
        try:
            if q:
                results = self.call("search_text", query=q, limit=SEARCH_LIMIT)
            elif tag:
                results = self.call("search_by_tag", tag=tag, limit=SEARCH_LIMIT)
        except ToolError as exc:
            error = str(exc)
        label = f'"{q}"' if q else (f"tag {tag}" if tag else "")
        body = (
            f"{self._search_form(q, tag)}"
            f"{'<p class=\"err\">' + _esc(error) + '</p>' if error else ''}"
            f"<h2>{_esc(label) or 'results'}</h2>"
            f"{_entries_html(self.slug, results) if (q or tag) else _HINT}"
        )
        return self._page("Search", body, nav="search")

    # -- writes -----------------------------------------------------------------
    def write_entry(self, req: Request) -> Response:
        form = req.form
        agent = form.get("agent", "").strip()[:40] or DEFAULT_AGENT
        entry_type = form.get("entry_type", "").strip()[:40]
        if entry_type == "__other":
            entry_type = form.get("entry_type_other", "").strip()[:40]
        content = form.get("content", "")
        tags = form.get("tags", "").strip()[:MAX_TAGS]
        related = form.get("related_id", "").strip()
        related_id = int(related) if related.isdigit() else None
        if not content.strip():
            return self.node_page(req, error="Content is empty.", status=400)
        if len(content) > MAX_CONTENT:
            return self.node_page(
                req, error="Content is too long for the browser form.", status=400
            )
        try:
            payload = self.call(
                "log_entry",
                agent=agent,
                entry_type=entry_type or "note",
                content=content,
                related_id=related_id,
                tags=[t.strip() for t in tags.split(",") if t.strip()] or None,
            )
        except ToolError as exc:
            return self.node_page(req, error=str(exc), status=400)
        new_id = payload.get("id") if isinstance(payload, dict) else None
        if new_id is None:
            return self.app._redirect(f"{self.base}?m=entry-written")
        return self.app._redirect(f"{self.base}/entries/{new_id}?m=entry-written")

    def retag(self, req: Request, entry_id: int) -> Response:
        form = req.form
        tags = form.get("tags", "").strip()[:MAX_TAGS]
        reason = form.get("reason", "").strip()[:MAX_REASON]
        if not reason:
            return self._page("Refused", '<p class="err">A retag needs a reason.</p>', status=400)
        try:
            adapter.retag(self.db_path, entry_id, tags or None, reason, self.account.slug)
        except (ValueError, LookupError, RuntimeError) as exc:
            return self._page("Refused", f'<p class="err">{_esc(exc)}</p>', status=400)
        return self.app._redirect(f"{self.base}/entries/{entry_id}?m=retagged")

    def delete_node(self, req: Request) -> Response:
        if req.form.get("confirm", "").strip() != self.slug:
            return self.node_page(
                req, error="Type the node name exactly to tombstone it.", status=400
            )
        try:
            provisioner.remove_node(self.app.registry, self.account.slug, self.slug)
        except RegistryError as exc:
            return self.node_page(req, error=str(exc), status=400)
        return self.app._redirect(f"{PREFIX}/?m=node-removed")


# --------------------------------------------------------------------------
# dispatch (called from WebApp.handle for /nodes/{slug}[/…])
# --------------------------------------------------------------------------
def dispatch(app: WebApp, req: Request, slug: str, rest: list[str]) -> Response:
    """Route ``/nodes/{slug}[/entries[/{id}[/retag]] | /search | /delete]``."""
    needs_csrf = req.method == "POST"
    found = app._require(req, csrf=needs_csrf)
    if not hasattr(found, "account"):
        return found
    account, csrf = found.account, found.csrf
    try:
        validate_slug(slug, kind="node slug")
    except SlugError:
        return app._page("Not found", "<p>No such node.</p>", status=404, private=True)
    user = app.registry.get_user(account.slug)
    node = app.registry.get_node(user, slug) if user else None
    if node is None:
        return app._page("Not found", "<p>No such node.</p>", status=404, private=True)
    browser = NodeBrowser(app, account, csrf, node)
    get, post = req.method == "GET", req.method == "POST"
    if not rest:
        return browser.node_page(req) if get else app._method_not_allowed("GET")
    head = rest[0]
    if head == "search" and len(rest) == 1 and get:
        return browser.search_page(req)
    if head == "delete" and len(rest) == 1 and post:
        return browser.delete_node(req)
    if head == "entries":
        if len(rest) == 1:
            return browser.write_entry(req) if post else app._method_not_allowed("POST")
        if not rest[1].isdigit():
            return app._page("Not found", "<p>No such entry.</p>", status=404, private=True)
        entry_id = int(rest[1])
        if len(rest) == 2 and get:
            return browser.entry_page(req, entry_id)
        if len(rest) == 3 and rest[2] == "retag" and post:
            return browser.retag(req, entry_id)
    return app._page("Not found", "<p>Nothing here.</p>", status=404, private=True)
