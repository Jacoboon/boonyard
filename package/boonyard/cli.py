"""The ``boonyard`` command-line interface (arch 04, minus ``migrate``).

All human-facing output lives here — the library never prints (CLAUDE.md). Every
command resolves its target node via ``--db`` / ``$BOONYARD_DB_PATH`` / a local
node (config precedence, arch 04) and its profile via ``--profile`` / a local
``boonyard.toml``. ``argparse`` + stdlib only (ADR-0001).

Exit codes: 0 success; 1 "not found" (a show/thread/latest that resolved to
nothing); 2 a usage / validation error.
"""

import argparse
import json
import sys
from pathlib import Path

from . import __version__, query
from .aggregator import aggregator
from .backup import backup_node
from .constants import DEFAULT_DB_FILENAME, DEFAULT_MCP_PORT, DEFAULT_NODE_DIRNAME
from .db import init_db, reindex
from .export import export_bundle, import_bundle
from .log import log_entry
from .profile import load_profile, resolve_db_path, resolve_profile_path
from .retag import retag_entry

EXIT_OK = 0
EXIT_NOT_FOUND = 1
EXIT_USAGE = 2


# --------------------------------------------------------------------------
# Resolution + formatting helpers
# --------------------------------------------------------------------------
def _db(args) -> Path:
    return resolve_db_path(getattr(args, "db", None))


def _profile(args):
    return load_profile(resolve_profile_path(getattr(args, "profile", None)))


def _fmt_entry(entry: dict, *, full: bool = False) -> str:
    src = f" @{entry['source']}" if entry.get("source") else ""
    head = f"#{entry['id']} [{entry['timestamp']}] {entry['agent']}/{entry['entry_type']}{src}"
    content = entry["content"] if full else entry["content"].splitlines()[0][:100]
    lines = [head, f"  {content}"]
    if entry.get("related_id"):
        lines.append(f"  ↳ related_id: {entry['related_id']}")
    if entry.get("tags"):
        lines.append(f"  tags: {', '.join(entry['tags'])}")
    return "\n".join(lines)


def _print_entries(entries: list[dict]) -> None:
    if not entries:
        print("(no entries)")
        return
    for entry in entries:
        print(_fmt_entry(entry))


def _emit_warnings(warns: list[str]) -> None:
    for warning in warns:
        print(f"warning: {warning}", file=sys.stderr)


# --------------------------------------------------------------------------
# Command handlers
# --------------------------------------------------------------------------
def cmd_init(args) -> int:
    db_path = (
        resolve_db_path(args.db) if args.db else Path(DEFAULT_NODE_DIRNAME) / DEFAULT_DB_FILENAME
    )
    init_db(db_path, node_name=args.name)
    toml_path = Path(db_path).parent / "boonyard.toml"
    if not toml_path.exists():
        name = args.name or Path(db_path).parent.name
        toml_path.write_text(
            f'[node]\nname = "{name}"\nschema_version = 3\n\n'
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
    print(f"initialized node at {db_path}")
    print(f"profile at {toml_path}")
    return EXIT_OK


def cmd_log(args) -> int:
    warns: list[str] = []
    new_id = log_entry(
        args.agent,
        args.entry_type,
        args.content,
        related_id=args.related,
        tags=args.tags,
        extras=json.loads(args.extras) if args.extras else None,
        db_path=_db(args),
        profile=_profile(args),
        warnings_out=warns,
    )
    _emit_warnings(warns)
    print(new_id)
    return EXIT_OK


def cmd_recent(args) -> int:
    _print_entries(query.recent(args.n, agent=args.agent, entry_type=args.type, db_path=_db(args)))
    return EXIT_OK


def cmd_show(args) -> int:
    entry = query.by_id(args.id, db_path=_db(args))
    if entry is None:
        print(f"entry {args.id} not found", file=sys.stderr)
        return EXIT_NOT_FOUND
    print(_fmt_entry(entry, full=True))
    return EXIT_OK


def cmd_thread(args) -> int:
    entries = query.get_thread(args.root_id, db_path=_db(args))
    if not entries:
        print(f"no thread rooted at {args.root_id}", file=sys.stderr)
        return EXIT_NOT_FOUND
    _print_entries(entries)
    return EXIT_OK


def cmd_tag(args) -> int:
    fn = query.search_by_tag_exact if args.exact else query.search_by_tag
    _print_entries(fn(args.tag, args.n, db_path=_db(args)))
    return EXIT_OK


def cmd_find(args) -> int:
    _print_entries(query.search_text(args.query, args.n, db_path=_db(args)))
    return EXIT_OK


def cmd_tags(args) -> int:
    result = query.list_tags(prefix=args.prefix, tree=args.tree, db_path=_db(args))
    if args.tree:
        for category, items in result.items():
            print(f"{category}:")
            for item in items:
                print(f"  {item['tag']} ({item['count']})")
    else:
        for item in result:
            print(f"{item['tag']} ({item['count']})")
    return EXIT_OK


def cmd_agents(args) -> int:
    for item in query.list_agents(db_path=_db(args)):
        print(f"{item['agent']} ({item['count']})")
    return EXIT_OK


def cmd_types(args) -> int:
    for item in query.list_entry_types(db_path=_db(args)):
        print(f"{item['entry_type']} ({item['count']})")
    return EXIT_OK


def cmd_skills(args) -> int:
    skills = query.list_skills(args.n, db_path=_db(args))
    if not skills:
        print("(no skills)")
        return EXIT_OK
    for skill in skills:
        flag = " [DEPRECATED]" if skill["is_deprecated"] else ""
        slug = skill["slug"] or f"(root {skill['root_id']})"
        n_rev = len(skill["all_revisions"])
        print(f"{slug}{flag} — {n_rev} revision(s), latest #{skill['latest']['id']}")
    return EXIT_OK


def cmd_skill(args) -> int:
    if args.skill_cmd == "latest":
        entry = query.latest_skill(args.slug, db_path=_db(args))
        if entry is None:
            print(f"no skill '{args.slug}'", file=sys.stderr)
            return EXIT_NOT_FOUND
        print(_fmt_entry(entry, full=True))
        return EXIT_OK
    if args.skill_cmd == "new":
        print(_SKILL_TEMPLATE.format(slug=args.slug))
        return EXIT_OK
    return EXIT_USAGE


def cmd_doctor(args) -> int:
    report = query.audit_doctor(db_path=_db(args), profile=_profile(args))
    print("== boonyard doctor ==")
    if not report["warnings"]:
        print("no warnings.")
    for warning in report["warnings"]:
        ids = ", ".join(str(i) for i in warning["sample_ids"])
        print(f"[{warning['kind']}] {warning['count']} — sample ids: {ids}")
    for finding in report["skill_threads_not_root_anchored"]:
        print(
            f"[skill-not-root-anchored] slug={finding['slug']} id={finding['broken_revision_id']}"
        )
    for agent in report["unknown_agents"]:
        print(f"[unknown-agent] {agent['agent']} ({agent['count']})")
    for etype in report["unknown_entry_types"]:
        print(f"[unknown-entry-type] {etype['entry_type']} ({etype['count']})")
    for suggestion in report["suggestions"]:
        print(f"  → {suggestion}")
    return EXIT_OK


def cmd_reindex(args) -> int:
    reindex(db_path=_db(args), profile=_profile(args))
    print("reindexed.")
    return EXIT_OK


def cmd_retag(args) -> int:
    retag_entry(args.id, args.new_tags, reason=args.reason, actor=args.actor, db_path=_db(args))
    print(f"retagged entry {args.id}")
    return EXIT_OK


def cmd_info(args) -> int:
    info = query.node_info(db_path=_db(args), profile=_profile(args))
    for key, value in info.items():
        print(f"{key}: {value}")
    return EXIT_OK


def cmd_backup(args) -> int:
    db_path = _db(args)
    dest = args.path or f"{db_path}.bak"
    backup_node(dest, db_path=db_path)
    print(f"backed up {db_path} -> {dest}")
    return EXIT_OK


def cmd_export(args) -> int:
    db_path = _db(args)
    dest = args.path or f"{db_path}.export.zip"
    profile_path = resolve_profile_path(getattr(args, "profile", None))
    export_bundle(dest, db_path=db_path, profile_path=profile_path)
    print(f"exported {db_path} -> {dest}")
    return EXIT_OK


def cmd_import(args) -> int:
    dest = import_bundle(args.path, _db(args), overwrite=args.force)
    print(f"imported {args.path} -> {dest}")
    return EXIT_OK


def _resolve_mcp_key(args) -> str | None:
    """The bearer key: --key wins, else $BOONYARD_MCP_KEY (keeps it out of argv)."""
    import os

    return args.key or os.environ.get("BOONYARD_MCP_KEY")


def cmd_mcp(args) -> int:
    from .mcp import serve

    key = _resolve_mcp_key(args)
    auth = "bearer-auth ON" if key else "no auth (local)"
    if args.config:
        nodes = _load_umbrella_nodes(Path(args.config))
        print(
            f"serving aggregator ({len(nodes)} nodes, read-only, {auth}) "
            f"on {args.host}:{args.port}"
        )
        serve(aggregator=aggregator(nodes=nodes), host=args.host, port=args.port, api_key=key)
    else:
        db_path = _db(args)
        print(f"serving node {db_path} ({auth}) on {args.host}:{args.port}")
        serve(
            db_path=db_path,
            profile=_profile(args),
            host=args.host,
            port=args.port,
            api_key=key,
        )
    return EXIT_OK


# --------------------------------------------------------------------------
# Umbrella (aggregator) subcommands
# --------------------------------------------------------------------------
def _umbrella_path(args) -> Path:
    if getattr(args, "config", None):
        return Path(args.config)
    return Path.home() / ".config" / "boonyard" / "umbrella.toml"


def _load_umbrella_nodes(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    from .profile import _safe_load_toml

    data = _safe_load_toml(path) or {}
    return {k: str(v) for k, v in data.get("nodes", {}).items()}


def _write_umbrella_nodes(path: Path, nodes: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["[nodes]"]
    for name, node_path in nodes.items():
        lines.append(f'{name} = "{Path(node_path).as_posix()}"')
    path.write_text("\n".join(lines) + "\n")


def cmd_umbrella(args) -> int:
    path = _umbrella_path(args)
    if args.umbrella_cmd == "init":
        if path.exists():
            print(f"umbrella already exists at {path}")
        else:
            _write_umbrella_nodes(path, {})
            print(f"created umbrella at {path}")
        return EXIT_OK
    if args.umbrella_cmd == "add":
        nodes = _load_umbrella_nodes(path)
        nodes[args.name] = str(Path(args.path).resolve())
        _write_umbrella_nodes(path, nodes)
        print(f"added {args.name}")
        return EXIT_OK
    if args.umbrella_cmd == "remove":
        nodes = _load_umbrella_nodes(path)
        if args.name not in nodes:
            print(f"no node named {args.name}", file=sys.stderr)
            return EXIT_NOT_FOUND
        del nodes[args.name]
        _write_umbrella_nodes(path, nodes)
        print(f"removed {args.name}")
        return EXIT_OK
    if args.umbrella_cmd == "list":
        nodes = _load_umbrella_nodes(path)
        if not nodes:
            print("(no nodes configured)")
        for name, node_path in nodes.items():
            print(f"{name} = {node_path}")
        return EXIT_OK

    agg = aggregator(nodes=_load_umbrella_nodes(path))
    scope = args.scope.split(",") if getattr(args, "scope", None) else None
    if args.umbrella_cmd == "recent":
        _print_entries(agg.recent(args.n, scope=scope))
    elif args.umbrella_cmd == "find":
        _print_entries(agg.search_text(args.query, args.n, scope=scope))
    elif args.umbrella_cmd == "tags":
        result = agg.list_tags(tree=args.tree, scope=scope)
        if args.tree:
            for category, items in result.items():
                print(f"{category}:")
                for item in items:
                    print(f"  {item['tag']} ({item['count']})")
        else:
            for item in result:
                print(f"{item['tag']} ({item['count']})")
    return EXIT_OK


_SKILL_TEMPLATE = """SKILL: <imperative one-liner — what this lets you do>
WHEN: <the retrieval hook — when to reach for this>
STEPS:
  1. ...
  2. ...
GOTCHAS: <the thing that bit us; the non-obvious failure mode>
SOURCE: <prompt-N / commit / entry id where this was learned>

# Log it: boonyard skill new {slug} renders this; write the body, then:
#   boonyard log code skill "<body>" --tags skill-{slug},<domain-tags>
"""


# --------------------------------------------------------------------------
# Parser
# --------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="boonyard", description="Append-only memory substrate.")
    parser.add_argument("--version", action="version", version=f"boonyard {__version__}")
    parser.add_argument("--db", help="path to the node's journal.db")
    parser.add_argument("--profile", help="path to the node's boonyard.toml")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="create a node + starter boonyard.toml")
    p.add_argument("--name", help="node name")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("log", help="append an entry")
    p.add_argument("agent")
    p.add_argument("entry_type")
    p.add_argument("content")
    p.add_argument("--tags")
    p.add_argument("--related", type=int)
    p.add_argument("--extras", help="JSON string")
    p.set_defaults(func=cmd_log)

    p = sub.add_parser("recent", help="newest entries")
    p.add_argument("n", nargs="?", type=int, default=20)
    p.add_argument("--agent")
    p.add_argument("--type")
    p.set_defaults(func=cmd_recent)

    p = sub.add_parser("show", help="one entry by id")
    p.add_argument("id", type=int)
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("thread", help="a thread by root id")
    p.add_argument("root_id", type=int)
    p.set_defaults(func=cmd_thread)

    p = sub.add_parser("tag", help="entries by tag")
    p.add_argument("tag")
    p.add_argument("n", nargs="?", type=int, default=20)
    p.add_argument("--exact", action="store_true", help="exact tag equality (else substring)")
    p.set_defaults(func=cmd_tag)

    p = sub.add_parser("find", help="full-text search")
    p.add_argument("query")
    p.add_argument("n", nargs="?", type=int, default=20)
    p.set_defaults(func=cmd_find)

    p = sub.add_parser("tags", help="the tag menu")
    p.add_argument("--prefix")
    p.add_argument("--tree", action="store_true")
    p.set_defaults(func=cmd_tags)

    sub.add_parser("agents", help="agents + counts").set_defaults(func=cmd_agents)
    sub.add_parser("types", help="entry_types + counts").set_defaults(func=cmd_types)

    p = sub.add_parser("skills", help="the skill catalog")
    p.add_argument("n", nargs="?", type=int, default=50)
    p.set_defaults(func=cmd_skills)

    p = sub.add_parser("skill", help="skill latest <slug> | new <slug>")
    skill_sub = p.add_subparsers(dest="skill_cmd", required=True)
    sp = skill_sub.add_parser("latest")
    sp.add_argument("slug")
    sp = skill_sub.add_parser("new")
    sp.add_argument("slug")
    p.set_defaults(func=cmd_skill)

    sub.add_parser("doctor", help="self-audit").set_defaults(func=cmd_doctor)
    sub.add_parser("reindex", help="rebuild FTS + entry_tag + extras indexes").set_defaults(
        func=cmd_reindex
    )
    sub.add_parser("info", help="node metadata").set_defaults(func=cmd_info)

    p = sub.add_parser("retag", help="audited tags-only mutation (ADR-0005 exception)")
    p.add_argument("id", type=int)
    p.add_argument("new_tags")
    p.add_argument("--reason", required=True)
    p.add_argument("--actor", required=True)
    p.set_defaults(func=cmd_retag)

    p = sub.add_parser("backup", help="single-file online backup of the node")
    p.add_argument("path", nargs="?", help="destination (default: <db>.bak)")
    p.set_defaults(func=cmd_backup)

    p = sub.add_parser("export", help="portable zip bundle (journal.db + profile)")
    p.add_argument("path", nargs="?", help="destination zip (default: <db>.export.zip)")
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("import", help="restore a boonyard export bundle")
    p.add_argument("path", help="the export bundle zip")
    p.add_argument("--force", action="store_true", help="overwrite an existing node")
    p.set_defaults(func=cmd_import)

    p = sub.add_parser("mcp", help="serve the node over MCP (stdlib http.server)")
    p.add_argument("--port", type=int, default=DEFAULT_MCP_PORT)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--config", help="umbrella.toml to serve as a read-only aggregator")
    p.add_argument("--key", help="require this bearer API key (default: no auth, local)")
    p.set_defaults(func=cmd_mcp)

    p = sub.add_parser("umbrella", help="over-many aggregator")
    p.add_argument("--config", help="path to umbrella.toml")
    um = p.add_subparsers(dest="umbrella_cmd", required=True)
    um.add_parser("init")
    a = um.add_parser("add")
    a.add_argument("name")
    a.add_argument("path")
    r = um.add_parser("remove")
    r.add_argument("name")
    um.add_parser("list")
    ur = um.add_parser("recent")
    ur.add_argument("n", nargs="?", type=int, default=20)
    ur.add_argument("--scope")
    uf = um.add_parser("find")
    uf.add_argument("query")
    uf.add_argument("n", nargs="?", type=int, default=20)
    uf.add_argument("--scope")
    ut = um.add_parser("tags")
    ut.add_argument("--tree", action="store_true")
    ut.add_argument("--scope")
    p.set_defaults(func=cmd_umbrella)

    return parser


def _force_utf8_output() -> None:
    """Emit UTF-8 so non-ASCII output (↳, —, →) never crashes a legacy console.

    Windows' default console encoding is cp1252, which can't encode the glyphs the
    CLI prints; without this, ``boonyard recent`` on any entry with a related_id
    raises UnicodeEncodeError. Reconfiguring is a no-op on redirected streams
    (StringIO/pipes) that lack ``reconfigure``.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def main(argv: list[str] | None = None) -> int:
    """Entry point for the ``boonyard`` command. Returns a process exit code."""
    _force_utf8_output()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
