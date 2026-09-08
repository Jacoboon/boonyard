"""The provisioner — user → node → key, the operator-run half of the hosted layer.

One command makes ADR-0007's directory, one mints ADR-0008's key, one exports
the node. This is the layer a signup platform will call (Professor, boonyard
#109: a real signup and user database, open beyond the first twenty founders);
until that ships, the operator runs these by hand. The registry owns the files;
the adapter owns the substrate; this module wires the two and nothing else.
"""

from datetime import UTC, datetime
from pathlib import Path

from . import adapter
from .registry import ApiKey, Node, NotFoundError, Registry, User


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _compact_utc(iso: str) -> str:
    """``2026-09-06T21:00:00+00:00`` -> ``20260906T210000Z`` (filename-safe ISO 8601)."""
    return datetime.fromisoformat(iso).astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def _require_user(registry: Registry, user_slug: str) -> User:
    user = registry.get_user(user_slug)
    if user is None:
        raise NotFoundError(f"no user {user_slug!r}")
    return user


def _require_node(registry: Registry, user: User, node_slug: str) -> Node:
    node = registry.get_node(user, node_slug)
    if node is None:
        raise NotFoundError(f"no node {node_slug!r} for user {user.slug!r}")
    return node


def add_user(registry: Registry, slug: str, email: str) -> User:
    """``user add``: create the per-user directory and index row.

    Example:
        add_user(reg, "jacoboon", "jacob@example.test")
    """
    return registry.create_user(slug, email)


def add_node(
    registry: Registry,
    user_slug: str,
    node_slug: str,
    *,
    profile_path: str | Path | None = None,
) -> Node:
    """``node add``: a node directory with a REAL initialised ``journal.db``.

    The journal comes from the package's own ``init_db`` via the adapter — never
    a bare sqlite file (umbrella #315's stub trap). ``boonyard.toml`` is either the
    file at ``profile_path`` or the package's starter profile named after the node.

    Example:
        add_node(reg, "jacoboon", "test-0")
    """
    user = _require_user(registry, user_slug)
    profile_text = (
        Path(profile_path).read_text(encoding="utf-8") if profile_path is not None else None
    )

    def init(node_dir: Path) -> str:
        toml = profile_text if profile_text is not None else adapter.starter_profile_toml(node_slug)
        (node_dir / "boonyard.toml").write_text(toml, encoding="utf-8")
        return adapter.init_node(node_dir / "journal.db", node_name=node_slug)

    return registry.create_node(user, node_slug, init=init)


def add_key(
    registry: Registry, user_slug: str, node_slug: str, *, label: str | None = None
) -> tuple[str, ApiKey]:
    """``key add``: mint a per-node key. Returns ``(raw, record)``; the caller prints raw ONCE.

    Example:
        raw, key = add_key(reg, "jacoboon", "test-0", label="code seat")
    """
    user = _require_user(registry, user_slug)
    node = _require_node(registry, user, node_slug)
    return registry.create_key(user, node, label=label)


def add_account_key(
    registry: Registry, user_slug: str, *, label: str | None = None
) -> tuple[str, ApiKey]:
    """``key add-account``: mint one key for EVERY node this account owns (ADR-0014).

    Present and future: a node created tomorrow is reachable through the same
    connector with no re-configuration, because the router builds the node map per
    request. Revoking this key cuts access to every node at once — say so wherever it
    is minted (ADR-0014 §8).

    Example:
        raw, key = add_account_key(reg, "jacoboon", label="laptop")
    """
    user = _require_user(registry, user_slug)
    return registry.create_account_key(user, label=label)


def account_key_url(public_base: str, user_slug: str) -> str:
    """The account door's URL. Header auth only — no capability form (ADR-0014 §2.2).

    Example:
        account_key_url("https://mcp.boonyard.com", "jacoboon")
    """
    return f"{public_base.rstrip('/')}/{user_slug}"


def revoke_key(registry: Registry, key_id: str) -> ApiKey:
    """``key revoke``: revoke by id; the row is kept for audit (arch 05).

    Example:
        revoke_key(reg, "2f1c…")
    """
    return registry.revoke_key(key_id)


def export_node(
    registry: Registry, user_slug: str, node_slug: str, *, now: str | None = None
) -> Path:
    """``export``: the package's export bundle into the user's ``exports/``.

    ADR-0007's no-lock-in promise, mechanically: the bundle is the node's own
    ``journal.db`` + ``boonyard.toml`` + manifest, named ``export_{ISO8601}.zip``
    (compact form — colons are not filename-safe everywhere).

    Example:
        export_node(reg, "jacoboon", "test-0")
        # -> …/users/<id>/exports/export_20260906T210000Z.zip
    """
    user = _require_user(registry, user_slug)
    node = _require_node(registry, user, node_slug)
    stamp = now or _now_iso()
    ndir = registry.node_dir(user, node)
    dest = registry.user_dir(user) / "exports" / f"export_{_compact_utc(stamp)}.zip"
    return adapter.export_node(
        dest,
        db_path=ndir / "journal.db",
        profile_path=ndir / "boonyard.toml",
        exported_at=stamp,
    )


def remove_node(registry: Registry, user_slug: str, node_slug: str) -> Path:
    """``node remove``: tombstone the node (directory moved aside, keys revoked). Returns the path.

    Example:
        remove_node(reg, "jacoboon", "scratch")
    """
    user = _require_user(registry, user_slug)
    node = _require_node(registry, user, node_slug)
    return registry.remove_node(user, node)


def set_plan(registry: Registry, user_slug: str, plan: str) -> User:
    """``user plan``: mirror the account's plan into the registry (the router reads it there).

    Example:
        set_plan(reg, "jacoboon", "owner")
    """
    user = _require_user(registry, user_slug)
    return registry.set_plan(user, plan)


def backup_config(registry: Registry, base_path: str | Path | None = None) -> str:
    """A ``[nodes]`` TOML table for the nightly backup: the base file's nodes + every hosted node.

    ``backup_walls.py`` (the proven export → restore-proof → heartbeat path) reads a
    ``[nodes]`` table of ``key = 'journal.db path'``. This returns that table with the
    six walls copied from ``base_path`` (so the heartbeat still lands on ``umbrella``)
    and one row per hosted node keyed ``{user_slug}__{node_slug}`` — the double
    underscore cannot occur inside a slug, so the key is unambiguous and the bundle
    directory it names is per node. Generated at run time, never hand-edited: a new
    founder's node is in the next run with no config change (umbrella #339).

    Example:
        backup_config(reg, "/etc/boonyard/umbrella.toml")
    """
    import tomllib

    rows: list[tuple[str, str]] = []
    if base_path is not None:
        with open(base_path, "rb") as fh:
            base = tomllib.load(fh)
        rows.extend((k, str(v)) for k, v in base.get("nodes", {}).items())
    for user, node in registry.all_nodes():
        db = (registry.node_dir(user, node) / "journal.db").resolve()
        rows.append((f"{user.slug}__{node.slug}", db.as_posix()))
    lines = [
        "# GENERATED by `boonyardnn backup-config` — do not edit. The six walls come from the",
        "# base file; every hosted node (users/*/nodes/*/journal.db) is discovered from the",
        "# registry at run time (umbrella #339). Keys: base keys as-is; hosted = user__node.",
        "[nodes]",
    ]
    for key, path in rows:
        lines.append(f"{key} = '{path}'")
    return "\n".join(lines) + "\n"


def key_urls(public_base: str, user_slug: str, node_slug: str, raw_key: str) -> dict[str, str]:
    """The two URL forms the router serves for one key (ADR-0008 + capability URL).

    ``header``: ``POST {base}/{user}/{node}`` with ``Authorization: Bearer <key>``.
    ``capability``: ``{base}/{user}/{node}/<key>`` — the key as the trailing path
    segment, for clients whose connector dialog has no header field.

    Example:
        key_urls("https://mcp.boonyard.com", "jacoboon", "test-0", "bnyk_…")
    """
    header = f"{public_base.rstrip('/')}/{user_slug}/{node_slug}"
    return {"header": header, "capability": f"{header}/{raw_key}"}
