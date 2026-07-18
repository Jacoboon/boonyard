"""The read path — non-destructive queries over a node (arch 06 is the contract).

Every reader returns entries in the canonical Entry shape: a dict with all eight
columns, ``tags`` parsed to a ``list[str]`` and ``extras`` parsed from JSON. The
raw comma-separated ``entry.tags`` column is an internal storage detail; the API
is structured (arch 06 §Conventions).

Read paths open with ``PRAGMA query_only = ON`` when given a ``db_path`` — the
connection is physically incapable of writing (CLAUDE.md / ADR-0005). This module
is the in-process form of the MCP read tools; the MCP layer (M7) wraps it.
"""

import json
import logging
from pathlib import Path
from sqlite3 import Connection, OperationalError

from .constants import DEFAULT_AGENTS, DEFAULT_ENTRY_TYPES
from .db import resolve_conn
from .log import validate_entry

_log = logging.getLogger("boonyard")

# The canonical column projection for an Entry row.
_ENTRY_COLS = "id, timestamp, agent, entry_type, content, related_id, tags, extras"


def _row_to_entry(row, source: str | None = None) -> dict:
    """Convert a sqlite Row into the canonical Entry dict (tags list, extras parsed)."""
    entry = dict(row)
    entry["tags"] = row["tags"].split(",") if row["tags"] else []
    if entry.get("extras"):
        try:
            entry["extras"] = json.loads(entry["extras"])
        except (ValueError, TypeError):
            pass  # leave malformed extras as its raw string
    if source is not None:
        entry["source"] = source
    return entry


# --------------------------------------------------------------------------
# Core readers
# --------------------------------------------------------------------------
def recent(
    limit: int = 20,
    agent: str | None = None,
    entry_type: str | None = None,
    *,
    conn: Connection | None = None,
    db_path: str | Path | None = None,
) -> list[dict]:
    """Return the newest entries first, optionally filtered by agent / entry_type.

    Example:
        recent(10, agent="code", db_path="node/journal.db")
    """
    with resolve_conn(conn, db_path, read_only=True) as c:
        rows = c.execute(
            f"SELECT {_ENTRY_COLS} FROM entry "
            "WHERE (:agent IS NULL OR agent = :agent) "
            "  AND (:entry_type IS NULL OR entry_type = :entry_type) "
            "ORDER BY id DESC LIMIT :limit",
            {"agent": agent, "entry_type": entry_type, "limit": limit},
        ).fetchall()
    return [_row_to_entry(r) for r in rows]


def by_id(
    entry_id: int,
    *,
    conn: Connection | None = None,
    db_path: str | Path | None = None,
) -> dict | None:
    """Return one entry by id, or None if it doesn't exist."""
    with resolve_conn(conn, db_path, read_only=True) as c:
        row = c.execute(f"SELECT {_ENTRY_COLS} FROM entry WHERE id = ?", (entry_id,)).fetchone()
    return _row_to_entry(row) if row is not None else None


def get_thread(
    root_id: int,
    *,
    conn: Connection | None = None,
    db_path: str | Path | None = None,
) -> list[dict]:
    """Return the root entry plus every entry pointing at it (one level, ADR-0004).

    Oldest-first. For root-anchored skill threads this is the full revision lineage.
    """
    with resolve_conn(conn, db_path, read_only=True) as c:
        rows = c.execute(
            f"SELECT {_ENTRY_COLS} FROM entry WHERE id = :rid OR related_id = :rid ORDER BY id",
            {"rid": root_id},
        ).fetchall()
    return [_row_to_entry(r) for r in rows]


def search_by_tag(
    tag: str,
    limit: int = 20,
    *,
    conn: Connection | None = None,
    db_path: str | Path | None = None,
) -> list[dict]:
    """Substring tag match (``LIKE %tag%``). Casual use; prefer search_by_tag_exact."""
    with resolve_conn(conn, db_path, read_only=True) as c:
        rows = c.execute(
            f"SELECT {_ENTRY_COLS} FROM entry WHERE tags LIKE ? ORDER BY id DESC LIMIT ?",
            (f"%{tag}%", limit),
        ).fetchall()
    return [_row_to_entry(r) for r in rows]


def search_by_tag_exact(
    tag: str,
    limit: int = 20,
    *,
    conn: Connection | None = None,
    db_path: str | Path | None = None,
) -> list[dict]:
    """Exact tag equality via the ``entry_tag`` companion table. Fast at any scale.

    The preferred tool for namespace lookups (``case:...``, ``model:...``) and for
    ``skill-<slug>`` identity lookups.
    """
    with resolve_conn(conn, db_path, read_only=True) as c:
        rows = c.execute(
            f"SELECT e.{', e.'.join(_ENTRY_COLS.split(', '))} "
            "FROM entry e JOIN entry_tag t ON t.entry_id = e.id "
            "WHERE t.tag = ? ORDER BY e.id DESC LIMIT ?",
            (tag, limit),
        ).fetchall()
    return [_row_to_entry(r) for r in rows]


def search_text(
    query: str,
    limit: int = 20,
    *,
    conn: Connection | None = None,
    db_path: str | Path | None = None,
) -> list[dict]:
    """FTS5 search over content. ``query`` accepts FTS5 syntax (``fuse AND boot``).

    Raises ``ValueError`` on malformed FTS syntax (maps to the MCP ``validation``
    error). Newest-first within the match set.
    """
    with resolve_conn(conn, db_path, read_only=True) as c:
        try:
            rows = c.execute(
                f"SELECT e.{', e.'.join(_ENTRY_COLS.split(', '))} "
                "FROM entry e JOIN entry_fts f ON f.rowid = e.id "
                "WHERE entry_fts MATCH ? ORDER BY e.id DESC LIMIT ?",
                (query, limit),
            ).fetchall()
        except OperationalError as exc:
            raise ValueError(f"malformed FTS5 query {query!r}: {exc}") from exc
    return [_row_to_entry(r) for r in rows]


# --------------------------------------------------------------------------
# Metadata / discovery
# --------------------------------------------------------------------------
def list_tags(
    prefix: str | None = None,
    tree: bool = False,
    *,
    conn: Connection | None = None,
    db_path: str | Path | None = None,
) -> list[dict] | dict[str, list[dict]]:
    """The tag menu: every unique tag with its count, most-used first.

    With ``prefix`` only tags starting with it; with ``tree=True`` grouped by the
    top-level category (text before the first hyphen). Backed by ``entry_tag``.
    """
    with resolve_conn(conn, db_path, read_only=True) as c:
        rows = c.execute(
            "SELECT tag, COUNT(*) AS n FROM entry_tag "
            "WHERE (:prefix IS NULL OR tag LIKE :prefix || '%') "
            "GROUP BY tag ORDER BY n DESC, tag ASC",
            {"prefix": prefix},
        ).fetchall()
    flat = [{"tag": r["tag"], "count": r["n"]} for r in rows]
    if not tree:
        return flat
    grouped: dict[str, list[dict]] = {}
    for item in flat:
        category = item["tag"].split("-", 1)[0]
        grouped.setdefault(category, []).append(item)
    return grouped


def list_agents(
    *,
    conn: Connection | None = None,
    db_path: str | Path | None = None,
) -> list[dict]:
    """Every unique agent with its entry count, most-active first."""
    with resolve_conn(conn, db_path, read_only=True) as c:
        rows = c.execute(
            "SELECT agent, COUNT(*) AS n FROM entry GROUP BY agent ORDER BY n DESC, agent ASC"
        ).fetchall()
    return [{"agent": r["agent"], "count": r["n"]} for r in rows]


def list_entry_types(
    *,
    conn: Connection | None = None,
    db_path: str | Path | None = None,
) -> list[dict]:
    """Every unique entry_type with its count, most-used first."""
    with resolve_conn(conn, db_path, read_only=True) as c:
        rows = c.execute(
            "SELECT entry_type, COUNT(*) AS n FROM entry "
            "GROUP BY entry_type ORDER BY n DESC, entry_type ASC"
        ).fetchall()
    return [{"entry_type": r["entry_type"], "count": r["n"]} for r in rows]


# --------------------------------------------------------------------------
# Skills (ADR-0004)
# --------------------------------------------------------------------------
def _extract_slug(tags: list[str]) -> str | None:
    """Return the ``<slug>`` from a ``skill-<slug>`` identity tag, if present."""
    for tag in tags:
        if tag.startswith("skill-") and not tag.endswith("-deprecated"):
            return tag[len("skill-") :]
    return None


def list_skills(
    limit: int = 50,
    *,
    conn: Connection | None = None,
    db_path: str | Path | None = None,
) -> list[dict]:
    """The skill catalog. Each item groups a skill's root + revisions by slug.

    Returns ``{root_id, slug, latest, all_revisions, is_deprecated}`` per skill,
    newest-activity first. Deprecation: any revision carrying a
    ``skill-<slug>-deprecated`` tag (ADR-0005 tombstone).
    """
    with resolve_conn(conn, db_path, read_only=True) as c:
        rows = c.execute(
            f"SELECT {_ENTRY_COLS} FROM entry WHERE entry_type = 'skill' ORDER BY id"
        ).fetchall()

    groups: dict[str, list[dict]] = {}
    for row in rows:
        entry = _row_to_entry(row)
        slug = _extract_slug(entry["tags"])
        root = entry["related_id"] if entry["related_id"] is not None else entry["id"]
        key = slug if slug is not None else f"@root:{root}"
        groups.setdefault(key, []).append(entry)

    skills: list[dict] = []
    for key, revisions in groups.items():
        revisions.sort(key=lambda e: e["id"])
        slug = None if key.startswith("@root:") else key
        deprecated = any(
            t.startswith("skill-") and t.endswith("-deprecated")
            for e in revisions
            for t in e["tags"]
        )
        skills.append(
            {
                "root_id": revisions[0]["id"],
                "slug": slug,
                "latest": revisions[-1],
                "all_revisions": revisions,
                "is_deprecated": deprecated,
            }
        )
    skills.sort(key=lambda s: s["latest"]["id"], reverse=True)
    return skills[:limit]


def latest_skill(
    slug: str,
    *,
    conn: Connection | None = None,
    db_path: str | Path | None = None,
) -> dict | None:
    """The newest revision of the named skill, or None if no such skill exists."""
    with resolve_conn(conn, db_path, read_only=True) as c:
        row = c.execute(
            f"SELECT e.{', e.'.join(_ENTRY_COLS.split(', '))} "
            "FROM entry e JOIN entry_tag t ON t.entry_id = e.id "
            "WHERE e.entry_type = 'skill' AND t.tag = ? ORDER BY e.id DESC LIMIT 1",
            (f"skill-{slug}",),
        ).fetchone()
    return _row_to_entry(row) if row is not None else None


# --------------------------------------------------------------------------
# Operational
# --------------------------------------------------------------------------
def _storage_bytes(db_path: str | Path | None) -> int | None:
    """Sum the sizes of a node's SQLite files (db + -wal + -shm), or None."""
    if db_path is None or str(db_path) == ":memory:":
        return None
    total = 0
    for suffix in ("", "-wal", "-shm"):
        p = Path(f"{db_path}{suffix}")
        if p.exists():
            total += p.stat().st_size
    return total


def node_info(
    *,
    conn: Connection | None = None,
    db_path: str | Path | None = None,
) -> dict:
    """Full node metadata: identity, schema version, counts, size, last write.

    ``profile`` is populated by the profile layer (M4); it is ``{}`` here.
    ``storage_bytes`` is None for in-memory nodes.
    """
    with resolve_conn(conn, db_path, read_only=True) as c:
        meta = {r["key"]: r["value"] for r in c.execute("SELECT key, value FROM meta")}
        entry_count = c.execute("SELECT COUNT(*) AS n FROM entry").fetchone()["n"]
        last_write = c.execute("SELECT MAX(timestamp) AS t FROM entry").fetchone()["t"]
    return {
        "name": meta.get("node_name"),
        "uuid": meta.get("node_uuid"),
        "schema_version": int(meta["schema_version"]) if "schema_version" in meta else None,
        "created_at": meta.get("created_at"),
        "entry_count": entry_count,
        "storage_bytes": _storage_bytes(db_path),
        "last_write_at": last_write,
        "profile": {},
    }


def audit_doctor(
    *,
    conn: Connection | None = None,
    db_path: str | Path | None = None,
    known_agents: frozenset[str] = DEFAULT_AGENTS,
    known_entry_types: frozenset[str] = DEFAULT_ENTRY_TYPES,
    known_namespaces: frozenset[str] | None = None,
) -> dict:
    """The substrate's self-audit (arch 06). Full-node scan; returns findings.

    Surfaces: possible deletions (gaps in the autoincrement id sequence — ADR-0005
    says entries are never deleted, so a gap is suspicious), orphaned related_id
    references, soft-validation warnings replayed over every row, skill threads
    that aren't root-anchored, unprecedented (singleton) tags, and unknown agents
    / entry_types. Warns; never mutates.
    """
    warnings: list[dict] = []
    suggestions: list[str] = []

    with resolve_conn(conn, db_path, read_only=True) as c:
        max_id_row = c.execute("SELECT MAX(id) AS m, COUNT(*) AS n FROM entry").fetchone()
        max_id, count = max_id_row["m"], max_id_row["n"]

        # Possible deletion: a gap in the 1..MAX(id) autoincrement sequence.
        if max_id and max_id != count:
            existing = {r["id"] for r in c.execute("SELECT id FROM entry")}
            missing = [i for i in range(1, max_id + 1) if i not in existing]
            warnings.append(
                {"kind": "possible_deletion", "count": len(missing), "sample_ids": missing[:10]}
            )
            suggestions.append(
                f"{len(missing)} id(s) missing from the sequence — entries are never "
                "deleted (ADR-0005); investigate how these were removed."
            )

        # Orphaned related_id references.
        orphans = [
            r["id"]
            for r in c.execute(
                "SELECT e.id FROM entry e WHERE e.related_id IS NOT NULL "
                "AND NOT EXISTS (SELECT 1 FROM entry p WHERE p.id = e.related_id)"
            )
        ]
        if orphans:
            warnings.append(
                {"kind": "orphaned_related_id", "count": len(orphans), "sample_ids": orphans[:10]}
            )

        # Replay the soft validators over every row.
        flagged: list[int] = []
        for r in c.execute("SELECT id, agent, entry_type, tags FROM entry"):
            if validate_entry(
                r["agent"],
                r["entry_type"],
                r["tags"],
                known_agents=known_agents,
                known_entry_types=known_entry_types,
                known_namespaces=known_namespaces,
                conn=c,
            ):
                flagged.append(r["id"])
        if flagged:
            warnings.append(
                {"kind": "soft_validation", "count": len(flagged), "sample_ids": flagged[:10]}
            )

        # Skill threads not root-anchored: a revision pointing at a non-root entry.
        not_anchored: list[dict] = []
        skill_rows = c.execute(
            f"SELECT {_ENTRY_COLS} FROM entry WHERE entry_type = 'skill' ORDER BY id"
        ).fetchall()
        for row in skill_rows:
            entry = _row_to_entry(row)
            parent = entry["related_id"]
            if parent is None:
                continue
            parent_row = c.execute(
                "SELECT related_id FROM entry WHERE id = ?", (parent,)
            ).fetchone()
            if parent_row is not None and parent_row["related_id"] is not None:
                not_anchored.append(
                    {"slug": _extract_slug(entry["tags"]), "broken_revision_id": entry["id"]}
                )

        # Unprecedented (singleton) tags — one-offs, common home of typos/forks.
        unprecedented = [
            {"tag": r["tag"], "count": r["n"]}
            for r in c.execute(
                "SELECT tag, COUNT(*) AS n FROM entry_tag GROUP BY tag HAVING n = 1 "
                "ORDER BY tag ASC"
            )
        ]

        # Unknown agents / entry_types vs the known (default or profile) sets.
        unknown_agents = [
            {"agent": r["agent"], "count": r["n"]}
            for r in c.execute("SELECT agent, COUNT(*) AS n FROM entry GROUP BY agent")
            if r["agent"] not in known_agents
        ]
        unknown_entry_types = [
            {"entry_type": r["entry_type"], "count": r["n"]}
            for r in c.execute("SELECT entry_type, COUNT(*) AS n FROM entry GROUP BY entry_type")
            if r["entry_type"] not in known_entry_types
        ]

    if not_anchored:
        suggestions.append(
            "Some skill revisions aren't root-anchored (ADR-0004); re-log them with "
            "related_id set to the skill's root."
        )

    return {
        "warnings": warnings,
        "suggestions": suggestions,
        "skill_threads_not_root_anchored": not_anchored,
        "unprecedented_tags": unprecedented,
        "unknown_agents": unknown_agents,
        "unknown_entry_types": unknown_entry_types,
    }
