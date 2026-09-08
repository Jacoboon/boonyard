"""The web app, served: signup → verify → dashboard → node → key → an MCP call through the
router with that key, in one test — plus every refusal the forms must make."""

import io
import json
import re
import unittest
import urllib.request
import zipfile

from boonyardnn.accounts import Accounts
from boonyardnn.web import COOKIE, PREFIX, Request, WebApp

from .support import ServedRouter, ServedWeb, TmpRoot, payload_of, rpc, tool_call

_KEY_RE = re.compile(rb"bnyk_[0-9a-f]{64}")


class WebTestCase(unittest.TestCase):
    seats = 2

    def setUp(self):
        self._root = TmpRoot().__enter__()
        self.addCleanup(self._root.__exit__, None, None, None)
        self.reg = self._root.registry
        self.acc = Accounts(self._root.root, founder_seats=self.seats)
        self.web = ServedWeb(self.reg, self.acc).__enter__()
        self.addCleanup(self.web.__exit__, None, None, None)

    def signup(self, email="alice@example.test", slug="alice", password=""):
        status, _h, body = self.web.post(
            "/signup", {"email": email, "slug": slug, "password": password}
        )
        self.assertEqual(status, 200, body)
        self.assertIn(b"Check your email", body)
        return self.web.last_link()

    def verify(self, link):
        status, headers, _b = self.web.get(link[link.index(PREFIX) + len(PREFIX) :])
        self.assertEqual(status, 303)
        self.assertIn(COOKIE, self.web.cookies)
        return headers

    def signed_in_user(self, **kw):
        self.verify(self.signup(**kw))
        return self.web.csrf()


class EndToEndTests(WebTestCase):
    def test_signup_verify_node_key_mcp_export(self):
        # signup
        link = self.signup()
        self.assertIn("/verify?t=", link)
        self.assertEqual(self.web.mailer.sent[-1]["to"], "alice@example.test")
        # verify → session cookie → dashboard
        headers = self.verify(link)
        self.assertTrue(headers["Location"].startswith(PREFIX + "/"))
        cookie = [v for k, v in headers.items() if k.lower() == "set-cookie"][0]
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Lax", cookie)
        self.assertNotIn("Secure", cookie)  # secure_cookies=False in tests
        status, _h, body = self.web.get("/")
        self.assertEqual(status, 200)
        self.assertIn(b"alice", body)
        self.assertIn(b"founder #1", body)
        self.assertIsNotNone(self.reg.get_user("alice"))  # the ADR-0007 directory exists
        self.assertEqual(self.acc.founders()["taken"], 1)
        csrf = self.web.csrf()
        # create node
        status, headers, _b = self.web.post("/nodes", {"csrf": csrf, "slug": "n1"})
        self.assertEqual(status, 303)
        self.assertIn("m=node-created", headers["Location"])
        status, _h, body = self.web.get("/?m=node-created")
        self.assertIn(b"Node created", body)
        self.assertIn(b"http://mcp.test/alice/n1", body)
        # mint key — shown once
        status, headers, body = self.web.post("/nodes/n1/keys", {"csrf": csrf, "label": "seat"})
        self.assertEqual(status, 200)
        self.assertEqual(headers["Cache-Control"], "no-store")
        raw = _KEY_RE.search(body).group(0).decode()
        self.assertIn(b"Authorization: Bearer", body)
        status, _h, body = self.web.get("/")
        self.assertNotIn(raw.encode(), body)  # never shown again
        self.assertIn(b"seat", body)
        # the key opens the router door
        with ServedRouter(self.reg) as router:
            status, resp, _h = router.post(
                "/alice/n1",
                tool_call("log_entry", {"agent": "code", "entry_type": "note", "content": "hi"}),
                {"Authorization": f"Bearer {raw}"},
            )
            self.assertEqual(status, 200)
            self.assertEqual(payload_of(resp)["id"], 1)
            # export carries that entry
            status, headers, data = self.web.get("/nodes/n1/export")
            self.assertEqual(status, 200)
            self.assertEqual(headers["Content-Type"], "application/zip")
            self.assertIn("attachment", headers["Content-Disposition"])
            names = zipfile.ZipFile(io.BytesIO(data)).namelist()
            self.assertTrue(any(n.endswith("journal.db") for n in names), names)
            # revoke → 401 at the door
            key_id = re.search(rb"/keys/([0-9a-f-]{36})/revoke", body).group(1).decode()
            status, headers, _b = self.web.post(f"/keys/{key_id}/revoke", {"csrf": csrf})
            self.assertEqual(status, 303)
            status, _r, _h = router.post(
                "/alice/n1", rpc("tools/list"), {"Authorization": f"Bearer {raw}"}
            )
            self.assertEqual(status, 401)
        # founders counter is public
        status, headers, body = self.web.get("/founders.json")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"seats": 2, "taken": 1, "open": 1})
        self.assertIn("max-age", headers["Cache-Control"])

    def test_signin_by_link_after_logout(self):
        csrf = self.signed_in_user()
        status, _h, _b = self.web.post("/logout", {"csrf": csrf})
        self.assertEqual(status, 303)
        self.assertNotIn(COOKIE, self.web.cookies)
        status, _h, _b = self.web.get("/")
        self.assertEqual(status, 303)  # to /login
        status, _h, body = self.web.post(
            "/login", {"email": "alice@example.test", "action": "link", "password": ""}
        )
        self.assertEqual(status, 200)
        link = self.web.last_link()
        self.assertIn("/login/link?t=", link)
        self.verify(link)
        status, _h, body = self.web.get("/")
        self.assertEqual(status, 200)
        self.assertIn(b"alice", body)

    def test_signin_by_password(self):
        csrf = self.signed_in_user(password="a long password")
        self.web.post("/logout", {"csrf": csrf})
        status, _h, body = self.web.post(
            "/login",
            {"email": "alice@example.test", "action": "password", "password": "nope nope nope"},
        )
        self.assertEqual(status, 400)
        self.assertIn(b"Wrong email or password", body)
        self.assertNotIn(COOKIE, self.web.cookies)
        status, _h, _b = self.web.post(
            "/login",
            {"email": "alice@example.test", "action": "password", "password": "a long password"},
        )
        self.assertEqual(status, 303)
        self.assertIn(COOKIE, self.web.cookies)

    def test_set_password_from_dashboard(self):
        csrf = self.signed_in_user()
        status, _h, body = self.web.post("/password", {"csrf": csrf, "password": "short"})
        self.assertEqual(status, 400)
        self.assertIn(b"at least 10", body)
        status, _h, _b = self.web.post("/password", {"csrf": csrf, "password": "long enough now"})
        self.assertEqual(status, 303)
        self.assertIsNotNone(self.acc.login_with_password("alice@example.test", "long enough now"))

    def test_existing_address_signup_mails_a_signin_link_and_says_the_same_thing(self):
        self.signed_in_user()
        self.web.cookies.clear()
        status, _h, body = self.web.post(
            "/signup", {"email": "alice@example.test", "slug": "other", "password": ""}
        )
        self.assertEqual(status, 200)
        self.assertIn(b"Check your email", body)
        self.assertIn("/login/link?t=", self.web.last_link())
        self.assertEqual(len(self.acc.list_accounts()), 1)


class RefusalTests(WebTestCase):
    def test_dashboard_and_actions_need_a_session(self):
        status, headers, _b = self.web.get("/")
        self.assertEqual(status, 303)
        self.assertEqual(headers["Location"], PREFIX + "/login")
        status, _h, _b = self.web.post("/nodes", {"slug": "n1"})
        self.assertEqual(status, 303)
        status, _h, _b = self.web.get("/nodes/n1/export")
        self.assertEqual(status, 303)

    def test_csrf_required(self):
        self.signed_in_user()
        status, _h, body = self.web.post("/nodes", {"csrf": "wrong", "slug": "n1"})
        self.assertEqual(status, 403)
        self.assertEqual(self.reg.list_nodes(self.reg.get_user("alice")), [])

    def test_bad_tokens(self):
        status, _h, body = self.web.get("/verify?t=nope")
        self.assertEqual(status, 400)
        self.assertIn(b"not valid", body)
        status, _h, body = self.web.get("/login/link?t=nope")
        self.assertEqual(status, 400)
        link = self.signup()
        self.verify(link)
        status, _h, body = self.web.get(link[link.index(PREFIX) + len(PREFIX) :])
        self.assertEqual(status, 400)
        self.assertIn(b"already been used", body)

    def test_signup_form_errors(self):
        status, _h, body = self.web.post(
            "/signup", {"email": "not-an-address", "slug": "alice", "password": ""}
        )
        self.assertEqual(status, 400)
        self.assertIn(b"email address", body)
        status, _h, body = self.web.post(
            "/signup", {"email": "a@example.test", "slug": "admin", "password": ""}
        )
        self.assertEqual(status, 400)
        self.assertIn(b"reserved", body)
        self._root.provision("taken", "n1")  # a registry user the accounts table never saw
        status, _h, body = self.web.post(
            "/signup", {"email": "a@example.test", "slug": "taken", "password": ""}
        )
        self.assertEqual(status, 400)
        self.assertIn(b"is taken", body)
        self.assertEqual(self.web.mailer.sent, [])

    def test_node_slug_errors_and_free_cap(self):
        csrf = self.signed_in_user()
        status, _h, body = self.web.post("/nodes", {"csrf": csrf, "slug": "Bad Name"})
        self.assertEqual(status, 400)
        self.web.post("/nodes", {"csrf": csrf, "slug": "n1"})
        status, _h, body = self.web.post("/nodes", {"csrf": csrf, "slug": "n1"})
        self.assertEqual(status, 400)
        self.assertIn(b"taken", body)

    def test_free_plan_holds_three_nodes(self):
        self.acc.founder_seats = 0  # nobody is a founder in this test
        csrf = self.signed_in_user()
        for slug in ("a", "b", "c"):
            status, _h, _b = self.web.post("/nodes", {"csrf": csrf, "slug": slug})
            self.assertEqual(status, 303, slug)
        status, _h, body = self.web.post("/nodes", {"csrf": csrf, "slug": "d"})
        self.assertEqual(status, 400)
        self.assertIn(b"holds 3 nodes", body)

    def test_other_users_keys_and_nodes_are_not_reachable(self):
        raw_bob = self._root.provision("bob", "bn", label="bob-seat")
        user_bob = self.reg.get_user("bob")
        bob_key = self.reg.list_keys(user_bob, self.reg.get_node(user_bob, "bn"))[0]
        csrf = self.signed_in_user()
        status, _h, _b = self.web.post(f"/keys/{bob_key.key_id}/revoke", {"csrf": csrf})
        self.assertEqual(status, 404)
        self.assertIsNotNone(self.reg.authenticate(user_bob, raw_bob))  # still live
        status, _h, _b = self.web.get("/nodes/bn/export")
        self.assertEqual(status, 404)
        status, _h, _b = self.web.post("/nodes/bn/keys", {"csrf": csrf})
        self.assertEqual(status, 404)

    def test_mail_limit_surfaces_as_429(self):
        for _ in range(5):
            self.signup(slug="alice")
        status, _h, body = self.web.post(
            "/signup", {"email": "alice@example.test", "slug": "alice", "password": ""}
        )
        self.assertEqual(status, 429)
        self.assertEqual(len(self.web.mailer.sent), 5)

    def test_mailer_failure_is_503_not_a_trace(self):
        class Broken:
            def send(self, *a):
                from boonyardnn.mailer import MailError

                raise MailError("down")

        self.web.app.mailer = Broken()
        status, _h, body = self.web.post(
            "/signup", {"email": "a@example.test", "slug": "alice", "password": ""}
        )
        self.assertEqual(status, 503)
        self.assertIn(b"could not send", body)
        self.assertNotIn(b"Traceback", body)


class PublicPagesTests(WebTestCase):
    def test_signup_form_shows_the_counter(self):
        status, headers, body = self.web.get("/signup")
        self.assertEqual(status, 200)
        self.assertIn(b"0 of 2 seats taken", body)
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertIn("default-src 'none'", headers["Content-Security-Policy"])

    def test_privacy_health_and_404(self):
        status, _h, body = self.web.get("/privacy")
        self.assertEqual(status, 200)
        self.assertIn(b"can technically read them", body)
        status, _h, body = self.web.get("/health")
        self.assertEqual(json.loads(body)["status"], "ok")
        status, _h, _b = self.web.get("/nope")
        self.assertEqual(status, 404)
        status, headers, _b = self.web.post("/founders.json", {})
        self.assertEqual(status, 404)  # POST is not a route for it

    def test_outside_the_prefix_is_404(self):
        req = urllib.request.Request(f"http://127.0.0.1:{self.web.port}/", method="GET")
        try:
            urllib.request.urlopen(req)
        except urllib.error.HTTPError as err:
            self.assertEqual(err.code, 404)
        else:
            self.fail("expected 404")

    def test_head_sends_headers_without_a_body(self):
        req = urllib.request.Request(self.web.url("/signup"), method="HEAD")
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            self.assertEqual(resp.headers["X-Content-Type-Options"], "nosniff")
            self.assertGreater(int(resp.headers["Content-Length"]), 100)
            self.assertEqual(resp.read(), b"")

    def test_handler_never_logs(self):
        from boonyardnn.web import make_web_handler

        self.assertIsNone(make_web_handler(self.web.app).log_message(None, "x"))


class PureAppTests(unittest.TestCase):
    def test_request_form_parsing_and_method_gates(self):
        with TmpRoot() as root:
            app = WebApp(
                root.registry,
                Accounts(root.root),
                None,
                web_base="https://boonyard.com",
                mcp_base="https://mcp.boonyard.com",
            )
            self.assertTrue(app.secure_cookies)
            req = Request(
                "POST",
                "/signup",
                {},
                {"Content-Type": "application/x-www-form-urlencoded"},
                b"email=a%40b.test&slug=x",
                "127.0.0.1",
            )
            self.assertEqual(req.form, {"email": "a@b.test", "slug": "x"})
            status, headers, _b = app.handle(Request("POST", "/", {}, {}, b"", "127.0.0.1"))
            self.assertEqual(status, 405)
            self.assertIn(("Allow", "GET"), headers)
            status, headers, _b = app.handle(Request("GET", "/logout", {}, {}, b"", "127.0.0.1"))
            self.assertEqual(status, 405)


class AccountDoorInTheDashboardTests(WebTestCase):
    """The landing page's headline promise, reachable from the product (ADR-0014).

    Until 2026-09-08 it was not. `provisioner.add_account_key` had exactly one caller —
    the operator CLI — so the dashboard could only ever show a per-node URL and mint a
    per-node key, while boonyard.com sold "one MCP URL and one key for the whole
    account". A user who improvised and presented a node key at the account door was
    told by the router to "mint an account key", a button that existed nowhere.
    """

    def test_the_dashboard_offers_the_account_door_and_it_actually_works(self):
        self.signed_in_user()
        csrf = self.web.csrf()
        self.web.post("/nodes", {"csrf": csrf, "slug": "n1"})
        self.web.post("/nodes", {"csrf": csrf, "slug": "n2"})

        status, _h, body = self.web.get("/")
        self.assertEqual(status, 200)
        self.assertIn(b"http://mcp.test/alice", body)  # the ACCOUNT door, not a node door
        self.assertIn(b"connector", body)
        self.assertIn(b"Streamable HTTP", body)

        status, headers, body = self.web.post("/keys/account", {"csrf": csrf, "label": "laptop"})
        self.assertEqual(status, 200, body)
        self.assertEqual(headers["Cache-Control"], "no-store")
        raw = _KEY_RE.search(body).group(0).decode()
        # the recipe carries the REAL key, so nothing has to be assembled by hand
        self.assertIn(f"Authorization: Bearer {raw}".encode(), body)

        # ...and it opens EVERY node, which is the whole point
        with ServedRouter(self.reg) as router:
            for node in ("n1", "n2"):
                status, resp, _h = router.post(
                    "/alice",
                    tool_call(
                        "log_entry",
                        {"agent": "code", "entry_type": "note", "content": "hi", "node": node},
                    ),
                    {"Authorization": f"Bearer {raw}"},
                )
                self.assertEqual(status, 200, resp)
                self.assertEqual(payload_of(resp)["source"], node)

    def test_an_account_key_can_be_revoked_from_the_dashboard(self):
        """_owns_key scanned node-scoped keys only, so the most powerful credential the
        product issues had no revoke path at all."""
        self.signed_in_user()
        csrf = self.web.csrf()
        self.web.post("/nodes", {"csrf": csrf, "slug": "n1"})
        _s, _h, body = self.web.post("/keys/account", {"csrf": csrf, "label": "laptop"})
        raw = _KEY_RE.search(body).group(0).decode()

        _s, _h, body = self.web.get("/")
        key_id = re.search(rb"/keys/([0-9a-f-]{36})/revoke", body).group(1).decode()
        status, _h, _b = self.web.post(f"/keys/{key_id}/revoke", {"csrf": csrf})
        self.assertEqual(status, 303)

        with ServedRouter(self.reg) as router:
            status, _r, _h = router.post(
                "/alice", rpc("tools/list"), {"Authorization": f"Bearer {raw}"}
            )
            self.assertEqual(status, 401, "a revoked account key must be refused")

    def test_the_per_node_door_survives_as_the_narrow_tool(self):
        """Demoted behind a disclosure, never deleted: sharing one project is real."""
        self.signed_in_user()
        csrf = self.web.csrf()
        self.web.post("/nodes", {"csrf": csrf, "slug": "n1"})
        _s, _h, body = self.web.get("/")
        self.assertIn(b"<details>", body)
        self.assertIn(b"http://mcp.test/alice/n1", body)
        status, _h, body = self.web.post("/nodes/n1/keys", {"csrf": csrf, "label": "one-project"})
        self.assertEqual(status, 200)
        self.assertIsNotNone(_KEY_RE.search(body))

    def test_a_brand_new_account_is_told_what_to_do(self):
        """The empty state: no nodes, no keys, and the panel still explains itself."""
        self.signed_in_user()
        _s, _h, body = self.web.get("/")
        self.assertIn(b"Nothing is connected yet", body)
        self.assertIn(b"http://mcp.test/alice", body)
