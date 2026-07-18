"""The write path — the only legitimate way to insert entries (ADR-0005).

``log_entry`` is the universal write. ``log_skill_revision`` is sugar over it
that enforces the skill conventions (ADR-0004: entry_type=skill, the
``skill-<slug>`` identity tag, root-anchored revisions).

Validation is *soft* (ADR-0002, ADR-0009): the substrate captures, it does not
gatekeep. Unknown agents / entry_types / tag namespaces and malformed tags
**warn but insert**. Only a handful of things hard-fail: missing required
fields, and a ``related_id`` that points at no existing entry. If you ever find
yourself hard-rejecting a soft case, you have misread an ADR — stop and surface.

Warnings surface two ways: on the ``"boonyard"`` logger (stderr by default), and,
if the caller passes ``warnings_out=[]``, appended there verbatim for the CLI /
MCP layer to echo back as response metadata.

Lineage: grown from PlaneScape's ``_dev/journal/log.py`` (the v1 soft-validating
writer), extended to the v3 conventions.
"""

import json
import logging
from collections.abc import Iterable
from pathlib import Path
from sqlite3 import Connection

from .constants import DEFAULT_AGENTS, DEFAULT_ENTRY_TYPES
from .db import resolve_conn

_log = logging.getLogger("boonyard")


# --------------------------------------------------------------------------
# Tag normalization + soft checks (one source of truth, shared with the doctor)
# --------------------------------------------------------------------------
def _normalize_tags(raw: str | None, entry_type: str) -> tuple[list[str], list[str]]:
    """Clean a comma-separated tag string into an ordered, de-duplicated list.

    Returns ``(clean_tags, warnings)``. Cleaning is conservative (ADR-0009): tags
    are whitespace-stripped and lowercased; whitespace *inside* a tag splits it
    into multiple tags. Underscores/dots are warned about but preserved (JRHood's
    free-form culture uses them). The entry_type is always present as a tag (the
    type-tag mandate) — added automatically, without a warning.
    """
    warnings: list[str] = []
    clean: list[str] = []
    seen: set[str] = set()

    def _add(tag: str) -> None:
        if tag and tag not in seen:
            seen.add(tag)
            clean.append(tag)

    for chunk in (raw or "").split(","):
        piece = chunk.strip()
        if not piece:
            continue  # trailing/double commas are common and harmless — skip quietly
        parts = piece.split()  # internal whitespace → multiple tags (ADR-0009)
        if len(parts) > 1:
            warnings.append(f"tag {piece!r} contains whitespace; split into {parts}")
        for part in parts:
            low = part.lower()
            if part != low:
                warnings.append(f"tag {part!r} had uppercase; stored lowercased as {low!r}")
            if "_" in low:
                warnings.append(f"tag {low!r} uses an underscore; prefer hyphens (ADR-0009)")
            if "." in low:
                warnings.append(f"tag {low!r} uses a dot; prefer hyphens (ADR-0009)")
            _add(low)

    # Type-tag mandate (ADR-0009): every entry carries its entry_type as a tag.
    et = (entry_type or "").strip().lower()
    if et:
        _add(et)

    return clean, warnings


def _namespace_warnings(tags: Iterable[str], known_namespaces: frozenset[str] | None) -> list[str]:
    """Warn on ``prefix:value`` tags whose prefix isn't a declared namespace.

    ``known_namespaces=None`` means "no declaration to check against" (e.g. no
    profile loaded yet) and skips the check entirely — never noisy by default.
    """
    if known_namespaces is None:
        return []
    out: list[str] = []
    for tag in tags:
        if ":" in tag:
            prefix = tag.split(":", 1)[0]
            if prefix and prefix not in known_namespaces:
                out.append(f"tag namespace {prefix!r} (in {tag!r}) is not declared in the profile")
    return out


def _plural_fork_warnings(conn: Connection | None, tags: Iterable[str]) -> list[str]:
    """Warn when a tag's top-level prefix is a plural of a prefix already in use.

    The empirical plural-fork bug (ADR-0009): ``skills-system`` forking a node
    that already uses ``skill-*``. Needs whole-node context, so it runs only when
    a connection is available. Simple ``-s`` / ``-es`` suffix heuristic; false
    positives are tolerable because these are warnings, not rejections.
    """
    if conn is None:
        return []
    existing = {
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT substr(tag, 1, "
            "CASE WHEN instr(tag,'-')>0 THEN instr(tag,'-')-1 ELSE length(tag) END) "
            "FROM entry_tag"
        )
    }
    out: list[str] = []
    for tag in tags:
        prefix = tag.split("-", 1)[0]
        singulars = set()
        if prefix.endswith("es"):
            singulars.add(prefix[:-2])
        if prefix.endswith("s"):
            singulars.add(prefix[:-1])
        for singular in singulars:
            if singular and singular in existing and prefix not in existing:
                out.append(
                    f"tag prefix {prefix!r} looks plural; singular {singular!r} "
                    f"is already in use in this node (ADR-0009 plural-fork)"
                )
    return out


def validate_entry(
    agent: str,
    entry_type: str,
    tags: str | None = None,
    *,
    known_agents: frozenset[str] = DEFAULT_AGENTS,
    known_entry_types: frozenset[str] = DEFAULT_ENTRY_TYPES,
    known_namespaces: frozenset[str] | None = None,
    conn: Connection | None = None,
) -> list[str]:
    """Return the soft-validation warnings for an entry (never raises).

    This is the reusable validator the write path emits and ``audit_doctor`` (M3)
    replays over existing rows. It reports unknown agent / entry_type, tag
    well-formedness, undeclared namespaces, and probable plural-forks. Hard-fail
    conditions (missing required fields, non-existent related_id) are enforced by
    :func:`log_entry`, not here.
    """
    clean, warnings = _normalize_tags(tags, entry_type)
    if agent and agent not in known_agents:
        warnings.append(f"unknown agent {agent!r} — logging anyway (soft validation)")
    if entry_type and entry_type not in known_entry_types:
        warnings.append(f"unknown entry_type {entry_type!r} — logging anyway (soft validation)")
    warnings.extend(_namespace_warnings(clean, known_namespaces))
    warnings.extend(_plural_fork_warnings(conn, clean))
    return warnings


# --------------------------------------------------------------------------
# Extras serialization
# --------------------------------------------------------------------------
def _serialize_extras(extras: dict | list | str | None) -> tuple[str | None, list[str]]:
    """Normalize ``extras`` to JSON text for the column. Returns ``(text, warnings)``.

    dict/list are JSON-encoded; a str is assumed to already be JSON and is
    validated (a warning, not a failure, on invalid JSON — the substrate captures).
    """
    if extras is None:
        return None, []
    if isinstance(extras, str):
        try:
            json.loads(extras)
        except (ValueError, TypeError):
            return extras, ["extras is not valid JSON — stored as-is (soft validation)"]
        return extras, []
    try:
        return json.dumps(extras), []
    except (TypeError, ValueError) as exc:
        return json.dumps(str(extras)), [f"extras not JSON-serializable ({exc}); stored as string"]


# --------------------------------------------------------------------------
# Warning emission
# --------------------------------------------------------------------------
def _emit(warnings: list[str], sink: list[str] | None) -> None:
    for w in warnings:
        _log.warning("%s", w)
    if sink is not None:
        sink.extend(warnings)


def _populate_entry_tags(conn: Connection, entry_id: int, tags: list[str]) -> None:
    """Insert one ``entry_tag`` row per tag, in the same transaction as the entry.

    The insert-side denormalization the schema's ``entry_ai_tags`` trigger
    documents as application-owned (arch 02). ``INSERT OR IGNORE`` tolerates the
    (entry_id, tag) primary key on any accidental duplicate.
    """
    if tags:
        conn.executemany(
            "INSERT OR IGNORE INTO entry_tag (entry_id, tag) VALUES (?, ?)",
            [(entry_id, tag) for tag in tags],
        )


# --------------------------------------------------------------------------
# The universal write
# --------------------------------------------------------------------------
def log_entry(
    agent: str,
    entry_type: str,
    content: str,
    related_id: int | None = None,
    tags: str | None = None,
    extras: dict | list | str | None = None,
    *,
    conn: Connection | None = None,
    db_path: str | Path | None = None,
    known_agents: frozenset[str] = DEFAULT_AGENTS,
    known_entry_types: frozenset[str] = DEFAULT_ENTRY_TYPES,
    known_namespaces: frozenset[str] | None = None,
    warnings_out: list[str] | None = None,
) -> int:
    """Write one entry and return its new id. The universal write path.

    Hard-fails (raise ``ValueError``): empty ``agent`` / ``entry_type`` /
    ``content``; a ``related_id`` that references no existing entry. Everything
    else is soft — unknown agents/types, malformed tags, undeclared namespaces —
    and warns while still inserting (ADR-0002, ADR-0009). The entry_type is added
    to ``tags`` automatically if absent (the type-tag mandate). ``entry_tag`` rows
    are populated in the same transaction as the ``entry`` insert.

    Provide either ``conn`` (caller-managed) or ``db_path`` (opened+committed here).

    Example:
        new_id = log_entry(
            "code", "implementation", "Wrote log_entry.",
            tags="implementation,boonyardnn,model:claude-opus-4-8",
            db_path="node/journal.db",
        )
    """
    if not agent or not agent.strip():
        raise ValueError("agent is required and must be non-empty")
    if not entry_type or not entry_type.strip():
        raise ValueError("entry_type is required and must be non-empty")
    if content is None or content == "":
        raise ValueError("content is required and must be non-empty")

    clean_tags, tag_warnings = _normalize_tags(tags, entry_type)
    extras_text, extras_warnings = _serialize_extras(extras)

    with resolve_conn(conn, db_path) as c:
        if related_id is not None:
            exists = c.execute("SELECT 1 FROM entry WHERE id = ?", (related_id,)).fetchone()
            if exists is None:
                raise ValueError(f"related_id {related_id} does not reference an existing entry")

        soft = list(tag_warnings)
        if agent not in known_agents:
            soft.append(f"unknown agent {agent!r} — logging anyway (soft validation)")
        if entry_type not in known_entry_types:
            soft.append(f"unknown entry_type {entry_type!r} — logging anyway (soft validation)")
        soft.extend(_namespace_warnings(clean_tags, known_namespaces))
        soft.extend(_plural_fork_warnings(c, clean_tags))
        soft.extend(extras_warnings)
        _emit(soft, warnings_out)

        cursor = c.execute(
            "INSERT INTO entry (agent, entry_type, content, related_id, tags, extras) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (agent, entry_type, content, related_id, ",".join(clean_tags), extras_text),
        )
        new_id = int(cursor.lastrowid)
        _populate_entry_tags(c, new_id, clean_tags)

    _log.debug("entry %d [%s/%s]: %s", new_id, agent, entry_type, content[:80])
    return new_id


# --------------------------------------------------------------------------
# Skills (ADR-0004)
# --------------------------------------------------------------------------
def _resolve_skill_root(conn: Connection, root_id: int) -> int:
    """Return the true root id for a skill thread.

    Root-anchoring means every revision's ``related_id`` points at the root. So if
    ``root_id`` is itself a revision (has a ``related_id``), the real root is that
    ``related_id``; otherwise ``root_id`` is already the root. This is what lets a
    caller pass *any* revision's id and still anchor correctly (ADR-0004).
    """
    row = conn.execute("SELECT id, related_id FROM entry WHERE id = ?", (root_id,)).fetchone()
    if row is None:
        raise ValueError(f"root_id {root_id} does not reference an existing entry")
    return row["related_id"] if row["related_id"] is not None else row["id"]


def _root_slug(conn: Connection, root_id: int) -> str | None:
    """Find the ``skill-<slug>`` identity tag on a root skill, if any."""
    row = conn.execute("SELECT tags FROM entry WHERE id = ?", (root_id,)).fetchone()
    if row is None or not row["tags"]:
        return None
    for tag in row["tags"].split(","):
        if tag.startswith("skill-") and not tag.endswith("-deprecated"):
            return tag[len("skill-") :]
    return None


def log_skill_revision(
    agent: str,
    content: str,
    *,
    root_id: int | None = None,
    slug: str | None = None,
    tags: str | None = None,
    extras: dict | list | str | None = None,
    conn: Connection | None = None,
    db_path: str | Path | None = None,
    warnings_out: list[str] | None = None,
) -> int:
    """Write a ``skill`` entry, enforcing the skill conventions (ADR-0004).

    ``entry_type`` is forced to ``skill``. If ``root_id`` is None this is the
    first revision and it *becomes* the root (``related_id`` stays NULL). If
    ``root_id`` is given, the revision is anchored to that skill's true root — so
    ``get_thread(root_id)`` always sees every revision. The ``skill`` tag (via the
    type-tag mandate) and the ``skill-<slug>`` identity tag are ensured present;
    when revising, the slug is inherited from the root if not given.

    Example:
        root = log_skill_revision("code", "SKILL: ...", slug="fuse-boot", db_path=p)
        v2   = log_skill_revision("code", "SKILL: ... v2", root_id=root, db_path=p)
    """
    with resolve_conn(conn, db_path) as c:
        related: int | None = None
        if root_id is not None:
            related = _resolve_skill_root(c, root_id)
            if slug is None:
                slug = _root_slug(c, related)

        tag_list = [t.strip() for t in (tags or "").split(",") if t.strip()]
        if slug:
            identity = f"skill-{slug}"
            if identity not in tag_list:
                tag_list.append(identity)
        else:
            _emit(
                ["skill has no slug identity tag (ADR-0004 recommends skill-<slug>)"],
                warnings_out,
            )
        merged_tags = ",".join(tag_list) if tag_list else None

        return log_entry(
            agent,
            "skill",
            content,
            related_id=related,
            tags=merged_tags,
            extras=extras,
            conn=c,
            warnings_out=warnings_out,
        )
