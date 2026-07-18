"""Export/import of a node as a portable bundle (ADR-0007 §exports).

An export bundle is a ZIP containing the node's ``journal.db`` (a consolidated
online-backup copy), its ``boonyard.toml`` if present, a ``boonyard-export.json``
manifest, and a README pointing at the OSS package. ``import_bundle`` accepts
**boonyard export bundles only** — this is bundle roundtrip, not legacy migration
(the migration path is deferred entirely, wall entry 95). The no-lock-in promise
is mechanical: the bundle is a zip of a SQLite file (CHARTER).
"""

import json
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from .backup import backup_node
from .db import connect

EXPORT_VERSION = 1
_MANIFEST_NAME = "boonyard-export.json"
_DB_NAME = "journal.db"
_TOML_NAME = "boonyard.toml"
_README = (
    "This is a BoonyardNN export bundle.\n\n"
    "It contains a node's journal.db (a SQLite file), its boonyard.toml profile,\n"
    "and this manifest. The data is plain SQLite — open journal.db with any SQLite\n"
    "tool, or `pip install boonyard` and `boonyard import <this-bundle>.zip`.\n"
    "No lock-in, ever.\n"
)


def _node_meta(db_path: str | Path) -> dict:
    with connect(db_path, read_only=True) as conn:
        return {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM meta")}


def export_bundle(
    dest_path: str | Path,
    *,
    db_path: str | Path,
    profile_path: str | Path | None = None,
    exported_at: str | None = None,
) -> Path:
    """Write a portable ZIP bundle of the node at ``db_path`` to ``dest_path``.

    Includes a consolidated ``journal.db`` (via the online-backup API, so WAL
    state is folded in), the profile if ``profile_path`` exists, a manifest, and a
    README. Returns the bundle path. Pass ``exported_at`` (ISO string) to stamp the
    manifest deterministically; otherwise the current UTC time is used.

    Example:
        export_bundle("boonyard.zip", db_path="node/journal.db",
                      profile_path="node/boonyard.toml")
    """
    dest = Path(dest_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    meta = _node_meta(db_path)
    manifest = {
        "boonyard_export_version": EXPORT_VERSION,
        "schema_version": int(meta.get("schema_version", 3)),
        "node_name": meta.get("node_name"),
        "node_uuid": meta.get("node_uuid"),
        "exported_at": exported_at or datetime.now(UTC).isoformat(timespec="seconds"),
    }

    with tempfile.TemporaryDirectory() as tmp:
        consolidated = Path(tmp) / _DB_NAME
        backup_node(consolidated, db_path=db_path)
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(consolidated, _DB_NAME)
            zf.writestr(_MANIFEST_NAME, json.dumps(manifest, indent=2))
            zf.writestr("README.txt", _README)
            toml = Path(profile_path) if profile_path else None
            if toml is not None and toml.exists():
                zf.write(toml, _TOML_NAME)
    return dest


def import_bundle(
    bundle_path: str | Path,
    dest_db_path: str | Path,
    *,
    overwrite: bool = False,
) -> Path:
    """Restore a boonyard export bundle to ``dest_db_path``. Returns the db path.

    Accepts **only** boonyard export bundles (validated via the manifest); anything
    else raises ``ValueError`` — this is not a general importer, and not a legacy
    migration path. Refuses to clobber an existing destination unless
    ``overwrite=True``. The node's ``boonyard.toml`` is restored beside the db if
    the bundle carried one.

    Example:
        import_bundle("boonyard.zip", "restored/journal.db")
    """
    if not zipfile.is_zipfile(bundle_path):
        raise ValueError(f"{bundle_path} is not a boonyard export bundle (not a zip)")
    with zipfile.ZipFile(bundle_path) as zf:
        names = set(zf.namelist())
        if _MANIFEST_NAME not in names or _DB_NAME not in names:
            raise ValueError(f"{bundle_path} is not a boonyard export bundle")
        manifest = json.loads(zf.read(_MANIFEST_NAME))
        if "boonyard_export_version" not in manifest:
            raise ValueError(f"{bundle_path} is not a boonyard export bundle")

        dest = Path(dest_db_path)
        if dest.exists() and not overwrite:
            raise ValueError(f"destination {dest} already exists; pass overwrite=True")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(zf.read(_DB_NAME))
        if _TOML_NAME in names:
            (dest.parent / _TOML_NAME).write_bytes(zf.read(_TOML_NAME))
    return dest
