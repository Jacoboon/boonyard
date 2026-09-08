"""The registry — users, nodes and keys as JSON-per-user files (ADR-0007, arch 05).

One directory per user, one directory per node, keys hashed at rest (ADR-0008).
Storage is exactly what ADR-0007 draws, and nothing more::

    {root}/
        users.json                       <- index: user_slug -> user_id
        users/{user_id}/                 <- mode 0700
            metadata.json                <- User fields + this user's Node records
            api_keys.json                <- ApiKey rows (sha256 only; the raw key is never here)
            nodes/{node_slug}/           <- mode 0700: journal.db, boonyard.toml, backups/
            exports/                     <- export bundles

Design call (b), umbrella #335: JSON files, not SQLAlchemy. Twenty founders are
twenty directories; a deploy order can move the index to SQLite if it ever hurts.

Identity rules (arch 05): ``user_id`` / ``node_id`` / ``key_id`` are opaque UUIDs —
never derived from a slug or an email. ``node_id`` is the journal's own
``meta.node_uuid`` (the provisioner's ``init`` callback returns it), so the registry
and the file agree and a node directory is self-describing.

This module knows nothing about the substrate: it never imports ``boonyard``
(``adapter.py`` is the only seam). Node initialisation is injected as a callback.
"""

import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

# CODE_ORDER_PHASE2_SLICE1 §1.1: 1–40 chars, lowercase/digits/hyphens, no leading or
# trailing hyphen. Hyphens are allowed deliberately (the aggregator's ``_IDENT`` is not
# in slice 1); the shape is also filesystem-safe by construction (no ``.``, no ``/``).
SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,38}[a-z0-9])?$")

# The router's own paths (§1.1's minimum list) plus ``http`` — ADR-0008's second
# transport suffix, which the router treats the same way as ``sse``.
RESERVED_SLUGS: frozenset[str] = frozenset(
    {"_aggregate", "api", "admin", "health", "static", "www", "mcp", "sse", "http"}
)

KEY_PREFIX = "bnyk_"
STORE_VERSION = 1
_PRIVATE_DIR = 0o700
_PRIVATE_FILE = 0o600


class RegistryError(ValueError):
    """A registry operation that cannot proceed (taken slug, missing record, …)."""


class SlugError(RegistryError):
    """A slug that fails the shape rule or names a reserved path."""


class NotFoundError(RegistryError):
    """A user, node or key that does not exist."""


def validate_slug(slug: str, *, kind: str = "slug") -> str:
    """Return ``slug`` if it is well-formed and not reserved; raise :class:`SlugError`.

    No normalisation: ``Jacoboon`` is rejected, not lowercased — a slug is part of
    a URL a founder pastes into a connector dialog, and silent rewriting is how
    two people end up with the same door.

    Example:
        validate_slug("test-0")   # -> "test-0"
        validate_slug("admin")    # SlugError: reserved
    """
    if not isinstance(slug, str) or not SLUG_RE.match(slug):
        raise SlugError(
            f"invalid {kind} {slug!r}: lowercase letters, digits and hyphens only, "
            "1-40 chars, no leading or trailing hyphen"
        )
    if slug in RESERVED_SLUGS:
        raise SlugError(f"{kind} {slug!r} is reserved")
    return slug


def mint_key() -> str:
    """A fresh raw API key: ``bnyk_`` + 64 hex chars (ADR-0008: ``secrets.token_hex(32)``).

    Example:
        mint_key()  # -> "bnyk_3f9a…"  (69 chars)
    """
    return KEY_PREFIX + secrets.token_hex(32)


def hash_key(raw: str) -> str:
    """The at-rest form of a key: hex sha256 of the raw string (ADR-0008).

    Example:
        hash_key("bnyk_…")  # -> 64 hex chars
    """
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value)


# --------------------------------------------------------------------------
# Entities — exactly architecture/05's fields (slice 1 omits the Phase-3-only ones:
# Node.plan_overrides, ApiKey.rate_limit, Team).
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class User:
    user_id: str
    slug: str
    email: str
    plan: str
    created_at: str
    status: str


@dataclass(frozen=True)
class Node:
    node_id: str
    owner_id: str
    slug: str
    created_at: str
    storage_path: str  # relative to the data root, POSIX separators


@dataclass(frozen=True)
class ApiKey:
    key_id: str
    hashed_secret: str
    scope: str  # 'node:{node_id}'
    label: str | None
    created_at: str
    last_used_at: str | None
    revoked_at: str | None


# --------------------------------------------------------------------------
# Private-by-construction file helpers
# --------------------------------------------------------------------------
def _mkdir_private(path: Path) -> None:
    """Create ``path`` (and parents) and set it to 0700. Idempotent."""
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, _PRIVATE_DIR)  # explicit: mkdir's mode is umask-masked


def _write_private(path: Path, payload: dict) -> None:
    """Atomically write JSON to ``path`` with mode 0600 from the first byte.

    Writes to a sibling temp file opened with 0600, then ``os.replace`` — so a
    reader never sees a half-written store and the file is never world-readable,
    not even briefly. On Windows the mode is advisory; the droplet is Linux.
    """
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, _PRIVATE_FILE)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, path)
    os.chmod(path, _PRIVATE_FILE)


def _read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


class Registry:
    """The JSON-per-user store under one data root. Thread-safe within a process.

    Example:
        reg = Registry("/var/lib/boonyard/users-root")
        user = reg.create_user("jacoboon", "jacob@example.test")
        node = reg.create_node(user, "test-0", init=lambda d: adapter.init_node(...))
        raw, key = reg.create_key(user, node, label="code seat")
    """

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.users_dir = self.root / "users"
        self.index_path = self.root / "users.json"
        # One lock for every read-modify-write; the router is threaded and two
        # requests may touch the same api_keys.json (last_used_at) at once.
        self._lock = threading.RLock()

    # -- index ----------------------------------------------------------------
    def _read_index(self) -> dict[str, str]:
        data = _read_json(self.index_path)
        return dict(data.get("users", {})) if data else {}

    def _write_index(self, users: dict[str, str]) -> None:
        _mkdir_private(self.root)
        _write_private(self.index_path, {"version": STORE_VERSION, "users": users})

    # -- per-user files -------------------------------------------------------
    def _meta_path(self, user_id: str) -> Path:
        return self.users_dir / user_id / "metadata.json"

    def _keys_path(self, user_id: str) -> Path:
        return self.users_dir / user_id / "api_keys.json"

    def _read_meta(self, user_id: str) -> dict | None:
        return _read_json(self._meta_path(user_id))

    def _write_meta(self, user_id: str, meta: dict) -> None:
        _write_private(self._meta_path(user_id), meta)

    def _read_keys(self, user_id: str) -> dict:
        return _read_json(self._keys_path(user_id)) or {"version": STORE_VERSION, "keys": []}

    def _write_keys(self, user_id: str, store: dict) -> None:
        _write_private(self._keys_path(user_id), store)

    @staticmethod
    def _user_from_meta(meta: dict) -> User:
        return User(
            user_id=meta["user_id"],
            slug=meta["slug"],
            email=meta["email"],
            plan=meta["plan"],
            created_at=meta["created_at"],
            status=meta["status"],
        )

    @staticmethod
    def _node_from_meta(owner_id: str, slug: str, rec: dict) -> Node:
        return Node(
            node_id=rec["node_id"],
            owner_id=owner_id,
            slug=slug,
            created_at=rec["created_at"],
            storage_path=rec["storage_path"],
        )

    # -- users ----------------------------------------------------------------
    def create_user(self, slug: str, email: str) -> User:
        """Create ``users/{user_id}/`` (0700) with its two stores; refuse a taken slug.

        Example:
            reg.create_user("jacoboon", "jacob@example.test").plan  # -> "free"
        """
        slug = validate_slug(slug, kind="user slug")
        if not email or "@" not in email:
            raise RegistryError(f"email {email!r} does not look like an address")
        with self._lock:
            index = self._read_index()
            if slug in index:
                raise RegistryError(f"user slug {slug!r} is taken")
            user = User(
                user_id=str(uuid.uuid4()),
                slug=slug,
                email=email,
                plan="free",
                created_at=_now(),
                status="active",
            )
            udir = self.users_dir / user.user_id
            _mkdir_private(udir)
            _mkdir_private(udir / "nodes")
            _mkdir_private(udir / "exports")
            self._write_meta(user.user_id, {"version": STORE_VERSION, **asdict(user), "nodes": {}})
            self._write_keys(user.user_id, {"version": STORE_VERSION, "keys": []})
            index[slug] = user.user_id
            self._write_index(index)
        return user

    def get_user(self, slug: str) -> User | None:
        """The user with this slug, or None (also None for a malformed slug).

        Example:
            reg.get_user("nobody")  # -> None
        """
        try:
            slug = validate_slug(slug, kind="user slug")
        except SlugError:
            return None
        user_id = self._read_index().get(slug)
        if user_id is None:
            return None
        meta = self._read_meta(user_id)
        return None if meta is None else self._user_from_meta(meta)

    def list_users(self) -> list[User]:
        """Every user, sorted by slug.

        Example:
            [u.slug for u in reg.list_users()]
        """
        users = []
        for slug in sorted(self._read_index()):
            user = self.get_user(slug)
            if user is not None:
                users.append(user)
        return users

    def user_dir(self, user: User) -> Path:
        """``{root}/users/{user_id}``."""
        return self.users_dir / user.user_id

    def set_plan(self, user: User, plan: str) -> User:
        """Record the user's plan (``free`` / ``founder`` / ``owner`` …) in ``metadata.json``.

        The accounts store decides the plan; this mirror lets the router read the
        tier for rate limits and caps without opening ``users.db``.

        Example:
            reg.set_plan(user, "founder").plan  # -> "founder"
        """
        if not isinstance(plan, str) or not plan or len(plan) > 32 or not plan.isidentifier():
            raise RegistryError(f"plan {plan!r} is not a plan name")
        with self._lock:
            meta = self._read_meta(user.user_id)
            if meta is None:
                raise NotFoundError(f"no user with id {user.user_id!r}")
            meta["plan"] = plan
            self._write_meta(user.user_id, meta)
        return self._user_from_meta(meta)

    def all_nodes(self) -> list[tuple[User, Node]]:
        """Every ``(user, node)`` pair in the registry, sorted by user slug then node slug.

        What the backup config is generated from: a new founder's node is covered
        the night it is created, with no config edit anywhere.
        """
        pairs = []
        for user in self.list_users():
            for node in self.list_nodes(user):
                pairs.append((user, node))
        return pairs

    # -- nodes ----------------------------------------------------------------
    def create_node(self, user: User, slug: str, *, init: Callable[[Path], str]) -> Node:
        """Create ``nodes/{slug}/`` (0700) + ``backups/``, run ``init``, record the node.

        ``init(node_dir)`` must create the node's files and return its ``node_id``
        (the provisioner passes the adapter's ``init_node``, which returns the
        journal's own uuid). The record is written only after ``init`` succeeds.

        Example:
            reg.create_node(user, "test-0", init=lambda d: adapter.init_node(
                d / "journal.db", node_name="test-0"))
        """
        slug = validate_slug(slug, kind="node slug")
        with self._lock:
            meta = self._read_meta(user.user_id)
            if meta is None:
                raise NotFoundError(f"no user with id {user.user_id!r}")
            if slug in meta["nodes"]:
                raise RegistryError(f"node slug {slug!r} is taken for user {user.slug!r}")
            ndir = self.user_dir(user) / "nodes" / slug
            if ndir.exists():
                raise RegistryError(f"{ndir} already exists but is not registered")
            _mkdir_private(ndir)
            _mkdir_private(ndir / "backups")
            node_id = init(ndir)
            node = Node(
                node_id=node_id,
                owner_id=user.user_id,
                slug=slug,
                created_at=_now(),
                storage_path=ndir.relative_to(self.root).as_posix(),
            )
            meta["nodes"][slug] = {
                "node_id": node.node_id,
                "created_at": node.created_at,
                "storage_path": node.storage_path,
            }
            self._write_meta(user.user_id, meta)
        return node

    def get_node(self, user: User, slug: str) -> Node | None:
        """The user's node with this slug, or None.

        Example:
            reg.get_node(user, "test-0")
        """
        try:
            slug = validate_slug(slug, kind="node slug")
        except SlugError:
            return None
        meta = self._read_meta(user.user_id)
        if meta is None or slug not in meta["nodes"]:
            return None
        return self._node_from_meta(user.user_id, slug, meta["nodes"][slug])

    def list_nodes(self, user: User) -> list[Node]:
        """The user's nodes, sorted by slug."""
        meta = self._read_meta(user.user_id) or {"nodes": {}}
        return [
            self._node_from_meta(user.user_id, slug, meta["nodes"][slug])
            for slug in sorted(meta["nodes"])
        ]

    def node_dir(self, user: User, node: Node) -> Path:
        """The node's directory (``journal.db``, ``boonyard.toml``, ``backups/`` live here)."""
        return self.root / node.storage_path

    def remove_node(self, user: User, node: Node) -> Path:
        """Tombstone a node: move its directory aside, drop its record, revoke its keys.

        Nothing is destroyed. The directory lands under
        ``{root}/.tombstoned/{user_id}/{stamp}-{slug}/`` (0700), which is arch 05's
        grace shape for deletion: a purge is a separate, later, human decision. Every
        key scoped to the node is revoked so no seat can keep writing to a file that
        the dashboard says is gone. Returns the tombstone path.

        Example:
            reg.remove_node(user, node)  # -> …/.tombstoned/<id>/20260907T050000Z-n1
        """
        with self._lock:
            meta = self._read_meta(user.user_id)
            if meta is None or node.slug not in meta["nodes"]:
                raise NotFoundError(f"no node {node.slug!r} for user {user.slug!r}")
            src = self.node_dir(user, node)
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            grave = self.root / ".tombstoned" / user.user_id
            _mkdir_private(self.root / ".tombstoned")
            _mkdir_private(grave)
            dest = grave / f"{stamp}-{node.slug}"
            if src.exists():
                os.replace(src, dest)
            else:
                _mkdir_private(dest)
            del meta["nodes"][node.slug]
            self._write_meta(user.user_id, meta)
            store = self._read_keys(user.user_id)
            now = _now()
            scope = f"node:{node.node_id}"
            for row in store["keys"]:
                if row["scope"] == scope and row["revoked_at"] is None:
                    row["revoked_at"] = now
            self._write_keys(user.user_id, store)
        return dest

    # -- keys -----------------------------------------------------------------
    def create_key(self, user: User, node: Node, *, label: str | None = None) -> tuple[str, ApiKey]:
        """Mint a key scoped to ``node``; store its hash; return ``(raw, record)``.

        The raw string exists in memory here and in the caller's hands; it is
        never written anywhere (``test_raw_key_appears_nowhere_under_the_root``).

        Example:
            raw, key = reg.create_key(user, node, label="code seat")
        """
        raw = mint_key()
        key = ApiKey(
            key_id=str(uuid.uuid4()),
            hashed_secret=hash_key(raw),
            scope=f"node:{node.node_id}",
            label=label,
            created_at=_now(),
            last_used_at=None,
            revoked_at=None,
        )
        with self._lock:
            store = self._read_keys(user.user_id)
            store["keys"].append(asdict(key))
            self._write_keys(user.user_id, store)
        return raw, key

    def account_scope(self, user: User) -> str:
        """The scope string an account-wide key carries (ADR-0014 §2)."""
        return f"user:{user.user_id}"

    def create_account_key(self, user: User, *, label: str | None = None) -> tuple[str, ApiKey]:
        """Mint a key scoped to the whole ACCOUNT — every node, present and future.

        Same storage as a node key (``bnyk_`` prefix, sha256 at rest, raw returned
        once, revocable): only the scope differs, which is why this is a new value in
        an existing field and not a schema change (ADR-0008 anticipated
        ``aggregator:{ids}``).

        ⚠ Revoking one of these cuts access to EVERY node at once — a feature when a
        laptop is lost, a risk when a finger slips (ADR-0014 §8). Whoever mints one is
        expected to say so where it is minted.

        Example:
            raw, key = reg.create_account_key(user, label="laptop")
        """
        raw = mint_key()
        key = ApiKey(
            key_id=str(uuid.uuid4()),
            hashed_secret=hash_key(raw),
            scope=self.account_scope(user),
            label=label,
            created_at=_now(),
            last_used_at=None,
            revoked_at=None,
        )
        with self._lock:
            store = self._read_keys(user.user_id)
            store["keys"].append(asdict(key))
            self._write_keys(user.user_id, store)
        return raw, key

    def list_account_keys(self, user: User) -> list[ApiKey]:
        """Every account-scoped key of ``user`` (live and revoked), oldest first."""
        scope = self.account_scope(user)
        return [
            ApiKey(**row) for row in self._read_keys(user.user_id)["keys"] if row["scope"] == scope
        ]

    def authenticate(self, user: User, presented: str | None) -> ApiKey | None:
        """The live key of ``user`` matching ``presented``, or None.

        Compares ``sha256(presented)`` to every stored hash with
        ``hmac.compare_digest`` (no early exit), then discards revoked rows. Only
        this user's file is consulted — another user's key is simply unknown at
        this door, which is ADR-0007's isolation clause in one line.

        Example:
            reg.authenticate(user, "bnyk_…")  # -> ApiKey or None
        """
        if not presented:
            return None
        digest = hash_key(presented)
        found: ApiKey | None = None
        for row in self._read_keys(user.user_id)["keys"]:
            if hmac.compare_digest(row["hashed_secret"], digest) and row["revoked_at"] is None:
                found = ApiKey(**row)
        return found

    def touch_key(
        self, user: User, key_id: str, *, now: str | None = None, min_interval_s: int = 60
    ) -> bool:
        """Record ``last_used_at`` for a key, coarsely. Returns True if it wrote.

        Skips the write when the stored stamp is younger than ``min_interval_s``,
        so a chatty seat does not rewrite the store on every call — this is the
        hygiene column of arch 05 ("you have stale keys"), not an audit log.

        Example:
            reg.touch_key(user, key.key_id)
        """
        stamp = now or _now()
        with self._lock:
            store = self._read_keys(user.user_id)
            for row in store["keys"]:
                if row["key_id"] != key_id:
                    continue
                last = row["last_used_at"]
                if last is not None:
                    age = (_parse_ts(stamp) - _parse_ts(last)).total_seconds()
                    if 0 <= age < min_interval_s:
                        return False
                row["last_used_at"] = stamp
                self._write_keys(user.user_id, store)
                return True
        return False

    def revoke_key(self, key_id: str) -> ApiKey:
        """Revoke a key by id (searching every user). The row stays, for audit.

        Idempotent: a second revoke returns the row with its original
        ``revoked_at``. Raises :class:`NotFoundError` for an unknown id.

        Example:
            reg.revoke_key("2f1c…").revoked_at  # -> "2026-09-06T21:00:00+00:00"
        """
        with self._lock:
            for user_id in self._read_index().values():
                store = self._read_keys(user_id)
                for row in store["keys"]:
                    if row["key_id"] == key_id:
                        if row["revoked_at"] is None:
                            row["revoked_at"] = _now()
                            self._write_keys(user_id, store)
                        return ApiKey(**row)
        raise NotFoundError(f"no key with id {key_id!r}")

    def list_keys(self, user: User, node: Node) -> list[ApiKey]:
        """Every key (live and revoked) scoped to ``node``, oldest first.

        Callers print labels and dates; the hash is in the record but the CLI
        never shows it.
        """
        scope = f"node:{node.node_id}"
        return [
            ApiKey(**row) for row in self._read_keys(user.user_id)["keys"] if row["scope"] == scope
        ]

    # -- health ---------------------------------------------------------------
    def counts(self) -> dict[str, int]:
        """``{"users": n, "nodes": m}`` — what ``/health`` reports. No slugs.

        Example:
            reg.counts()  # -> {"users": 2, "nodes": 3}
        """
        index = self._read_index()
        nodes = 0
        for user_id in index.values():
            meta = self._read_meta(user_id)
            nodes += len(meta["nodes"]) if meta else 0
        return {"users": len(index), "nodes": nodes}
