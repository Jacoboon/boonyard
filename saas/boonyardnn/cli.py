"""``boonyardnn`` — provisioning by hand, ``serve`` for the router, ``serve-web`` for the app.

    python -m boonyardnn [--root DIR] user add <slug> --email <e>
                                     user list
                                     node add <user> <node> [--profile TOML]
                                     node list <user>
                                     key add <user> <node> [--label L]
                                     key add-account <user> [--label L]
                                     key revoke <key_id>
                                     key list <user> [<node>]
                                     export <user> <node>
                                     serve [--host H] [--port P]
                                     serve-web [--host H] [--port P]
                                     account list
                                     account founders
                                     account import <slug> --email <e> [--plan owner]
                                     account link <email>
                                     mail test <to>

The data root is ``--root`` or ``$BOONYARDNN_DATA_ROOT`` — never a silent default,
because these commands create 0700 directories. ``$BOONYARDNN_PUBLIC_BASE`` is the
router's public URL (what ``key add`` prints and what the dashboard shows);
``$BOONYARDNN_WEB_BASE`` is the app's (the links in mail). Mail: ``$BOONYARDNN_MAIL``
= ``agentmail`` | ``log`` | ``none`` (see ``mailer.py``).

Exit codes mirror the package: 0 ok; 1 not found; 2 usage / validation. All
human-facing output lives here; the library modules never print. The raw key is
printed by ``key add`` exactly once and by nothing else; ``account link`` prints a
one-time sign-in link, once, for the hour the mailer is down.
"""

import argparse
import os
import sys
from pathlib import Path

from . import __version__, adapter, provisioner
from .accounts import DEFAULT_FOUNDER_SEATS, AccountError, Accounts
from .mailer import MailError, mailer_from_env
from .registry import NotFoundError, Registry, RegistryError
from .router import DEFAULT_HOST, DEFAULT_PORT, serve
from .web import DEFAULT_WEB_PORT, PREFIX, WebApp, serve_web

EXIT_OK = 0
EXIT_NOT_FOUND = 1
EXIT_USAGE = 2

ENV_ROOT = "BOONYARDNN_DATA_ROOT"
ENV_PUBLIC_BASE = "BOONYARDNN_PUBLIC_BASE"
ENV_WEB_BASE = "BOONYARDNN_WEB_BASE"
ENV_FOUNDER_SEATS = "BOONYARDNN_FOUNDER_SEATS"
DEFAULT_PUBLIC_BASE = "http://127.0.0.1:8800"
DEFAULT_WEB_BASE = "http://127.0.0.1:8801"


class _Usage(Exception):
    """A usage error the parser could not catch (e.g. no data root)."""


def _registry(args) -> Registry:
    root = args.root or os.environ.get(ENV_ROOT)
    if not root:
        raise _Usage(f"no data root: pass --root DIR or set {ENV_ROOT}")
    return Registry(Path(root))


def _accounts(args) -> Accounts:
    seats = os.environ.get(ENV_FOUNDER_SEATS)
    return Accounts(
        _registry(args).root, founder_seats=int(seats) if seats else DEFAULT_FOUNDER_SEATS
    )


def _public_base() -> str:
    return os.environ.get(ENV_PUBLIC_BASE) or DEFAULT_PUBLIC_BASE


def _web_base() -> str:
    return os.environ.get(ENV_WEB_BASE) or DEFAULT_WEB_BASE


def _table(rows: list[list[str]], header: list[str]) -> None:
    widths = [max(len(str(r[i])) for r in [header, *rows]) for i in range(len(header))]
    for row in [header, *rows]:
        print("  ".join(str(cell).ljust(widths[i]) for i, cell in enumerate(row)).rstrip())


# --------------------------------------------------------------------------
# user
# --------------------------------------------------------------------------
def cmd_user(args) -> int:
    reg = _registry(args)
    if args.user_cmd == "add":
        user = provisioner.add_user(reg, args.slug, args.email)
        print(f"created user {user.slug} ({user.user_id})")
        print(f"  dir: {reg.user_dir(user).relative_to(reg.root).as_posix()}")
        return EXIT_OK
    if args.user_cmd == "list":
        users = reg.list_users()
        if not users:
            print("(no users)")
            return EXIT_OK
        _table(
            [[u.slug, u.user_id, u.plan, u.status, u.created_at, u.email] for u in users],
            ["slug", "user_id", "plan", "status", "created_at", "email"],
        )
        return EXIT_OK
    if args.user_cmd == "plan":
        user = provisioner.set_plan(reg, args.slug, args.plan)
        print(f"{user.slug}: plan {user.plan}")
        return EXIT_OK
    return EXIT_USAGE


# --------------------------------------------------------------------------
# node
# --------------------------------------------------------------------------
def cmd_node(args) -> int:
    reg = _registry(args)
    if args.node_cmd == "add":
        node = provisioner.add_node(reg, args.user, args.node, profile_path=args.profile)
        print(f"created node {args.user}/{node.slug} ({node.node_id})")
        print(f"  dir: {node.storage_path}")
        return EXIT_OK
    if args.node_cmd == "list":
        user = provisioner._require_user(reg, args.user)
        nodes = reg.list_nodes(user)
        if not nodes:
            print("(no nodes)")
            return EXIT_OK
        _table(
            [[n.slug, n.node_id, n.created_at, n.storage_path] for n in nodes],
            ["slug", "node_id", "created_at", "storage_path"],
        )
        return EXIT_OK
    if args.node_cmd == "remove":
        grave = provisioner.remove_node(reg, args.user, args.node)
        print(f"tombstoned {args.user}/{args.node} -> {grave.relative_to(reg.root).as_posix()}")
        print("  keys scoped to it are revoked; nothing was destroyed (purge is a separate act)")
        return EXIT_OK
    return EXIT_USAGE


# --------------------------------------------------------------------------
# key
# --------------------------------------------------------------------------
def cmd_key(args) -> int:
    reg = _registry(args)
    if args.key_cmd == "add":
        raw, key = provisioner.add_key(reg, args.user, args.node, label=args.label)
        urls = provisioner.key_urls(_public_base(), args.user, args.node, raw)
        print(f"key_id:  {key.key_id}")
        print(f"label:   {key.label or '-'}")
        print(f"scope:   {key.scope}")
        print(f"node:    {args.user}/{args.node}")
        print()
        print(f"  {raw}")
        print()
        print("Shown ONCE. Store it now: only its sha256 is kept, and it cannot be recovered.")
        print()
        print(f"header form:     POST {urls['header']}")
        print(f"                 Authorization: Bearer {raw}")
        print(f"capability URL:  {urls['capability']}")
        return EXIT_OK
    if args.key_cmd == "add-account":
        raw, key = provisioner.add_account_key(reg, args.user, label=args.label)
        print(f"key_id:  {key.key_id}")
        print(f"label:   {key.label or '-'}")
        print(f"scope:   {key.scope}")
        print(f"account: {args.user} — EVERY node, present and future")
        print()
        print(f"  {raw}")
        print()
        print("Shown ONCE. Store it now: only its sha256 is kept, and it cannot be recovered.")
        print("Revoking this key cuts access to every node at once (ADR-0014 §8).")
        print()
        print(f"URL:             POST {provisioner.account_key_url(_public_base(), args.user)}")
        print(f"                 Authorization: Bearer {raw}")
        print("                 (header auth only at this door — no capability URL form)")
        print("Writes must name their node: log_entry(..., node='<slug>'); see list_nodes.")
        return EXIT_OK
    if args.key_cmd == "revoke":
        key = provisioner.revoke_key(reg, args.key_id)
        print(f"revoked key {key.key_id} (revoked_at {key.revoked_at})")
        return EXIT_OK
    if args.key_cmd == "list":
        user = provisioner._require_user(reg, args.user)
        if args.node is None:
            keys = reg.list_account_keys(user)
        else:
            node = provisioner._require_node(reg, user, args.node)
            keys = reg.list_keys(user, node)
        if not keys:
            print("(no keys)")
            return EXIT_OK
        _table(
            [
                [
                    k.key_id,
                    "revoked" if k.revoked_at else "active",
                    k.label or "-",
                    k.created_at,
                    k.last_used_at or "-",
                    k.revoked_at or "-",
                ]
                for k in keys
            ],
            ["key_id", "status", "label", "created_at", "last_used_at", "revoked_at"],
        )
        return EXIT_OK
    return EXIT_USAGE


# --------------------------------------------------------------------------
# export / serve / serve-web
# --------------------------------------------------------------------------
def cmd_export(args) -> int:
    reg = _registry(args)
    dest = provisioner.export_node(reg, args.user, args.node)
    print(f"exported {args.user}/{args.node} -> {dest.relative_to(reg.root).as_posix()}")
    return EXIT_OK


def cmd_serve(args) -> int:
    reg = _registry(args)
    counts = reg.counts()
    print(
        f"serving boonyardnn {__version__} (boonyard {adapter.package_version()}) "
        f"on {args.host}:{args.port} -- root {reg.root}, "
        f"{counts['users']} users, {counts['nodes']} nodes",
        flush=True,  # stdout is a pipe under systemd; the banner must not wait for exit
    )
    serve(reg, host=args.host, port=args.port)
    return EXIT_OK


def cmd_serve_web(args) -> int:
    reg = _registry(args)
    acc = _accounts(args)
    mailer = mailer_from_env()
    app = WebApp(reg, acc, mailer, web_base=_web_base(), mcp_base=_public_base())
    founders = acc.founders()
    print(
        f"serving boonyardnn web {__version__} on {args.host}:{args.port}{PREFIX} -- "
        f"root {reg.root}, mail {type(mailer).__name__}, "
        f"founders {founders['taken']}/{founders['seats']}, "
        f"links {app.web_base}{PREFIX}, mcp {app.mcp_base}",
        flush=True,
    )
    serve_web(app, host=args.host, port=args.port)
    return EXIT_OK


# --------------------------------------------------------------------------
# account / mail
# --------------------------------------------------------------------------
def cmd_account(args) -> int:
    acc = _accounts(args)
    if args.account_cmd == "list":
        rows = acc.list_accounts()
        if not rows:
            print("(no accounts)")
            return EXIT_OK
        _table(
            [
                [
                    a.slug,
                    a.plan + (f" #{a.founder_no}" if a.founder_no else ""),
                    "verified" if a.verified else "unverified",
                    "pw" if a.has_password else "-",
                    a.created_at,
                    a.last_login_at or "-",
                    a.email,
                ]
                for a in rows
            ],
            ["slug", "plan", "status", "password", "created_at", "last_login_at", "email"],
        )
        return EXIT_OK
    if args.account_cmd == "founders":
        f = acc.founders()
        print(f"founders: {f['taken']} of {f['seats']} seats taken, {f['open']} open")
        return EXIT_OK
    if args.account_cmd == "import":
        reg = _registry(args)
        if reg.get_user(args.slug) is None:
            raise NotFoundError(f"no registry user {args.slug!r} — import is for provisioned users")
        account = acc.import_user(args.slug, args.email, plan=args.plan)
        provisioner.set_plan(reg, args.slug, account.plan)
        print(f"imported {account.slug} as {account.plan} ({account.account_id})")
        return EXIT_OK
    if args.account_cmd == "link":
        found = acc.issue_link_token(args.email)
        if found is None:
            raise NotFoundError(f"no account for {args.email!r}")
        account, kind, token = found
        path = "/verify" if kind == "verify" else "/login/link"
        print(f"{kind} link for {account.slug} (one use; shown once):")
        print(f"  {_web_base()}{PREFIX}{path}?t={token}")
        return EXIT_OK
    return EXIT_USAGE


def cmd_backup_config(args) -> int:
    reg = _registry(args)
    text = provisioner.backup_config(reg, args.base, heartbeat_node=args.heartbeat_node)
    if args.out:
        out = Path(args.out)
        tmp = out.with_name(out.name + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, out)
        # Count rows in [nodes] only: [backup] carries a `key = 'value'` line too, and
        # counting it would report one node more than the file actually registers.
        body = text.split("[nodes]", 1)[-1].split("[backup]", 1)[0]
        rows = sum(1 for line in body.splitlines() if " = '" in line)
        beat = f", heartbeat -> {args.heartbeat_node}" if args.heartbeat_node else ""
        print(f"wrote {out} ({rows} nodes{beat})")
    else:
        print(text, end="")
    return EXIT_OK


def cmd_mail(args) -> int:
    if args.mail_cmd == "test":
        mailer = mailer_from_env()
        try:
            mailer.send(args.to, "Boonyard mail test", "If you can read this, the sender works.\n")
        except MailError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return EXIT_USAGE
        print(f"sent a test mail to {args.to} via {type(mailer).__name__}")
        return EXIT_OK
    return EXIT_USAGE


# --------------------------------------------------------------------------
# Parser
# --------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="boonyardnn", description="Hosted-layer provisioning, the path router and the web app."
    )
    parser.add_argument("--version", action="version", version=f"boonyardnn {__version__}")
    parser.add_argument("--root", help=f"data root (default: ${ENV_ROOT})")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("user", help="user add <slug> --email E | user list")
    us = p.add_subparsers(dest="user_cmd", required=True)
    a = us.add_parser("add", help="create a user directory (ADR-0007)")
    a.add_argument("slug")
    a.add_argument("--email", required=True)
    us.add_parser("list", help="every user")
    pl = us.add_parser("plan", help="mirror the account's plan into the registry (router tier)")
    pl.add_argument("slug")
    pl.add_argument("plan")
    p.set_defaults(func=cmd_user)

    p = sub.add_parser("node", help="node add <user> <node> [--profile TOML] | node list <user>")
    ns = p.add_subparsers(dest="node_cmd", required=True)
    a = ns.add_parser("add", help="create and initialise a node under a user")
    a.add_argument("user")
    a.add_argument("node")
    a.add_argument("--profile", help="a boonyard.toml to copy in (default: the starter profile)")
    ls = ns.add_parser("list", help="a user's nodes")
    ls.add_argument("user")
    rm = ns.add_parser("remove", help="tombstone a node (moved aside, keys revoked; no purge)")
    rm.add_argument("user")
    rm.add_argument("node")
    p.set_defaults(func=cmd_node)

    p = sub.add_parser("key", help="key add <user> <node> [--label L] | key revoke <id> | key list")
    ks = p.add_subparsers(dest="key_cmd", required=True)
    a = ks.add_parser("add", help="mint a per-node key; prints it ONCE (ADR-0008)")
    a.add_argument("user")
    a.add_argument("node")
    a.add_argument("--label")
    aa = ks.add_parser(
        "add-account", help="mint an ACCOUNT key — every node, one connector (ADR-0014)"
    )
    aa.add_argument("user")
    aa.add_argument("--label")
    r = ks.add_parser("revoke", help="revoke a key by id (row kept for audit)")
    r.add_argument("key_id")
    ls = ks.add_parser("list", help="a node's keys, or the account's when no node is named")
    ls.add_argument("user")
    ls.add_argument("node", nargs="?")
    p.set_defaults(func=cmd_key)

    p = sub.add_parser("export", help="export bundle into the user's exports/ (no lock-in)")
    p.add_argument("user")
    p.add_argument("node")
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("serve", help="run the router (stdlib http.server)")
    p.add_argument("--host", default=DEFAULT_HOST)
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("serve-web", help="run the signup/dashboard app (stdlib http.server)")
    p.add_argument("--host", default=DEFAULT_HOST)
    p.add_argument("--port", type=int, default=DEFAULT_WEB_PORT)
    p.set_defaults(func=cmd_serve_web)

    p = sub.add_parser(
        "account", help="account list | founders | import <slug> --email E | link <email>"
    )
    acs = p.add_subparsers(dest="account_cmd", required=True)
    acs.add_parser("list", help="every account: plan, verification, password set or not")
    acs.add_parser("founders", help="the founders counter")
    imp = acs.add_parser("import", help="register a provisioned registry user as an account")
    imp.add_argument("slug")
    imp.add_argument("--email", required=True)
    imp.add_argument("--plan", default="owner", choices=["owner", "free", "founder"])
    ln = acs.add_parser("link", help="print a one-time sign-in/verify link (mailer down)")
    ln.add_argument("email")
    p.set_defaults(func=cmd_account)

    p = sub.add_parser(
        "backup-config", help="emit the [nodes] table for backup_walls.py: base file + hosted nodes"
    )
    p.add_argument("--base", help="a TOML whose [nodes] rows are copied first (the six walls)")
    p.add_argument("--out", help="write here (atomic) instead of stdout")
    p.add_argument(
        "--heartbeat-node",
        help="emit [backup] heartbeat_node — the [nodes] key the nightly's heartbeat lands "
        "on. This generated file is the only config the nightly reads, so the setting has "
        "to be here. Refused if it is not one of the nodes emitted.",
    )
    p.set_defaults(func=cmd_backup_config)

    p = sub.add_parser(
        "mail", help="mail test <to> — send one message through the configured sender"
    )
    ms = p.add_subparsers(dest="mail_cmd", required=True)
    t = ms.add_parser("test", help="send a test message")
    t.add_argument("to")
    p.set_defaults(func=cmd_mail)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point for ``boonyardnn`` / ``python -m boonyardnn``. Returns an exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except NotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_NOT_FOUND
    except (_Usage, RegistryError, AccountError, MailError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
