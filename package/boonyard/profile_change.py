"""The audited profile write: ``change_profile`` (``meta_log`` op ``profile_change``).

A node's ``boonyard.toml`` is its advisory contract — the seat registry, the entry
types, the tag namespaces (ADR-0002 §Layer 4). It lives *beside* the node file, not
in it, so an edit by hand leaves no trace anywhere. This module is the sanctioned
edit: the new text is validated before it lands, the swap is atomic, and one
append-only ``meta_log`` row (``op='profile_change'``, named in arch 02's DDL since
the schema was written) records the before, the after and the reason — the same
shape ``retag_entry`` gives an entry's tags.

Like retag, this is a library operation and deliberately NOT an MCP tool: the
profile says which agents a node knows, and an agent that could rewrite it could
register itself through the very door the profile governs. The hosted dashboard
calls it for a signed-in human (boonyard #168).
"""

import copy
import hashlib
import json
import logging
import os
import re
import tempfile
import tomllib
from pathlib import Path
from sqlite3 import Connection

from .db import resolve_conn
from .profile import Profile, profile_from_dict

_log = logging.getLogger("boonyard")

#: A profile is a few hundred bytes; this bounds what the audit row carries.
MAX_PROFILE_BYTES = 32 * 1024

_SEAT = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
_MAX_LANE = 200
_TABLE_HEADER = re.compile(r"^\s*\[")
_AGENTS_HEADER = re.compile(r"^\s*\[\s*agents\s*\]\s*(#.*)?$")
_KEY_LINE = re.compile(r"""^\s*[A-Za-z0-9_"'-]""")


class ProfileConflict(ValueError):
    """The profile changed after the caller read it; nothing was written."""


def profile_sha256(text: str) -> str:
    """The fingerprint a caller reads a profile at, and hands back to change it.

    Example:
        profile_sha256("")  # -> "e3b0c442…" (an absent profile reads as "")
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_profile_text(profile_path: str | Path) -> str:
    """The profile's text, or ``""`` when the node has none (defaults apply).

    Example:
        text = read_profile_text("node/boonyard.toml")
        sha = profile_sha256(text)  # pass to change_profile(expected_sha256=sha)
    """
    p = Path(profile_path)
    return p.read_text(encoding="utf-8") if p.exists() else ""


def validate_profile_text(text: str, *, current: str = "") -> Profile:
    """Parse ``text`` as a profile, or raise ``ValueError`` saying why not.

    The rules: at most ``MAX_PROFILE_BYTES``; valid TOML; a shape
    :func:`~boonyard.profile.profile_from_dict` can build; and ``[node]`` equal to
    ``current``'s, because the node's name and schema version were fixed at birth.
    Unknown tables and keys are allowed — the profile is advisory (ADR-0002).

    Example:
        validate_profile_text('[agents]\\ncode = "builds"\\n').allowed_agents
        # -> frozenset({"code"})
    """
    if len(text.encode("utf-8")) > MAX_PROFILE_BYTES:
        raise ValueError(f"a profile is at most {MAX_PROFILE_BYTES} bytes")
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"not valid TOML: {exc}") from exc
    try:
        profile = profile_from_dict(data)
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError(f"not a profile boonyard can read: {exc}") from exc
    old_node = _loads_or_empty(current).get("node")
    if old_node is not None and data.get("node") != old_node:
        raise ValueError("[node] is the node's identity (name, schema_version) and cannot change")
    return profile


def _loads_or_empty(text: str) -> dict:
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return {}  # a broken current file must not block the edit that repairs it


def _atomic_write(path: Path, text: str) -> None:
    """Write ``text`` beside ``path`` and swap it in, keeping the old file's mode."""
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".boonyard.toml.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _restore(path: Path, text: str, existed: bool) -> None:
    if existed:
        _atomic_write(path, text)
    else:
        path.unlink(missing_ok=True)


def change_profile(
    profile_path: str | Path,
    new_text: str,
    reason: str,
    actor: str,
    *,
    expected_sha256: str | None = None,
    conn: Connection | None = None,
    db_path: str | Path | None = None,
) -> int:
    """Replace a node's ``boonyard.toml``, atomically logging it to ``meta_log``.

    Returns the ``meta_log`` row's id. The row (``op='profile_change'``) carries the
    before and after text, their sha256s, the reason and the actor. The file and the
    row land together: the node's write lock is held across the swap, and if the row
    cannot be committed the old file is put back.

    ``expected_sha256`` is the fingerprint the caller read the profile at (see
    :func:`profile_sha256`). When given, a profile that has changed since is refused
    with :class:`ProfileConflict` rather than silently overwritten.

    Hard-fails (``ValueError``): an empty ``reason`` or ``actor``; text that fails
    :func:`validate_profile_text`; text identical to the current profile. Nothing is
    written on any refusal.

    With ``conn=`` the caller owns the transaction (as everywhere in the package):
    the file is swapped before the caller commits, so commit it.

    Example:
        text = read_profile_text("node/boonyard.toml")
        change_profile(
            "node/boonyard.toml", text + 'tg-dev = "the Tea Guru dev seat"\\n',
            reason="register the Tea Guru dev seat", actor="jacoboon",
            expected_sha256=profile_sha256(text), db_path="node/journal.db",
        )
    """
    if not reason or not reason.strip():
        raise ValueError("a profile change requires a non-empty reason (it is the audit record)")
    if not actor or not actor.strip():
        raise ValueError("a profile change requires a non-empty actor")
    path = Path(profile_path)
    wrote = False
    existed = path.exists()
    before = ""
    try:
        with resolve_conn(conn, db_path) as c:
            if conn is None:
                # Take the write lock BEFORE reading the file, so two editors are
                # serialised and the sha check below cannot be raced.
                c.execute("BEGIN IMMEDIATE")
            existed = path.exists()
            before = read_profile_text(path)
            if expected_sha256 is not None and profile_sha256(before) != expected_sha256:
                raise ProfileConflict("the profile changed after it was read; reload and retry")
            if new_text == before:
                raise ValueError("nothing changed")
            validate_profile_text(new_text, current=before)
            payload = json.dumps(
                {
                    "before": before,
                    "after": new_text,
                    "sha256_before": profile_sha256(before),
                    "sha256_after": profile_sha256(new_text),
                    "reason": reason,
                }
            )
            cursor = c.execute(
                "INSERT INTO meta_log (op, entry_id, payload, actor) "
                "VALUES ('profile_change', NULL, ?, ?)",
                (payload, actor),
            )
            meta_log_id = int(cursor.lastrowid)
            _atomic_write(path, new_text)
            wrote = True
    except BaseException:
        if wrote:
            _restore(path, before, existed)
        raise
    _log.info("profile change on %s by %s (%s)", path, actor, reason)
    return meta_log_id


def profile_history(
    *,
    conn: Connection | None = None,
    db_path: str | Path | None = None,
    limit: int = 20,
) -> list[dict]:
    """The node's profile changes, newest first, each with its decoded payload.

    Every row has ``id``, ``timestamp``, ``actor``, ``reason``, ``before``,
    ``after``, ``sha256_before`` and ``sha256_after``.

    Example:
        profile_history(db_path="node/journal.db", limit=5)[0]["reason"]
    """
    with resolve_conn(conn, db_path, read_only=True) as c:
        rows = c.execute(
            "SELECT id, timestamp, actor, payload FROM meta_log "
            "WHERE op = 'profile_change' ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [
        {"id": r["id"], "timestamp": r["timestamp"], "actor": r["actor"]} | json.loads(r["payload"])
        for r in rows
    ]


def _toml_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def add_seat(text: str, seat: str, lane: str) -> str:
    """Return ``text`` with ``seat = "lane"`` registered under ``[agents]``.

    Everything else in the file is kept byte for byte: the line goes after the last
    key in ``[agents]`` (or a new ``[agents]`` table is appended). The result is
    re-parsed and must equal the old profile plus exactly this one seat, so a file
    shaped in a way this cannot place safely is refused, never mangled.

    Hard-fails (``ValueError``): a seat name that is not lowercase letters, digits,
    ``-`` or ``_`` (at most 40); a lane with a line break or over 200 characters; a
    seat already registered; a profile that lists seats as ``allowed = [...]``.

    Example:
        add_seat('[agents]\\ncode = "builds"\\n', "tg-dev", "the Tea Guru dev seat")
        # -> '[agents]\\ncode = "builds"\\ntg-dev = "the Tea Guru dev seat"\\n'
    """
    if not _SEAT.match(seat):
        raise ValueError(
            "a seat name is lowercase letters, digits, '-' or '_', starting with a letter "
            "or digit, at most 40 characters"
        )
    lane = lane.strip()
    if not lane:
        raise ValueError("a seat needs a lane: one line saying what it does")
    if len(lane) > _MAX_LANE or any(ord(ch) < 32 or ord(ch) == 127 for ch in lane):
        raise ValueError(f"a lane is one line of at most {_MAX_LANE} characters")
    try:
        old = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"the current profile is not valid TOML: {exc}") from exc
    agents = old.get("agents", {})
    if not isinstance(agents, dict):
        raise ValueError("[agents] is not a table; edit the TOML directly")
    if "allowed" in agents:
        raise ValueError("this profile lists its seats as allowed = [...]; edit the TOML directly")
    if seat in agents:
        raise ValueError(f"seat {seat!r} is already registered")

    line = f"{seat} = {_toml_string(lane)}\n"
    lines = text.splitlines(keepends=True)
    header = next((i for i, ln in enumerate(lines) if _AGENTS_HEADER.match(ln)), None)
    if header is None:
        sep = "" if not text or text.endswith("\n\n") else ("\n" if text.endswith("\n") else "\n\n")
        new_text = f"{text}{sep}[agents]\n{line}"
    else:
        end = next(
            (i for i in range(header + 1, len(lines)) if _TABLE_HEADER.match(lines[i])),
            len(lines),
        )
        at = header + 1
        for i in range(header + 1, end):
            if _KEY_LINE.match(lines[i]):
                at = i + 1
        if at > 0 and not lines[at - 1].endswith("\n"):
            lines[at - 1] += "\n"
        lines.insert(at, line)
        new_text = "".join(lines)

    expected = copy.deepcopy(old)
    expected.setdefault("agents", {})[seat] = lane
    try:
        placed = tomllib.loads(new_text) == expected
    except tomllib.TOMLDecodeError:
        placed = False
    if not placed:
        raise ValueError("could not place the seat safely in this file; edit the TOML directly")
    return new_text
