"""Schema and connection management for a boonyard node.

A node is one SQLite file (ADR-0003). This module owns the DDL (the v3 schema,
verbatim from ``docs/architecture/02_schema_design.md`` — the DDL authority),
the ``connect`` context manager, and ``init_db``.

Lineage: the connection/DDL shape descends from PlaneScape's
``_dev/journal/db.py`` (the v1 reference), grown to the v3 canon (FTS5 external
content index, the ``entry_tag`` companion table, ``meta`` and ``meta_log``).
"""

import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from .constants import SCHEMA_VERSION

# =====================================================================
#  BoonyardNN node schema v3 — verbatim from architecture/02_schema_design.md.
#  Idempotent: every CREATE uses IF NOT EXISTS; every bootstrap INSERT is
#  OR IGNORE. The entry column set is CLOSED (ADR-0002): adding a column is a
#  new-ADR decision, never a casual edit here.
# =====================================================================
DDL = """
-- ---- entry: the irreducible row -----------------------------------------
CREATE TABLE IF NOT EXISTS entry (
    id          INTEGER  PRIMARY KEY AUTOINCREMENT,
    timestamp   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    agent       TEXT     NOT NULL,
    entry_type  TEXT     NOT NULL,
    content     TEXT     NOT NULL,
    related_id  INTEGER  REFERENCES entry(id),
    tags        TEXT,
    extras      TEXT  -- JSON; NULL unless the schema profile enables it
);

CREATE INDEX IF NOT EXISTS idx_entry_agent      ON entry(agent);
CREATE INDEX IF NOT EXISTS idx_entry_timestamp  ON entry(timestamp);
CREATE INDEX IF NOT EXISTS idx_entry_type       ON entry(entry_type);
CREATE INDEX IF NOT EXISTS idx_entry_related_id ON entry(related_id);

-- ---- full-text search over content (FTS5, external-content) -------------
CREATE VIRTUAL TABLE IF NOT EXISTS entry_fts USING fts5(
    content,
    content='entry',
    content_rowid='id'
);

CREATE TRIGGER IF NOT EXISTS entry_ai_fts
AFTER INSERT ON entry
BEGIN
    INSERT INTO entry_fts(rowid, content) VALUES (new.id, new.content);
END;

CREATE TRIGGER IF NOT EXISTS entry_ad_fts
AFTER DELETE ON entry  -- ADR-0005: this trigger should effectively never fire
BEGIN
    INSERT INTO entry_fts(entry_fts, rowid, content)
    VALUES ('delete', old.id, old.content);
END;

-- entry_au_fts is intentionally NOT a content-update trigger:
-- the substrate does not edit content. The tags-only retag path
-- (ADR-0005 exception) does not touch FTS-indexed columns.

-- ---- entry_tag: per-(entry, tag) denormalized lookup --------------------
CREATE TABLE IF NOT EXISTS entry_tag (
    entry_id INTEGER NOT NULL REFERENCES entry(id) ON DELETE CASCADE,
    tag      TEXT    NOT NULL,
    PRIMARY KEY (entry_id, tag)
);

CREATE INDEX IF NOT EXISTS idx_entry_tag_tag ON entry_tag(tag);

CREATE TRIGGER IF NOT EXISTS entry_ai_tags
AFTER INSERT ON entry
WHEN new.tags IS NOT NULL AND new.tags != ''
BEGIN
    -- Placeholder no-op. entry_tag population is application-side: log.py calls
    -- _populate_entry_tags(conn, id, tags) in the SAME transaction as the INSERT.
    -- SQLite triggers can't easily loop over a split string, so Python owns it.
    SELECT 1;  -- no-op; see comment above
END;

CREATE TRIGGER IF NOT EXISTS entry_ad_tags
AFTER DELETE ON entry  -- ADR-0005: should effectively never fire
BEGIN
    DELETE FROM entry_tag WHERE entry_id = old.id;
END;

-- ---- meta: schema versioning and node identity --------------------------
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Bootstrap rows; INSERT OR IGNORE makes init_db() idempotent.
-- Note: the NULL placeholders below are intentionally skipped by OR IGNORE
-- (value is NOT NULL); init_db() populates node_uuid/node_name/created_at in
-- Python with real values.
INSERT OR IGNORE INTO meta (key, value) VALUES ('schema_version', '3');
INSERT OR IGNORE INTO meta (key, value) VALUES ('node_uuid', NULL);  -- populated on init
INSERT OR IGNORE INTO meta (key, value) VALUES ('node_name', NULL);  -- from boonyard.toml on init
INSERT OR IGNORE INTO meta (key, value) VALUES ('created_at', NULL); -- populated on init

-- ---- meta_log: append-only log of meta operations -----------------------
CREATE TABLE IF NOT EXISTS meta_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    op         TEXT NOT NULL,         -- 'retag', 'schema_migrate', 'profile_change'
    entry_id   INTEGER,               -- nullable; the row affected, if applicable
    payload    TEXT NOT NULL,         -- JSON: before/after, reason, etc.
    actor      TEXT NOT NULL          -- who did it; usually an agent or 'system'
);

CREATE INDEX IF NOT EXISTS idx_meta_log_timestamp ON meta_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_meta_log_op        ON meta_log(op);
CREATE INDEX IF NOT EXISTS idx_meta_log_entry_id  ON meta_log(entry_id);
"""


def _utc_now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string (seconds precision)."""
    return datetime.now(UTC).isoformat(timespec="seconds")


def _apply_pragmas(conn: sqlite3.Connection, *, read_only: bool = False) -> None:
    """Apply the canonical pragmas (arch 02) and the Row factory to ``conn``.

    Idempotent and safe to call on a caller-supplied connection. Must run before
    any transaction is open (``journal_mode = WAL`` cannot switch mid-transaction).
    """
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")  # writers don't block readers
    conn.execute("PRAGMA foreign_keys = ON")  # enforce REFERENCES entry(id)
    conn.execute("PRAGMA synchronous = NORMAL")  # durable enough; faster than FULL
    if read_only:
        conn.execute("PRAGMA query_only = ON")  # physically incapable of writing


def _open(db_path: str | Path, *, read_only: bool = False) -> sqlite3.Connection:
    """Open a configured raw connection to ``db_path``. Caller must close it."""
    conn = sqlite3.connect(str(db_path))
    _apply_pragmas(conn, read_only=read_only)
    return conn


@contextmanager
def connect(db_path: str | Path, *, read_only: bool = False) -> Iterator[sqlite3.Connection]:
    """Open a node connection, apply pragmas, commit on success, and always close.

    The canonical connection idiom for the package. On a clean exit the
    transaction is committed; on exception it is rolled back; the connection is
    closed either way — connections never leak (CLAUDE.md).

    Args:
        db_path: Path to the node's SQLite file, or ``":memory:"``.
        read_only: If True, add ``PRAGMA query_only = ON`` — the connection
            becomes physically incapable of writing (the aggregator's guarantee).

    Example:
        with connect("node/journal.db") as conn:
            conn.execute("SELECT COUNT(*) FROM entry")
    """
    conn = _open(db_path, read_only=read_only)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _init_schema(conn: sqlite3.Connection, *, node_name: str | None = None) -> None:
    """Run the DDL and populate node-identity meta rows on an open connection."""
    conn.executescript(DDL)
    # The DDL's NULL placeholders for these keys were skipped by OR IGNORE
    # (value is NOT NULL). Populate them with real values, still idempotently.
    conn.execute(
        "INSERT OR IGNORE INTO meta (key, value) VALUES ('node_uuid', ?)",
        (str(uuid.uuid4()),),
    )
    conn.execute(
        "INSERT OR IGNORE INTO meta (key, value) VALUES ('created_at', ?)",
        (_utc_now_iso(),),
    )
    if node_name is not None:
        conn.execute(
            "INSERT OR IGNORE INTO meta (key, value) VALUES ('node_name', ?)",
            (node_name,),
        )


def init_db(
    db_path: str | Path | None = None,
    *,
    conn: sqlite3.Connection | None = None,
    node_name: str | None = None,
) -> None:
    """Create the v3 schema and bootstrap node identity. Idempotent.

    Provide exactly one of ``db_path`` (opened and closed here) or ``conn`` (an
    already-open connection managed by the caller — used by tests and the SaaS
    layer). Re-running against an initialized node is a safe no-op; existing
    identity values are preserved (INSERT OR IGNORE).

    Args:
        db_path: Path to the node file to create/initialize.
        conn: An open connection to initialize in place, instead of ``db_path``.
        node_name: Optional human name recorded in ``meta.node_name``.

    Example:
        init_db("node/journal.db", node_name="boonyard")
    """
    if conn is not None:
        _apply_pragmas(conn)
        _init_schema(conn, node_name=node_name)
        conn.commit()
        return
    if db_path is None:
        raise ValueError("init_db requires either db_path or conn")
    if str(db_path) != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with connect(db_path) as opened:
        _init_schema(opened, node_name=node_name)


def schema_version(conn: sqlite3.Connection) -> int:
    """Return the node's stored schema version (from ``meta``).

    Example:
        with connect("node/journal.db") as conn:
            assert schema_version(conn) == SCHEMA_VERSION
    """
    row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    return int(row["value"]) if row is not None else SCHEMA_VERSION
