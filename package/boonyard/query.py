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
import re
from datetime import date, datetime
from pathlib import Path
from sqlite3 import Connection, OperationalError
from typing import TYPE_CHECKING

from .constants import DEFAULT_AGENTS, DEFAULT_ENTRY_TYPES, NON_MODEL_SEATS
from .db import resolve_conn
from .log import validate_entry

if TYPE_CHECKING:
    from .profile import Profile

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
# Dated entries — the kill-date tripwire (umbrella #202 Ruling 4)
# --------------------------------------------------------------------------
# A kill-date is DECLARED, never inferred: it is an entry tagged
# ``killdate:YYYY-MM-DD``. The reader parses the tag; nothing guesses at dates in
# prose. Same namespace culture as ``case:`` / ``arc:`` / ``model:`` (ADR-0009),
# same parse-the-tag precedent as ``_extract_slug`` above.
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _coerce_today(today: date | str | None) -> date:
    """Today as a real ``date`` — **local wall-clock** by default, never UTC.

    ``date.today()`` is localtime; ``datetime.utcnow().date()`` is not, and this
    stack has been bitten by that drift twice in three days (umbrella #53, #200).
    Callers pin ``today`` (a ``date`` or ``'YYYY-MM-DD'``) to make it exact.
    """
    if today is None:
        return date.today()
    if isinstance(today, datetime):
        return today.date()
    if isinstance(today, date):
        return today
    return date.fromisoformat(str(today))


def _extract_dated_tags(tags: list[str], prefix: str) -> tuple[list[tuple[str, date]], list[str]]:
    """Split ``<prefix>:...`` tags into ``(tag, date)`` pairs plus malformed leftovers.

    The ``_extract_slug`` precedent, one namespace over. Anything under the prefix
    that is not a real ``YYYY-MM-DD`` comes back in the second list for the
    caller's ``warnings`` channel — it is skipped, never raised (ADR-0003's
    soft-validation spirit: the substrate captures, it does not gatekeep).

    Example:
        _extract_dated_tags(["killdate:2026-09-23", "killdate:soon"], "killdate")
        # -> ([("killdate:2026-09-23", date(2026, 9, 23))], ["killdate:soon"])
    """
    head = f"{prefix}:"
    good: list[tuple[str, date]] = []
    malformed: list[str] = []
    for tag in tags:
        if not tag.startswith(head):
            continue
        value = tag[len(head) :]
        if not _ISO_DATE.match(value):
            malformed.append(tag)
            continue
        try:
            good.append((tag, date.fromisoformat(value)))
        except ValueError:  # right shape, impossible calendar (killdate:2026-13-40)
            malformed.append(tag)
    return good, malformed


def _dated_entry_rows(
    entry: dict, prefix: str, day: date, within_days: int, node: str | None
) -> tuple[list[dict], list[dict]]:
    """One entry's dated tags -> (result rows, warnings). Shared with the aggregator.

    **A past date is never filtered out.** It returns with ``overdue=True`` and a
    negative ``days_out`` and keeps returning until a human retires it: silence on
    an already-passed date is the 2026-08-20 failure this reader exists to kill.
    Only the future side of the window is bounded.
    """
    rows: list[dict] = []
    warnings: list[dict] = []
    good, malformed = _extract_dated_tags(entry["tags"], prefix)
    for tag in malformed:
        warnings.append(
            {
                "kind": "malformed_date_tag",
                "node": node,
                "entry_id": entry["id"],
                "tag": tag,
                "detail": f"{tag!r} is not {prefix}:YYYY-MM-DD — skipped, not raised",
            }
        )
    for _tag, value in good:  # the tag is reconstructible from prefix + date
        days_out = (value - day).days
        if days_out > within_days:
            continue  # beyond the forward window; the past side is deliberately open
        rows.append(
            {
                "date": value.isoformat(),
                "days_out": days_out,
                "overdue": days_out < 0,
                "entry_id": entry["id"],
                "node": node,
                "agent": entry["agent"],
                "prefix": prefix,
                "headline": " ".join(entry["content"].split())[:120],
                "tags": entry["tags"],
            }
        )
    return rows, warnings


def _dates_envelope(
    day: date, within_days: int, prefix: str, rows: list[dict], warnings: list[dict]
) -> dict:
    """Sort soonest-first (overdue at the top) and wrap in the result envelope."""
    rows.sort(key=lambda r: (r["date"], r["node"] or "", r["entry_id"]))
    return {
        "today": day.isoformat(),
        "within_days": within_days,
        "prefix": prefix,
        "dates": rows,
        "warnings": warnings,
    }


def _node_name(c: Connection) -> str | None:
    """This node's own name from ``meta``, or None if it can't be read."""
    try:
        row = c.execute("SELECT value FROM meta WHERE key = 'node_name'").fetchone()
    except OperationalError:
        return None
    return row["value"] if row is not None else None


def upcoming_dates(
    within_days: int = 45,
    *,
    prefix: str = "killdate",
    today: date | str | None = None,
    conn: Connection | None = None,
    db_path: str | Path | None = None,
) -> dict:
    """The kill-date register: entries tagged ``<prefix>:YYYY-MM-DD``, soonest first.

    Returns an envelope, not a bare list, because the warnings channel is
    load-bearing (a malformed tag or a skipped node must be *seen*, not silently
    dropped)::

        {"today": "2026-08-24", "within_days": 45, "prefix": "killdate",
         "dates": [{date, days_out, overdue, entry_id, node, agent, prefix,
                    headline, tags}, ...],
         "warnings": [{kind, node, entry_id, tag, detail}, ...]}

    Overdue dates sort to the top and **never drop out of the window**; only the
    future side is bounded by ``within_days``. ``days_out`` is measured against the
    local wall-clock date (see :func:`_coerce_today`).

    Example:
        upcoming_dates(45, db_path="node/journal.db")["dates"][0]["overdue"]
    """
    day = _coerce_today(today)
    with resolve_conn(conn, db_path, read_only=True) as c:
        node = _node_name(c)
        # entry_tag is the indexed lookup (the search_by_tag_exact path). The LIKE
        # is only a prefilter — _extract_dated_tags is the authority on what counts.
        rows = c.execute(
            f"SELECT {_ENTRY_COLS} FROM entry "
            "WHERE id IN (SELECT entry_id FROM entry_tag WHERE tag LIKE ?) "
            "ORDER BY id",
            (f"{prefix}:%",),
        ).fetchall()
    dates: list[dict] = []
    warnings: list[dict] = []
    for row in rows:
        entry_rows, entry_warnings = _dated_entry_rows(
            _row_to_entry(row), prefix, day, within_days, node
        )
        dates.extend(entry_rows)
        warnings.extend(entry_warnings)
    return _dates_envelope(day, within_days, prefix, dates, warnings)


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
    profile: "Profile | None" = None,
) -> dict:
    """Full node metadata: identity, schema version, counts, size, last write.

    ``profile``, if given, is summarized under the ``profile`` key.
    ``storage_bytes`` is None for in-memory nodes.
    """
    with resolve_conn(conn, db_path, read_only=True) as c:
        meta = {r["key"]: r["value"] for r in c.execute("SELECT key, value FROM meta")}
        entry_count = c.execute("SELECT COUNT(*) AS n FROM entry").fetchone()["n"]
        last_write = c.execute("SELECT MAX(timestamp) AS t FROM entry").fetchone()["t"]
    profile_summary: dict = {}
    if profile is not None:
        profile_summary = {
            "allowed_agents": sorted(profile.allowed_agents),
            "allowed_entry_types": sorted(profile.allowed_entry_types),
            "namespaces": sorted(profile.namespaces),
            "extras_enabled": profile.extras_enabled,
        }
    return {
        "name": meta.get("node_name"),
        "uuid": meta.get("node_uuid"),
        "schema_version": int(meta["schema_version"]) if "schema_version" in meta else None,
        "created_at": meta.get("created_at"),
        "entry_count": entry_count,
        "storage_bytes": _storage_bytes(db_path),
        "last_write_at": last_write,
        "profile": profile_summary,
    }


def audit_doctor(
    *,
    conn: Connection | None = None,
    db_path: str | Path | None = None,
    profile: "Profile | None" = None,
    known_agents: frozenset[str] = DEFAULT_AGENTS,
    known_entry_types: frozenset[str] = DEFAULT_ENTRY_TYPES,
    known_namespaces: frozenset[str] | None = None,
) -> dict:
    """The substrate's self-audit (arch 06). Full-node scan; returns findings.

    Surfaces: possible deletions (gaps in the autoincrement id sequence — ADR-0005
    says entries are never deleted, so a gap is suspicious), orphaned related_id
    references, soft-validation warnings replayed over every row, skill threads
    that aren't root-anchored, unprecedented (singleton) tags, unknown agents /
    entry_types (the advisory seat registry — wall entry 97), and AI-seat entries
    missing a ``model:`` tag (professor/system exempt). Warns; never mutates. A
    ``profile`` supplies the known sets when given.
    """
    if profile is not None:
        known_agents = profile.allowed_agents
        known_entry_types = profile.allowed_entry_types
        known_namespaces = profile.namespaces
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

        # AI-seat entries missing a model: tag (wall entry 97). professor/system
        # are exempt (they don't self-report a model). Soft: warns, never rejects.
        missing_model = [
            r["id"]
            for r in c.execute("SELECT id, agent, tags FROM entry")
            if r["agent"] not in NON_MODEL_SEATS
            and not any(t.startswith("model:") for t in (r["tags"] or "").split(","))
        ]
        if missing_model:
            warnings.append(
                {
                    "kind": "missing_model_tag",
                    "count": len(missing_model),
                    "sample_ids": missing_model[:10],
                }
            )
            suggestions.append(
                "Some AI-seat entries carry no model: tag (wall entry 97's agent-identity "
                "convention); include model:<exact-model-string> on AI-seat writes."
            )

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
