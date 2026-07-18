"""The one audited mutation surface: ``retag_entry`` (ADR-0005's sole exception).

Tags are *index data*, not content — so they may be corrected in place, but only
through this path, which records the before/after/reason as an append-only
``meta_log`` row. There is deliberately no delete, no content-edit, and no MCP
tool for this (arch 06): retag is a CLI/library operation, used with intent.

The entry's ``entry_type`` tag is preserved across a retag (the type-tag mandate,
ADR-0009): even if the caller drops it from ``new_tags``, it is re-added.
"""

import json
import logging
from pathlib import Path
from sqlite3 import Connection

from .db import resolve_conn
from .log import _normalize_tags, _populate_entry_tags

_log = logging.getLogger("boonyard")


def _repopulate_entry_tags(conn: Connection, entry_id: int, tags: list[str]) -> None:
    """Replace all ``entry_tag`` rows for an entry with the given tag set."""
    conn.execute("DELETE FROM entry_tag WHERE entry_id = ?", (entry_id,))
    _populate_entry_tags(conn, entry_id, tags)


def retag_entry(
    entry_id: int,
    new_tags: str | None,
    reason: str,
    actor: str,
    *,
    conn: Connection | None = None,
    db_path: str | Path | None = None,
) -> int:
    """Replace an entry's tags, atomically logging the change to ``meta_log``.

    The only sanctioned way to mutate an existing entry (ADR-0005). The entry's
    ``content``, ``agent``, ``entry_type`` and ``related_id`` are never touched;
    only ``entry.tags`` (and its ``entry_tag`` rows) change. A single ``meta_log``
    row (``op='retag'``) records the before, after, and reason. Returns that
    meta_log row's id.

    Hard-fails (raise ``ValueError``): a non-existent ``entry_id``, an empty
    ``reason``, or an empty ``actor`` — this is an audited operation and the audit
    fields are mandatory.

    Example:
        retag_entry(
            42, "discussion,personality",
            reason="merging plural drift; see the ontology decision",
            actor="cowork", db_path="node/journal.db",
        )
    """
    if not reason or not reason.strip():
        raise ValueError("retag requires a non-empty reason (it is the audit record)")
    if not actor or not actor.strip():
        raise ValueError("retag requires a non-empty actor")

    with resolve_conn(conn, db_path) as c:
        row = c.execute("SELECT entry_type, tags FROM entry WHERE id = ?", (entry_id,)).fetchone()
        if row is None:
            raise ValueError(f"entry {entry_id} does not exist")
        before = row["tags"]
        entry_type = row["entry_type"]

        clean_tags, _ = _normalize_tags(new_tags, entry_type)
        after = ",".join(clean_tags)

        c.execute("UPDATE entry SET tags = ? WHERE id = ?", (after, entry_id))
        _repopulate_entry_tags(c, entry_id, clean_tags)

        payload = json.dumps({"before": before, "after": after, "reason": reason})
        cursor = c.execute(
            "INSERT INTO meta_log (op, entry_id, payload, actor) VALUES ('retag', ?, ?, ?)",
            (entry_id, payload, actor),
        )
        meta_log_id = int(cursor.lastrowid)

    _log.info("retag entry %d by %s: %r -> %r (%s)", entry_id, actor, before, after, reason)
    return meta_log_id
