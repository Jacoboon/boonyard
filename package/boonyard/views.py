"""Derived views (ADR-0013): queries over tables that already exist, never declarations.

3.3.0 ships the first one, ``ghosts`` — the orphan sweep, derived. A ghost is a root
entry (no ``related_id``) that nobody threaded to (no child) and nobody read (no
``read_hit`` in the window). It asks no seat to tag anything; it reads the structure
seats already produce and the heat the meter already records. The dated half of the
sweep stays where it is (``upcoming_dates(prefix="open")``, umbrella #234); this is the
undated half #234 left open.

Arcs (3.4.0) and the panel (3.5.0) will live here too.
"""

from datetime import date, timedelta
from pathlib import Path
from sqlite3 import Connection

from . import meter
from .db import resolve_conn
from .query import _coerce_today

FIRST_LINE_CHARS = 120


def _first_line(content: str) -> str:
    line = (content or "").strip().splitlines()[0] if (content or "").strip() else ""
    return line if len(line) <= FIRST_LINE_CHARS else line[: FIRST_LINE_CHARS - 1].rstrip() + "…"


def ghosts(
    limit: int = 20,
    older_than_days: int = 30,
    *,
    today: date | str | None = None,
    conn: Connection | None = None,
    db_path: str | Path | None = None,
    meter_path: str | Path | None = None,
) -> list[dict]:
    """Root entries with no children and no reads in the window, coldest first.

    A row is a ghost when all of: ``related_id IS NULL``; ``entry_type != 'meta'``
    (retag receipts are not ghosts); no entry has ``related_id = id``; the entry is
    older than ``older_than_days`` (a young root has not had its chance yet); and the
    meter holds no read of it newer than the window. Ranked by fewest reads, then
    oldest. Each row: ``id, timestamp, agent, entry_type, first_line, tags, reads,
    last_read``.

    Day one caveat (ADR-0013): heat starts empty the day the sidecar lands, so at
    first this is the *unthreaded* count; it becomes a read-heat count only after
    seats have been reading through the meter for a while.

    Example:
        ghosts(10, 30, db_path="node/journal.db", meter_path="node/meter.db")
    """
    day = _coerce_today(today)
    cutoff = (day - timedelta(days=max(int(older_than_days), 0))).isoformat()
    with resolve_conn(conn, db_path, read_only=True) as c:
        rows = c.execute(
            "SELECT e.id, e.timestamp, e.agent, e.entry_type, e.content, e.tags FROM entry e "
            "WHERE e.related_id IS NULL AND e.entry_type != 'meta' "
            "  AND substr(e.timestamp, 1, 10) < :cutoff "
            "  AND NOT EXISTS (SELECT 1 FROM entry k WHERE k.related_id = e.id) "
            "ORDER BY e.id",
            {"cutoff": cutoff},
        ).fetchall()
    if not rows:
        return []
    ids = [r["id"] for r in rows]
    heat = meter.entry_heat(meter_path, entry_ids=ids) if meter_path is not None else {}
    out = []
    for r in rows:
        h = heat.get(r["id"], {"reads": 0, "last_read": None})
        last = h.get("last_read")
        if last is not None and last[:10] >= cutoff:
            continue  # read inside the window: not a ghost
        out.append(
            {
                "id": r["id"],
                "timestamp": r["timestamp"],
                "agent": r["agent"],
                "entry_type": r["entry_type"],
                "first_line": _first_line(r["content"]),
                "tags": r["tags"].split(",") if r["tags"] else [],
                "reads": int(h.get("reads") or 0),
                "last_read": last,
            }
        )
    out.sort(key=lambda g: (g["reads"], g["timestamp"], g["id"]))
    return out[: max(int(limit), 0)]
