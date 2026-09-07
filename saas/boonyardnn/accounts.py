"""Accounts — signup, verification, sign-in, sessions and the founders counter.

``system/users.db`` under the data root: the file ADR-0007 drew ("email -> user_id,
billing state") with arch 05's session store folded in (one file, two tables,
instead of ``users.db`` + ``sessions.db`` — a dated clarification, not a redesign).
SQLite through the stdlib; no ORM, parameterised SQL only, ``BEGIN IMMEDIATE`` where
a counter must not race (the founder seats).

What is here never contains an entry. Compromise of this file leaks *accounts*,
not *content* (ADR-0007). It never imports ``boonyard`` (``adapter.py`` is the seam).

Sign-in is BOTH ways — Professor's decision, boonyard #113: a magic link mailed to
the address, or a password. Passwords are hashed with ``hashlib.scrypt`` (the
stdlib's slow salted hash; ADR-0007 said "bcrypt", which is the same intent with a
dependency this layer does not need). Magic-link and verification tokens are
random, stored as sha256, single-use and short-lived.

Founders (boonyard #113): the first ``founder_seats`` VERIFIED signups get
``plan='founder'`` and ``founder_until = verified_at + 365 days``, automatically.
The count is what the public counter shows.
"""

import contextlib
import hashlib
import hmac
import os
import secrets
import sqlite3
import threading
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .registry import _mkdir_private, validate_slug

DEFAULT_FOUNDER_SEATS = 20
FOUNDER_TERM = timedelta(days=365)
VERIFY_TTL = timedelta(hours=24)
LOGIN_TTL = timedelta(minutes=20)
SESSION_TTL = timedelta(days=30)
MAIL_LIMIT = 5  # per address per window (boonyard #111)
MAIL_WINDOW = timedelta(hours=1)
IP_LIMIT = 40  # signup/login attempts per client address per window
IP_WINDOW = timedelta(hours=1)
PASSWORD_MIN = 10
PASSWORD_MAX = 256
_PRIVATE_FILE = 0o600

DDL = """
CREATE TABLE IF NOT EXISTS account (
    account_id    TEXT PRIMARY KEY,
    email         TEXT NOT NULL UNIQUE,
    slug          TEXT NOT NULL UNIQUE,
    password_hash TEXT,
    verified_at   TEXT,
    plan          TEXT NOT NULL DEFAULT 'free',
    founder_no    INTEGER UNIQUE,
    founder_until TEXT,
    status        TEXT NOT NULL DEFAULT 'active',
    created_at    TEXT NOT NULL,
    last_login_at TEXT
);
CREATE TABLE IF NOT EXISTS token (
    token_hash TEXT PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES account(account_id),
    kind       TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used_at    TEXT
);
CREATE TABLE IF NOT EXISTS session (
    session_hash TEXT PRIMARY KEY,
    account_id   TEXT NOT NULL REFERENCES account(account_id),
    csrf         TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    expires_at   TEXT NOT NULL,
    last_seen_at TEXT
);
CREATE TABLE IF NOT EXISTS mail_event (
    id      INTEGER PRIMARY KEY,
    email   TEXT NOT NULL,
    kind    TEXT NOT NULL,
    sent_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS mail_event_email ON mail_event(email, sent_at);
CREATE TABLE IF NOT EXISTS request_event (
    id   INTEGER PRIMARY KEY,
    ip   TEXT NOT NULL,
    kind TEXT NOT NULL,
    at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS request_event_ip ON request_event(ip, at);
"""


class AccountError(ValueError):
    """An account operation that cannot proceed (bad email, taken slug, weak password)."""


class TokenError(AccountError):
    """A verification or sign-in token that is unknown, used, expired or the wrong kind."""


@dataclass(frozen=True)
class Account:
    account_id: str
    email: str
    slug: str
    plan: str  # free | founder | owner
    founder_no: int | None
    founder_until: str | None
    verified_at: str | None
    status: str
    created_at: str
    last_login_at: str | None
    has_password: bool

    @property
    def verified(self) -> bool:
        return self.verified_at is not None


# --------------------------------------------------------------------------
# Pure helpers
# --------------------------------------------------------------------------
def normalize_email(email: str) -> str:
    """Trim + lowercase; refuse anything that does not look like ``local@domain.tld``.

    Example:
        normalize_email("  Jacob@Example.TEST ")  # -> "jacob@example.test"
    """
    value = (email or "").strip().lower()
    local, at, domain = value.partition("@")
    if not at or not local or "." not in domain or domain.startswith(".") or len(value) > 254:
        raise AccountError("that does not look like an email address")
    if any(ch.isspace() for ch in value):
        raise AccountError("that does not look like an email address")
    return value


def hash_password(password: str) -> str:
    """``scrypt$<log2 n>$<r>$<p>$<salt hex>$<hash hex>`` — self-describing, so parameters can move.

    Example:
        hash_password("correct horse battery staple").startswith("scrypt$14$8$1$")
    """
    if not isinstance(password, str) or len(password) < PASSWORD_MIN:
        raise AccountError(f"password must be at least {PASSWORD_MIN} characters")
    if len(password) > PASSWORD_MAX:
        raise AccountError(f"password must be at most {PASSWORD_MAX} characters")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=1 << 14, r=8, p=1, dklen=32)
    return f"scrypt$14$8$1${salt.hex()}${digest.hex()}"


def check_password_hash(stored: str | None, password: str) -> bool:
    """Timing-safe verification of ``password`` against a :func:`hash_password` string.

    Example:
        check_password_hash(hash_password("x" * 12), "x" * 12)  # -> True
    """
    if not stored or not isinstance(password, str):
        return False
    try:
        scheme, n_log2, r, p, salt_hex, hash_hex = stored.split("$")
        if scheme != "scrypt":
            return False
        digest = hashlib.scrypt(
            password.encode("utf-8"),
            salt=bytes.fromhex(salt_hex),
            n=1 << int(n_log2),
            r=int(r),
            p=int(p),
            dklen=len(hash_hex) // 2,
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest.hex(), hash_hex)


def _sha256(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat(timespec="seconds")


# --------------------------------------------------------------------------
# The store
# --------------------------------------------------------------------------
class Accounts:
    """The accounts store. One instance per process; safe across the app's threads.

    ``clock`` is injectable so expiry is testable without sleeping.

    Example:
        acc = Accounts("/var/lib/boonyard")
        account, kind, token = acc.begin_signup("jacob@example.test", "jacoboon")
        acc.verify(token)                 # founder #1, if seats remain
        raw, csrf = acc.open_session(account.account_id)
    """

    def __init__(
        self,
        root: str | Path,
        *,
        clock: Callable[[], datetime] | None = None,
        founder_seats: int = DEFAULT_FOUNDER_SEATS,
    ):
        self.root = Path(root)
        self.path = self.root / "system" / "users.db"
        self.founder_seats = founder_seats
        self._clock = clock or (lambda: datetime.now(UTC))
        self._lock = threading.RLock()
        self._init()

    # -- plumbing -------------------------------------------------------------
    def _init(self) -> None:
        _mkdir_private(self.root / "system")
        with self._connect() as conn:
            conn.executescript(DDL)
        try:
            os.chmod(self.path, _PRIVATE_FILE)
        except OSError:
            pass

    @contextlib.contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """A connection that is CLOSED on exit (``sqlite3``'s own context manager only commits)."""
        conn = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA foreign_keys = ON")
            yield conn
        finally:
            conn.close()

    def now(self) -> datetime:
        """The store's idea of now (UTC-aware)."""
        return self._clock().astimezone(UTC)

    @staticmethod
    def _account(row: sqlite3.Row | None) -> Account | None:
        if row is None:
            return None
        return Account(
            account_id=row["account_id"],
            email=row["email"],
            slug=row["slug"],
            plan=row["plan"],
            founder_no=row["founder_no"],
            founder_until=row["founder_until"],
            verified_at=row["verified_at"],
            status=row["status"],
            created_at=row["created_at"],
            last_login_at=row["last_login_at"],
            has_password=row["password_hash"] is not None,
        )

    def _one(self, conn: sqlite3.Connection, sql: str, params: tuple) -> Account | None:
        return self._account(conn.execute(sql, params).fetchone())

    # -- reads ----------------------------------------------------------------
    def get(self, account_id: str) -> Account | None:
        """By id, or None."""
        with self._connect() as conn:
            return self._one(conn, "SELECT * FROM account WHERE account_id = ?", (account_id,))

    def get_by_email(self, email: str) -> Account | None:
        """By (normalised) email, or None. A malformed address is simply None."""
        try:
            email = normalize_email(email)
        except AccountError:
            return None
        with self._connect() as conn:
            return self._one(conn, "SELECT * FROM account WHERE email = ?", (email,))

    def get_by_slug(self, slug: str) -> Account | None:
        """By slug, or None."""
        with self._connect() as conn:
            return self._one(conn, "SELECT * FROM account WHERE slug = ?", (slug,))

    def list_accounts(self) -> list[Account]:
        """Every account, oldest first."""
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM account ORDER BY created_at, slug").fetchall()
        return [self._account(r) for r in rows]

    def founders(self) -> dict[str, int]:
        """``{"seats": 20, "taken": n, "open": 20 - n}`` — the public counter.

        Example:
            acc.founders()  # -> {"seats": 20, "taken": 1, "open": 19}
        """
        with self._connect() as conn:
            taken = conn.execute(
                "SELECT COUNT(*) FROM account WHERE founder_no IS NOT NULL"
            ).fetchone()[0]
        seats = self.founder_seats
        return {"seats": seats, "taken": taken, "open": max(0, seats - taken)}

    # -- tokens ---------------------------------------------------------------
    def _issue(self, conn: sqlite3.Connection, account_id: str, kind: str, ttl: timedelta) -> str:
        raw = secrets.token_urlsafe(32)
        now = self.now()
        conn.execute(
            "INSERT INTO token (token_hash, account_id, kind, created_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (_sha256(raw), account_id, kind, _iso(now), _iso(now + ttl)),
        )
        return raw

    def _consume(self, conn: sqlite3.Connection, raw: str, kind: str) -> str:
        """Mark a token used and return its account id; :class:`TokenError` otherwise."""
        if not raw or len(raw) > 128:
            raise TokenError("that link is not valid")
        row = conn.execute("SELECT * FROM token WHERE token_hash = ?", (_sha256(raw),)).fetchone()
        if row is None or row["kind"] != kind:
            raise TokenError("that link is not valid")
        if row["used_at"] is not None:
            raise TokenError("that link has already been used")
        now = _iso(self.now())
        if row["expires_at"] <= now:
            raise TokenError("that link has expired — request a new one")
        conn.execute("UPDATE token SET used_at = ? WHERE token_hash = ?", (now, row["token_hash"]))
        return row["account_id"]

    # -- signup ---------------------------------------------------------------
    def begin_signup(
        self,
        email: str,
        slug: str,
        password: str | None = None,
        *,
        slug_available: Callable[[str], bool] | None = None,
    ) -> tuple[Account, str, str]:
        """Start a signup. Returns ``(account, kind, raw_token)``.

        ``kind`` is ``"verify"`` for a new or still-unverified address (mail the
        verification link) or ``"login"`` when the address already has a verified
        account (mail a sign-in link instead — the browser is told the same thing
        either way, so nobody can probe which addresses exist).

        ``slug_available`` is consulted for a NEW slug (the web layer passes the
        registry's view, so an account can never claim a directory that exists).

        Example:
            account, kind, token = acc.begin_signup("jacob@example.test", "jacoboon")
        """
        email = normalize_email(email)
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                existing = self._one(conn, "SELECT * FROM account WHERE email = ?", (email,))
                if existing is not None and existing.verified:
                    raw = self._issue(conn, existing.account_id, "login", LOGIN_TTL)
                    conn.execute("COMMIT")
                    return existing, "login", raw
                slug = validate_slug(slug, kind="username")
                taken = self._one(conn, "SELECT * FROM account WHERE slug = ?", (slug,))
                if taken is not None and (
                    existing is None or taken.account_id != existing.account_id
                ):
                    raise AccountError(f"the username {slug!r} is taken")
                if taken is None and slug_available is not None and not slug_available(slug):
                    raise AccountError(f"the username {slug!r} is taken")
                pw_hash = hash_password(password) if password else None
                now = _iso(self.now())
                if existing is None:
                    account_id = str(uuid.uuid4())
                    conn.execute(
                        "INSERT INTO account (account_id, email, slug, password_hash, created_at) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (account_id, email, slug, pw_hash, now),
                    )
                else:
                    # Unverified re-signup: the latest slug/password wins; nothing is lost.
                    account_id = existing.account_id
                    conn.execute(
                        "UPDATE account SET slug = ?, password_hash = COALESCE(?, password_hash) "
                        "WHERE account_id = ?",
                        (slug, pw_hash, account_id),
                    )
                raw = self._issue(conn, account_id, "verify", VERIFY_TTL)
                account = self._one(
                    conn, "SELECT * FROM account WHERE account_id = ?", (account_id,)
                )
            except Exception:
                conn.execute("ROLLBACK")
                raise
            conn.execute("COMMIT")
        return account, "verify", raw

    def verify(self, raw_token: str) -> Account:
        """Consume a verification token; mark verified; take a founder seat if one is open.

        Idempotent for an already-verified account (the token is still single-use).

        Example:
            acc.verify(token).founder_no  # -> 1
        """
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                account_id = self._consume(conn, raw_token, "verify")
                account = self._one(
                    conn, "SELECT * FROM account WHERE account_id = ?", (account_id,)
                )
                if account is not None and not account.verified:
                    now = self.now()
                    taken = conn.execute(
                        "SELECT COUNT(*) FROM account WHERE founder_no IS NOT NULL"
                    ).fetchone()[0]
                    if taken < self.founder_seats:
                        top = conn.execute(
                            "SELECT COALESCE(MAX(founder_no), 0) FROM account"
                        ).fetchone()[0]
                        conn.execute(
                            "UPDATE account SET verified_at = ?, plan = 'founder', "
                            "founder_no = ?, founder_until = ? WHERE account_id = ?",
                            (_iso(now), top + 1, _iso(now + FOUNDER_TERM), account_id),
                        )
                    else:
                        conn.execute(
                            "UPDATE account SET verified_at = ? WHERE account_id = ?",
                            (_iso(now), account_id),
                        )
                    account = self._one(
                        conn, "SELECT * FROM account WHERE account_id = ?", (account_id,)
                    )
            except Exception:
                conn.execute("ROLLBACK")
                raise
            conn.execute("COMMIT")
        return account

    # -- sign-in --------------------------------------------------------------
    def request_login(self, email: str) -> tuple[Account, str] | None:
        """A sign-in token for a VERIFIED account, or None (unknown or unverified).

        The caller mails the link; it tells the browser the same neutral sentence
        either way.

        Example:
            acc.request_login("jacob@example.test")  # -> (Account, "…token…")
        """
        account = self.get_by_email(email)
        if account is None or not account.verified or account.status != "active":
            return None
        with self._lock, self._connect() as conn:
            raw = self._issue(conn, account.account_id, "login", LOGIN_TTL)
        return account, raw

    def consume_login(self, raw_token: str) -> Account:
        """Consume a sign-in token; stamp ``last_login_at``; return the account."""
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                account_id = self._consume(conn, raw_token, "login")
                conn.execute(
                    "UPDATE account SET last_login_at = ? WHERE account_id = ?",
                    (_iso(self.now()), account_id),
                )
                account = self._one(
                    conn, "SELECT * FROM account WHERE account_id = ?", (account_id,)
                )
            except Exception:
                conn.execute("ROLLBACK")
                raise
            conn.execute("COMMIT")
        if account is None or account.status != "active":
            raise TokenError("that account is not active")
        return account

    def login_with_password(self, email: str, password: str) -> Account | None:
        """The account if ``password`` matches and the address is verified; else None.

        An unknown address still costs one scrypt so the two answers take the same time.

        Example:
            acc.login_with_password("jacob@example.test", "…")
        """
        try:
            email = normalize_email(email)
        except AccountError:
            return None
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM account WHERE email = ?", (email,)).fetchone()
        stored = row["password_hash"] if row is not None else None
        ok = check_password_hash(stored or _DUMMY_HASH, password or "")
        if row is None or stored is None or not ok:
            return None
        account = self._account(row)
        if not account.verified or account.status != "active":
            return None
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE account SET last_login_at = ? WHERE account_id = ?",
                (_iso(self.now()), account.account_id),
            )
        return self.get(account.account_id)

    def set_password(self, account_id: str, password: str) -> None:
        """Set or replace the password (the dashboard's account section)."""
        pw_hash = hash_password(password)
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE account SET password_hash = ? WHERE account_id = ?", (pw_hash, account_id)
            )

    # -- sessions -------------------------------------------------------------
    def open_session(self, account_id: str) -> tuple[str, str]:
        """Start a session. Returns ``(raw_session_id, csrf_token)``; only the hash is stored."""
        raw = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(16)
        now = self.now()
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO session (session_hash, account_id, csrf, created_at, expires_at, "
                "last_seen_at) VALUES (?, ?, ?, ?, ?, ?)",
                (_sha256(raw), account_id, csrf, _iso(now), _iso(now + SESSION_TTL), _iso(now)),
            )
        return raw, csrf

    def session(self, raw_session_id: str | None) -> tuple[Account, str] | None:
        """``(account, csrf)`` for a live session cookie, else None."""
        if not raw_session_id or len(raw_session_id) > 128:
            return None
        now = _iso(self.now())
        digest = _sha256(raw_session_id)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT s.csrf, s.expires_at, a.* FROM session s JOIN account a USING (account_id) "
                "WHERE s.session_hash = ?",
                (digest,),
            ).fetchone()
            if row is None or row["expires_at"] <= now:
                return None
            conn.execute(
                "UPDATE session SET last_seen_at = ? WHERE session_hash = ?", (now, digest)
            )
        account = self._account(row)
        if account.status != "active":
            return None
        return account, row["csrf"]

    def close_session(self, raw_session_id: str | None) -> None:
        """End a session (logout). Unknown ids are ignored."""
        if not raw_session_id:
            return
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM session WHERE session_hash = ?", (_sha256(raw_session_id),))

    # -- rate limits ----------------------------------------------------------
    def mail_allowed(self, email: str, kind: str) -> bool:
        """Record one outbound mail to ``email`` if fewer than ``MAIL_LIMIT`` went in the window.

        Example:
            all(acc.mail_allowed("a@example.test", "verify") for _ in range(5))  # -> True
            acc.mail_allowed("a@example.test", "verify")                          # -> False
        """
        email = email.strip().lower()
        now = self.now()
        since = _iso(now - MAIL_WINDOW)
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM mail_event WHERE sent_at <= ?", (since,))
            sent = conn.execute(
                "SELECT COUNT(*) FROM mail_event WHERE email = ? AND sent_at > ?", (email, since)
            ).fetchone()[0]
            if sent >= MAIL_LIMIT:
                return False
            conn.execute(
                "INSERT INTO mail_event (email, kind, sent_at) VALUES (?, ?, ?)",
                (email, kind, _iso(now)),
            )
        return True

    def ip_allowed(self, ip: str, kind: str) -> bool:
        """Record one attempt from ``ip`` if fewer than ``IP_LIMIT`` happened in the window."""
        now = self.now()
        since = _iso(now - IP_WINDOW)
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM request_event WHERE at <= ?", (since,))
            seen = conn.execute(
                "SELECT COUNT(*) FROM request_event WHERE ip = ? AND at > ?", (ip, since)
            ).fetchone()[0]
            if seen >= IP_LIMIT:
                return False
            conn.execute(
                "INSERT INTO request_event (ip, kind, at) VALUES (?, ?, ?)", (ip, kind, _iso(now))
            )
        return True

    # -- operator -------------------------------------------------------------
    def import_user(self, slug: str, email: str, *, plan: str = "owner") -> Account:
        """Register an already-provisioned registry user as a verified account.

        For the accounts that predate the platform (user zero). ``plan='owner'`` is
        not a founder seat and is not counted by the public counter.

        Example:
            acc.import_user("jacoboon", "jacob@example.test")
        """
        email = normalize_email(email)
        slug = validate_slug(slug, kind="username")
        now = _iso(self.now())
        with self._lock, self._connect() as conn:
            if self._one(conn, "SELECT * FROM account WHERE slug = ? OR email = ?", (slug, email)):
                raise AccountError(f"an account for {slug!r} / {email!r} already exists")
            account_id = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO account (account_id, email, slug, verified_at, plan, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (account_id, email, slug, now, plan, now),
            )
        return self.get(account_id)

    def issue_link_token(self, email: str) -> tuple[Account, str, str] | None:
        """Operator escape hatch: ``(account, kind, raw_token)`` for an address, or None.

        ``kind`` is ``"login"`` for a verified account, ``"verify"`` otherwise. For
        the hour the mailer is down; the CLI prints the link, once.
        """
        account = self.get_by_email(email)
        if account is None:
            return None
        kind = "login" if account.verified else "verify"
        ttl = LOGIN_TTL if kind == "login" else VERIFY_TTL
        with self._lock, self._connect() as conn:
            raw = self._issue(conn, account.account_id, kind, ttl)
        return account, kind, raw


# A real hash to burn scrypt time on for unknown addresses (timing parity).
_DUMMY_HASH = hash_password("dummy-password-for-timing-parity")
