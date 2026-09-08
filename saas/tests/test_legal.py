"""§4 — the legal pages, served: H2s from the .md, zero '[' in the body, linked from signup."""

import re
import unittest
import urllib.request
from pathlib import Path

from boonyardnn.accounts import Accounts
from boonyardnn.legal import PRIVACY_H2, TERMS_H2
from boonyardnn.legal import PRIVACY_HTML as _PRIVACY
from boonyardnn.legal import TERMS_HTML as _TERMS

from .support import ServedWeb, TmpRoot

DOCS = Path(__file__).resolve().parents[2] / "docs" / "legal"


class LegalTextTests(unittest.TestCase):
    def test_no_bracket_survives_in_either_body(self):
        self.assertNotIn("[", _TERMS)
        self.assertNotIn("[", _PRIVACY)

    def test_h2s_match_the_markdown_source(self):
        for md, h2s, html in (
            ("TERMS_OF_SERVICE_DRAFT.md", TERMS_H2, _TERMS),
            ("PRIVACY_POLICY_DRAFT.md", PRIVACY_H2, _PRIVACY),
        ):
            source = (DOCS / md).read_text(encoding="utf-8")
            in_md = re.findall(r"^## (.+)$", source, flags=re.M)
            self.assertEqual(in_md, h2s, md)
            for h in h2s:
                self.assertIn(f"<h2>{h}</h2>", html, f"{md}: {h}")

    def test_the_resolutions_the_order_named(self):
        TERMS_HTML = " ".join(_TERMS.split())
        PRIVACY_HTML = " ".join(_PRIVACY.split())
        self.assertIn("the limits shown on your dashboard", TERMS_HTML)
        self.assertIn("by email to hello@boonyard.com (a dashboard button is coming)", TERMS_HTML)
        self.assertIn("courts located in Florida.", TERMS_HTML)
        self.assertIn("up to 7 days", PRIVACY_HTML)
        # 2026-09-08: the [TODAY] sentence was retired when Tier 1 went live and the
        # Conductor discharged the fence (umbrella #392). The page had been UNDERSTATING
        # since 17:54 the previous day — the right direction to be wrong in, and still wrong.
        self.assertNotIn("not yet encrypted", PRIVACY_HTML)
        self.assertIn("your node lives on an encrypted volume", PRIVACY_HTML)
        self.assertIn("with a key that is not kept on the server", PRIVACY_HTML)
        # This was the guard against flipping EARLY — the page must never claim encryption
        # it does not have. It is inverted rather than deleted, so the pair still pins the
        # page to exactly one of the two states and never to neither or both.
        self.assertNotIn("is not yet encrypted", PRIVACY_HTML)
        self.assertIn("rolled up to counts after 180 days", PRIVACY_HTML)
        self.assertIn("one hour", PRIVACY_HTML)
        self.assertIn("holding area", PRIVACY_HTML)


class LegalServedTests(unittest.TestCase):
    def setUp(self):
        self._root = TmpRoot().__enter__()
        self.addCleanup(self._root.__exit__, None, None, None)
        self.web = ServedWeb(self._root.registry, Accounts(self._root.root)).__enter__()
        self.addCleanup(self.web.__exit__, None, None, None)

    def test_terms_and_privacy_are_served_without_brackets(self):
        for path, h2s in (("/terms", TERMS_H2), ("/privacy", PRIVACY_H2)):
            status, headers, body = self.web.get(path)
            self.assertEqual(status, 200, path)
            text = body.decode("utf-8")
            self.assertNotIn("[", text, path)  # the WHOLE served body, stylesheet included
            for h in h2s:
                self.assertIn(f"<h2>{h}</h2>", text, f"{path}: {h}")
            self.assertIn('href="/app/terms">terms</a>', text)

    def test_signup_links_both(self):
        status, _h, body = self.web.get("/signup")
        self.assertEqual(status, 200)
        self.assertIn(
            b'By creating an account you agree to the <a href="/app/terms">Terms</a>', body
        )
        self.assertIn(b'<a href="/app/privacy">Privacy Policy</a>', body)
        self.assertNotIn(b'type="checkbox"', body)

    def test_head_works(self):
        req = urllib.request.Request(self.web.url("/terms"), method="HEAD")
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            self.assertEqual(resp.read(), b"")
