"""``boonyardnn`` — provisioning by hand, and ``serve`` for the router.

    python -m boonyardnn [--root DIR] user add <slug> --email <e>
                                     user list
                                     node add <user> <node> [--profile TOML]
                                     node list <user>
                                     key add <user> <node> [--label L]
                                     key revoke <key_id>
                                     key list <user> <node>
                                     export <user> <node>
                                     serve [--host H] [--port P]

The data root is ``--root`` or ``$BOONYARDNN_DATA_ROOT`` — never a silent default,
because these commands create 0700 directories. ``$BOONYARDNN_PUBLIC_BASE`` affects
only what ``key add`` prints (default ``http://127.0.0.1:8800``).

Exit codes mirror the package: 0 ok; 1 not found; 2 usage / validation. All
human-facing output lives here; the library modules never print. The raw key is
printed by ``key add`` exactly once and by nothing else.
"""

import argparse
import os
import sys
from pathlib import Path

from . import __version__, adapter, provisioner
from .registry import NotFoundError, Registry, RegistryError
from .router import DEFAULT_HOST, DEFAULT_PORT, serve

EXIT_OK = 0
EXIT_NOT_FOUND = 1
EXIT_USAGE = 2

ENV_ROOT = "BOONYARDNN_DATA_ROOT"
ENV_PUBLIC_BASE = "BOONYARDNN_PUBLIC_BASE"
DEFAULT_PUBLIC_BASE = "http://127.0.0.1:8800"


class _Usage(Exception):
    """A usage error the parser could not catch (e.g. no data root)."""


def _registry(args) -> Registry:
    root = args.root or os.environ.get(ENV_ROOT)
    if not root:
        raise _Usage(f"no data root: pass --root DIR or set {ENV_ROOT}")
    return Registry(Path(root))


def _public_base() -> str:
    return os.environ.get(ENV_PUBLIC_BASE) or DEFAULT_PUBLIC_BASE


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
    if args.key_cmd == "revoke":
        key = provisioner.revoke_key(reg, args.key_id)
        print(f"revoked key {key.key_id} (revoked_at {key.revoked_at})")
        return EXIT_OK
    if args.key_cmd == "list":
        user = provisioner._require_user(reg, args.user)
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
# export / serve
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


# --------------------------------------------------------------------------
# Parser
# --------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="boonyardnn", description="Hosted-layer provisioning and the path router."
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
    p.set_defaults(func=cmd_user)

    p = sub.add_parser("node", help="node add <user> <node> [--profile TOML] | node list <user>")
    ns = p.add_subparsers(dest="node_cmd", required=True)
    a = ns.add_parser("add", help="create and initialise a node under a user")
    a.add_argument("user")
    a.add_argument("node")
    a.add_argument("--profile", help="a boonyard.toml to copy in (default: the starter profile)")
    ls = ns.add_parser("list", help="a user's nodes")
    ls.add_argument("user")
    p.set_defaults(func=cmd_node)

    p = sub.add_parser("key", help="key add <user> <node> [--label L] | key revoke <id> | key list")
    ks = p.add_subparsers(dest="key_cmd", required=True)
    a = ks.add_parser("add", help="mint a per-node key; prints it ONCE (ADR-0008)")
    a.add_argument("user")
    a.add_argument("node")
    a.add_argument("--label")
    r = ks.add_parser("revoke", help="revoke a key by id (row kept for audit)")
    r.add_argument("key_id")
    ls = ks.add_parser("list", help="a node's keys: labels and dates, never hashes")
    ls.add_argument("user")
    ls.add_argument("node")
    p.set_defaults(func=cmd_key)

    p = sub.add_parser("export", help="export bundle into the user's exports/ (no lock-in)")
    p.add_argument("user")
    p.add_argument("node")
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("serve", help="run the router (stdlib http.server)")
    p.add_argument("--host", default=DEFAULT_HOST)
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.set_defaults(func=cmd_serve)

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
    except (_Usage, RegistryError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
