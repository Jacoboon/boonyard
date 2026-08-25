"""The meter — countable read/write traffic, in a sidecar (umbrella #228 Layer 3).

A read discipline with no meter is not a discipline. The substrate's own audit
found thirteen documented instances of a seat answering from inference when the
answer was already on a wall, and eight rule-shaped remedies that each have a
later violation. The rules failed for one mechanical reason: **nobody could see
the violation.** A seat that writes twelve entries and runs zero searches looks
exactly like a seat that did its job. This module makes that a number.

Same shape as ADR-0002's Ruling-4 lesson one level up: a kill-date with no reader
is not a control, and a read law nothing counts is not a law.

**SIDECAR, NEVER THE JOURNAL** (house law, umbrella #30 — node = memory,
sidecar = telemetry). Hundreds of telemetry rows per session inside ``entry``
would drown the wall they exist to protect, and ``entry`` is append-only, so the
mistake would be permanent. The meter lives in its own file, ``meter.db``, beside
the node it measures. Nothing here ever touches ``entry``.

**TOOL NAME AND TIMESTAMP ONLY — ARGUMENTS ARE NEVER RECORDED.** A ``search_text``
query can carry a homeowner's name, a case number, a vendor, a person. The ratio
does not need them, and writing them would move PII into a new file for no gain.
Not hashed, not truncated: not logged. ``tests/test_meter.py`` pins this with a
sentinel string and fails if it is ever reintroduced.

**FAIL-SOFT, ALWAYS.** A meter that can break a read is worse than no meter, so
:func:`record` swallows every ``Exception`` and returns a bool instead of raising.
If the file cannot be opened, the read it was measuring still gets served.
"""

import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

from .query import _coerce_today

DEFAULT_METER_FILENAME = "meter.db"

# Deliberately tiny and flat. Four columns answer the whole question; a fifth
# would be an invitation to log something that identifies a person.
DDL = """
CREATE TABLE IF NOT EXISTS meter (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    ts   TEXT NOT NULL,
    tool TEXT NOT NULL,
    node TEXT,
    kind TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_meter_ts   ON meter(ts);
CREATE INDEX IF NOT EXISTS idx_meter_kind ON meter(kind);
"""


def default_meter_path(db_path: str | Path) -> Path:
    """The meter that belongs to the node at ``db_path`` — its sibling ``meter.db``.

    Example:
        default_meter_path("node/journal.db")  # -> Path("node/meter.db")
    """
    return Path(db_path).parent / DEFAULT_METER_FILENAME


def _connect(meter_path: str | Path) -> sqlite3.Connection:
    """Open (creating if needed) the sidecar. Callers handle their own failures."""
    path = Path(meter_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(DDL)
    return conn


def record(
    meter_path: str | Path | None,
    tool: str,
    *,
    node: str | None = None,
    kind: str = "read",
    ts: str | None = None,
) -> bool:
    """Record one tool call. Returns True if it landed, False if it could not.

    **Never raises.** This runs inside the MCP tool path, and a telemetry failure
    must not become a read failure — the same fail-soft discipline as JR Hood's
    conductor-notify hook in the claim path. Every ``Exception`` is swallowed;
    ``KeyboardInterrupt`` and ``SystemExit`` deliberately are not, because a
    shutdown signal is not a bug to hide.

    ``ts`` is a LOCAL wall-clock ISO string, never UTC: "yesterday: 12 writes, 0
    searches" has to mean the human's yesterday, and this stack has been bitten by
    UTC drift twice (umbrella #53, #200).

    Only ``tool``/``node``/``kind`` are stored. Arguments are not accepted by this
    function at all, which is the cheapest way to guarantee they are never logged.

    Example:
        record("node/meter.db", "search_text", node="umbrella", kind="read")
    """
    if meter_path is None:
        return False
    try:
        stamp = ts or datetime.now().isoformat(timespec="seconds")
        conn = _connect(meter_path)
        try:
            conn.execute(
                "INSERT INTO meter (ts, tool, node, kind) VALUES (?, ?, ?, ?)",
                (stamp, tool, node, kind),
            )
            conn.commit()
        finally:
            conn.close()
        return True
    except Exception:  # noqa: BLE001 — a broken meter must never break a read
        return False


def _empty_stats(within_days: int, since: date, until: date, warnings: list[dict]) -> dict:
    return {
        "window_days": within_days,
        "since": since.isoformat(),
        "until": until.isoformat(),
        "totals": {"reads": 0, "writes": 0, "ratio": 0.0},
        "by_tool": {},
        "by_day": [],
        "warnings": warnings,
    }


def collect_rows(
    meter_path: str | Path,
    since: date,
    until: date,
    *,
    source: str | None = None,
) -> tuple[list[dict], dict | None]:
    """Rows in ``[since, until]`` from one meter file -> (rows, warning or None).

    Read-only and fail-soft: an unreadable or absent sidecar yields ``([], warning)``
    rather than raising, so one bad meter cannot take down a stats call across
    several (the ADR-0003 degrade-don't-crash posture, applied to telemetry).
    """
    path = Path(meter_path)
    if not path.exists():
        return [], {
            "kind": "meter_absent",
            "node": source,
            "detail": f"no meter at {path} yet — nothing has been served through it",
        }
    try:
        conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA query_only = ON")
            rows = conn.execute(
                "SELECT ts, tool, node, kind FROM meter "
                "WHERE substr(ts, 1, 10) BETWEEN ? AND ? ORDER BY ts",
                (since.isoformat(), until.isoformat()),
            ).fetchall()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return [], {"kind": "meter_unreadable", "node": source, "detail": f"{path}: {exc}"}
    return [dict(r) for r in rows], None


def summarize(
    rows: list[dict], within_days: int, since: date, until: date, warnings: list[dict]
) -> dict:
    """Fold meter rows into the stats envelope. Pure; no I/O."""
    stats = _empty_stats(within_days, since, until, warnings)
    if not rows:
        return stats

    by_tool: dict[str, int] = {}
    by_day: dict[str, dict] = {}
    reads = writes = 0
    for row in rows:
        tool, kind = row["tool"], row["kind"]
        by_tool[tool] = by_tool.get(tool, 0) + 1
        day = by_day.setdefault(row["ts"][:10], {"date": row["ts"][:10], "reads": 0, "writes": 0})
        if kind == "write":
            writes += 1
            day["writes"] += 1
        else:
            reads += 1
            day["reads"] += 1

    stats["totals"] = {
        "reads": reads,
        "writes": writes,
        # max(writes, 1) so a session of pure reads reports its read count rather
        # than dividing by zero. A ratio below 1 means the wall is being written
        # more than it is being consulted — the failure #228 audited.
        "ratio": round(reads / max(writes, 1), 2),
    }
    stats["by_tool"] = dict(sorted(by_tool.items(), key=lambda kv: (-kv[1], kv[0])))
    stats["by_day"] = [by_day[d] for d in sorted(by_day)]
    return stats


def read_stats(
    within_days: int = 7,
    *,
    today: date | str | None = None,
    meter_path: str | Path | None = None,
) -> dict:
    """How often this node was READ versus WRITTEN, over the last ``within_days``.

    Returns the same envelope shape as ``upcoming_dates``::

        {"window_days": 7, "since": "2026-08-19", "until": "2026-08-25",
         "totals": {"reads": 41, "writes": 12, "ratio": 3.42},
         "by_tool": {"search_text": 18, "recent": 12, "log_entry": 11, ...},
         "by_day": [{"date": "2026-08-25", "reads": 9, "writes": 2}, ...],
         "warnings": []}

    The window is ``within_days`` calendar days **ending today inclusive**, so
    ``within_days=1`` means today only. Days are LOCAL wall-clock (see
    :func:`record`); pin ``today`` to make a test exact.

    ⚠ **ATTRIBUTION LIMIT, STATED RATHER THAN SOLVED.** The bearer key is
    per-NODE, not per-seat, so the server cannot tell the Conductor from the Code
    seat from the morning wave. Writes carry ``agent=`` as a parameter; reads do
    not. **The aggregate ratio is the number that matters** — "yesterday: 12
    writes, 0 searches" is damning no matter who did it. Per-seat attribution
    would mean an optional ``agent`` param on every read tool, which is just
    another rule asking for discipline, and rules are what failed here.

    Note the observer effect: ``read_stats`` is itself a read tool, so checking
    the meter adds one row to it. One row per check, and it is honest to leave it.

    Example:
        read_stats(7, meter_path="node/meter.db")["totals"]["ratio"]
    """
    day = _coerce_today(today)
    since = day - timedelta(days=max(within_days, 1) - 1)
    if meter_path is None:
        return _empty_stats(
            within_days,
            since,
            day,
            [{"kind": "meter_disabled", "node": None, "detail": "no meter path configured"}],
        )
    rows, warning = collect_rows(meter_path, since, day)
    return summarize(rows, within_days, since, day, [warning] if warning else [])
