"""``system/users.db``: signup, verification, founders, sign-in both ways, sessions, limits."""

import os
import stat
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from boonyardnn.accounts import (
    LOGIN_TTL,
    MAIL_LIMIT,
    VERIFY_TTL,
    AccountError,
    Accounts,
    TokenError,
    check_password_hash,
    hash_password,
    normalize_email,
)
from boonyardnn.registry import SlugError


class Clock:
    """A settable clock for expiry tests."""

    def __init__(self):
        self.now = datetime(2026, 9, 7, 3, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now += delta


class AccountsTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "data"
        self.clock = Clock()
        self.acc = Accounts(self.root, clock=self.clock, founder_seats=2)

    def signup_and_verify(self, email: str, slug: str, password: str | None = None):
        _account, kind, token = self.acc.begin_signup(email, slug, password)
        self.assertEqual(kind, "verify")
        return self.acc.verify(token)


class PureHelperTests(unittest.TestCase):
    def test_normalize_email(self):
        self.assertEqual(normalize_email("  Jacob@Example.TEST "), "jacob@example.test")
        for bad in ("", "nope", "@x.y", "a@b", "a b@c.d", "a@.b"):
            with self.subTest(bad=bad), self.assertRaises(AccountError):
                normalize_email(bad)

    def test_password_hash_round_trip(self):
        stored = hash_password("correct horse battery staple")
        self.assertTrue(stored.startswith("scrypt$14$8$1$"))
        self.assertTrue(check_password_hash(stored, "correct horse battery staple"))
        self.assertFalse(check_password_hash(stored, "correct horse battery stapl"))
        self.assertFalse(check_password_hash(None, "x"))
        self.assertFalse(check_password_hash("garbage", "x"))

    def test_password_length_rules(self):
        with self.assertRaises(AccountError):
            hash_password("short")
        with self.assertRaises(AccountError):
            hash_password("x" * 257)


class SignupTests(AccountsTestCase):
    def test_signup_then_verify_takes_a_founder_seat(self):
        account, kind, token = self.acc.begin_signup("A@Example.test", "alice")
        self.assertEqual(kind, "verify")
        self.assertEqual(account.email, "a@example.test")
        self.assertFalse(account.verified)
        self.assertIsNone(account.founder_no)
        verified = self.acc.verify(token)
        self.assertTrue(verified.verified)
        self.assertEqual(verified.plan, "founder")
        self.assertEqual(verified.founder_no, 1)
        self.assertEqual(verified.founder_until[:10], "2027-09-07")
        self.assertEqual(self.acc.founders(), {"seats": 2, "taken": 1, "open": 1})

    def test_seats_run_out_then_free(self):
        self.signup_and_verify("a@example.test", "alice")
        second = self.signup_and_verify("b@example.test", "bob")
        self.assertEqual(second.founder_no, 2)
        third = self.signup_and_verify("c@example.test", "carol")
        self.assertEqual(third.plan, "free")
        self.assertIsNone(third.founder_no)
        self.assertEqual(self.acc.founders()["open"], 0)

    def test_verify_token_is_single_use(self):
        _account, _kind, token = self.acc.begin_signup("a@example.test", "alice")
        self.acc.verify(token)
        with self.assertRaises(TokenError):
            self.acc.verify(token)

    def test_verify_token_expires(self):
        _account, _kind, token = self.acc.begin_signup("a@example.test", "alice")
        self.clock.advance(VERIFY_TTL + timedelta(seconds=1))
        with self.assertRaises(TokenError):
            self.acc.verify(token)

    def test_unknown_token_and_wrong_kind_refused(self):
        with self.assertRaises(TokenError):
            self.acc.verify("nope")
        self.signup_and_verify("a@example.test", "alice")
        _account, token = self.acc.request_login("a@example.test")
        with self.assertRaises(TokenError):
            self.acc.verify(token)  # a login token is not a verify token

    def test_existing_verified_email_gets_a_login_token_not_a_new_row(self):
        self.signup_and_verify("a@example.test", "alice")
        account, kind, token = self.acc.begin_signup("a@example.test", "someone-else")
        self.assertEqual(kind, "login")
        self.assertEqual(account.slug, "alice")
        self.assertEqual(len(self.acc.list_accounts()), 1)
        self.assertEqual(self.acc.consume_login(token).slug, "alice")

    def test_unverified_resignup_updates_slug_and_reissues(self):
        self.acc.begin_signup("a@example.test", "alice")
        account, kind, token = self.acc.begin_signup("a@example.test", "alicia")
        self.assertEqual(kind, "verify")
        self.assertEqual(account.slug, "alicia")
        self.assertEqual(len(self.acc.list_accounts()), 1)
        self.assertEqual(self.acc.verify(token).slug, "alicia")

    def test_taken_slug_refused(self):
        self.acc.begin_signup("a@example.test", "alice")
        with self.assertRaises(AccountError):
            self.acc.begin_signup("b@example.test", "alice")

    def test_slug_rules_and_registry_view(self):
        with self.assertRaises(SlugError):
            self.acc.begin_signup("a@example.test", "Alice")
        with self.assertRaises(SlugError):
            self.acc.begin_signup("a@example.test", "admin")
        with self.assertRaises(AccountError):
            self.acc.begin_signup("a@example.test", "jacoboon", slug_available=lambda s: False)

    def test_bad_email_refused(self):
        with self.assertRaises(AccountError):
            self.acc.begin_signup("not-an-address", "alice")

    def test_password_at_signup_is_hashed(self):
        account, _kind, _token = self.acc.begin_signup("a@example.test", "alice", "a long password")
        self.assertTrue(account.has_password)
        with self.assertRaises(AccountError):
            self.acc.begin_signup("b@example.test", "bob", "short")


class SignInTests(AccountsTestCase):
    def test_magic_link_round_trip(self):
        self.signup_and_verify("a@example.test", "alice")
        account, token = self.acc.request_login("a@example.test")
        self.assertEqual(account.slug, "alice")
        signed_in = self.acc.consume_login(token)
        self.assertIsNotNone(signed_in.last_login_at)
        with self.assertRaises(TokenError):
            self.acc.consume_login(token)

    def test_login_token_expires(self):
        self.signup_and_verify("a@example.test", "alice")
        _account, token = self.acc.request_login("a@example.test")
        self.clock.advance(LOGIN_TTL + timedelta(seconds=1))
        with self.assertRaises(TokenError):
            self.acc.consume_login(token)

    def test_login_request_for_unknown_or_unverified_is_none(self):
        self.assertIsNone(self.acc.request_login("nobody@example.test"))
        self.acc.begin_signup("u@example.test", "unverified")
        self.assertIsNone(self.acc.request_login("u@example.test"))

    def test_password_sign_in(self):
        self.signup_and_verify("a@example.test", "alice", "a long password")
        self.assertEqual(
            self.acc.login_with_password("A@example.test", "a long password").slug, "alice"
        )
        self.assertIsNone(self.acc.login_with_password("a@example.test", "wrong password!"))
        self.assertIsNone(self.acc.login_with_password("nobody@example.test", "a long password"))

    def test_password_sign_in_needs_verification_and_a_password(self):
        self.acc.begin_signup("u@example.test", "unverified", "a long password")
        self.assertIsNone(self.acc.login_with_password("u@example.test", "a long password"))
        self.signup_and_verify("n@example.test", "nopass")
        self.assertIsNone(self.acc.login_with_password("n@example.test", "a long password"))

    def test_set_password_later(self):
        account = self.signup_and_verify("a@example.test", "alice")
        self.assertFalse(account.has_password)
        self.acc.set_password(account.account_id, "another long password")
        self.assertTrue(self.acc.get(account.account_id).has_password)
        self.assertIsNotNone(
            self.acc.login_with_password("a@example.test", "another long password")
        )


class SessionTests(AccountsTestCase):
    def test_session_round_trip_and_logout(self):
        account = self.signup_and_verify("a@example.test", "alice")
        raw, csrf = self.acc.open_session(account.account_id)
        found, found_csrf = self.acc.session(raw)
        self.assertEqual(found.account_id, account.account_id)
        self.assertEqual(found_csrf, csrf)
        self.acc.close_session(raw)
        self.assertIsNone(self.acc.session(raw))

    def test_session_expires_and_garbage_is_none(self):
        account = self.signup_and_verify("a@example.test", "alice")
        raw, _csrf = self.acc.open_session(account.account_id)
        self.clock.advance(timedelta(days=31))
        self.assertIsNone(self.acc.session(raw))
        self.assertIsNone(self.acc.session(None))
        self.assertIsNone(self.acc.session("x" * 200))


class LimitTests(AccountsTestCase):
    def test_mail_limit_per_address_per_hour(self):
        for _ in range(MAIL_LIMIT):
            self.assertTrue(self.acc.mail_allowed("A@example.test", "verify"))
        self.assertFalse(self.acc.mail_allowed("a@example.test", "verify"))
        self.assertTrue(self.acc.mail_allowed("b@example.test", "verify"))
        self.clock.advance(timedelta(hours=1, seconds=1))
        self.assertTrue(self.acc.mail_allowed("a@example.test", "verify"))

    def test_ip_limit(self):
        for _ in range(40):
            self.assertTrue(self.acc.ip_allowed("203.0.113.9", "signup"))
        self.assertFalse(self.acc.ip_allowed("203.0.113.9", "signup"))
        self.assertTrue(self.acc.ip_allowed("203.0.113.10", "signup"))


class OperatorTests(AccountsTestCase):
    def test_import_owner_is_verified_and_not_a_founder(self):
        account = self.acc.import_user("jacoboon", "jacob@example.test")
        self.assertTrue(account.verified)
        self.assertEqual(account.plan, "owner")
        self.assertIsNone(account.founder_no)
        self.assertEqual(self.acc.founders()["taken"], 0)
        with self.assertRaises(AccountError):
            self.acc.import_user("jacoboon", "other@example.test")
        self.assertIsNotNone(self.acc.request_login("jacob@example.test"))

    def test_issue_link_token(self):
        self.assertIsNone(self.acc.issue_link_token("nobody@example.test"))
        self.acc.begin_signup("a@example.test", "alice")
        _account, kind, token = self.acc.issue_link_token("a@example.test")
        self.assertEqual(kind, "verify")
        self.acc.verify(token)
        _account, kind, token = self.acc.issue_link_token("a@example.test")
        self.assertEqual(kind, "login")
        self.acc.consume_login(token)

    @unittest.skipIf(os.name == "nt", "POSIX modes")
    def test_store_is_private(self):
        self.assertEqual(stat.S_IMODE(os.stat(self.acc.path).st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(self.root / "system").st_mode), 0o700)


class MailSlotTests(AccountsTestCase):
    """A failed send must not spend a real person's quota (launch sweep, 2026-09-08).

    The slot was claimed before the send and never handed back, so five hiccups at the
    mail provider — none of them the user's doing, none of them reaching an inbox —
    locked that address out of signup and sign-in for an hour, behind a page blaming
    them for asking too often.
    """

    def test_a_claim_is_returned_by_undo(self):
        claims = [self.acc.mail_allowed("a@example.test", "verify") for _ in range(5)]
        self.assertTrue(all(claims))
        self.assertFalse(self.acc.mail_allowed("a@example.test", "verify"))  # at the limit
        self.acc.mail_undo(claims[-1])
        self.assertTrue(self.acc.mail_allowed("a@example.test", "verify"), "slot not returned")

    def test_undo_releases_exactly_its_own_row_not_a_neighbours(self):
        first = self.acc.mail_allowed("a@example.test", "verify")
        second = self.acc.mail_allowed("a@example.test", "verify")
        self.acc.mail_undo(first)
        with self.acc._connect() as conn:
            live = [r[0] for r in conn.execute("SELECT id FROM mail_event")]
        self.assertEqual(live, [second])

    def test_undo_of_nothing_is_a_no_op(self):
        self.acc.mail_undo(None)  # the refused path passes None; it must not explode

    def test_five_consecutive_failures_do_not_lock_the_address_out(self):
        """The exact scenario: a provider outage during five signup attempts."""
        for _ in range(5):
            claim = self.acc.mail_allowed("a@example.test", "verify")
            self.assertTrue(claim)
            self.acc.mail_undo(claim)  # the send raised MailError
        self.assertTrue(
            self.acc.mail_allowed("a@example.test", "verify"),
            "an outage must not spend the user's quota",
        )
