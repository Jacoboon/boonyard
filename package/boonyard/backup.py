"""Node backup via SQLite's online-backup API (ADR-0003, ADR-0007).

The backup is a single consolidated ``.db`` file — a consistent snapshot taken
with ``sqlite3.Connection.backup()``, which is atomic and WAL-aware (it captures
committed content without quiescing writers). The node is one file, so the backup
story is one file (ADR-0003 §Backup story is dead simple).
"""

import sqlite3
from pathlib import Path

from .db import connect


def backup_node(dest_path: str | Path, *, db_path: str | Path) -> Path:
    """Write a consistent single-file backup of ``db_path`` to ``dest_path``.

    Uses SQLite's online backup API from a read-only source connection, so the
    source is never modified and the copy folds in any WAL state. Returns the
    destination path.

    Example:
        backup_node("node/journal.db.bak", db_path="node/journal.db")
    """
    dest = Path(dest_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with connect(db_path, read_only=True) as src:
        dst = sqlite3.connect(str(dest))
        try:
            src.backup(dst)
        finally:
            dst.close()
    return dest
