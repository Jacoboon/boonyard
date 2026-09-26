"""The profile editor: a node's boonyard.toml, changed from the dashboard (boonyard #168)."""

import re
import tomllib
import unittest

from boonyardnn import provisioner
from boonyardnn.accounts import Accounts
from boonyardnn.web import PREFIX

from .support import ServedRouter, ServedWeb, TmpRoot, payload_of, tool_call

_SHA_RE = re.compile(rb'name="sha" value="([0-9a-f]{64})"')


class ProfileEditorTests(unittest.TestCase):
    def setUp(self):
        self._root = TmpRoot().__enter__()
        self.addCleanup(self._root.__exit__, None, None, None)
        self.reg = self._root.registry
        self.web = ServedWeb(self.reg, Accounts(self._root.root, founder_seats=2)).__enter__()
        self.addCleanup(self.web.__exit__, None, None, None)
        self.web.post("/signup", {"email": "alice@example.test", "slug": "alice", "password": ""})
        link = self.web.last_link()
        self.web.get(link[link.index(PREFIX) + len(PREFIX) :])
        self.csrf = self.web.csrf()
        self.web.post("/nodes", {"csrf": self.csrf, "slug": "n1"})
        user = self.reg.get_user("alice")
        self.toml = self.reg.node_dir(user, self.reg.get_node(user, "n1")) / "boonyard.toml"

    def _text(self) -> str:
        return self.toml.read_text(encoding="utf-8")

    def _sha(self) -> str:
        _s, _h, body = self.web.get("/nodes/n1/profile")
        return _SHA_RE.search(body).group(1).decode()

    def _allowed_agents_through_the_router(self) -> list[str]:
        raw, _key = provisioner.add_key(self.reg, "alice", "n1")
        with ServedRouter(self.reg) as router:
            _s, resp, _h = router.post(
                "/alice/n1", tool_call("node_info"), {"Authorization": f"Bearer {raw}"}
            )
        return payload_of(resp)["profile"]["allowed_agents"]

    def test_the_page_shows_the_profile_and_is_linked(self):
        status, _h, body = self.web.get("/nodes/n1/profile")
        self.assertEqual(status, 200)
        self.assertIn(b"the implementing seat", body)
        self.assertIn(b"No changes since this node was born", body)
        self.assertIn(b"[node]", body)  # the file itself, in the editor
        for page in ("/", "/nodes/n1"):
            with self.subTest(linked_from=page):
                self.assertIn(b'href="/app/nodes/n1/profile"', self.web.get(page)[2])

    def test_registering_a_seat_is_audited_and_live_on_the_next_call(self):
        before = self._text()
        status, headers, _b = self.web.post(
            "/nodes/n1/profile/seats",
            {"csrf": self.csrf, "seat": "tg-dev", "lane": "the Tea Guru dev seat", "reason": ""},
        )
        self.assertEqual(status, 303)
        self.assertIn("/nodes/n1/profile?m=seat-registered", headers["Location"])
        after = self._text()
        self.assertEqual(tomllib.loads(after)["agents"]["tg-dev"], "the Tea Guru dev seat")
        self.assertTrue(after.startswith(before.split("\n\n[tags")[0]))
        _s, _h, body = self.web.get("/nodes/n1/profile?m=seat-registered")
        self.assertIn(b"Seat registered", body)
        self.assertIn(b"<b>alice</b> \xc2\xb7 register seat tg-dev", body)  # the history row
        self.assertIn(b"+tg-dev = &quot;the Tea Guru dev seat&quot;", body)  # its diff
        # the router builds a server per request, so the connector sees it with no restart
        self.assertIn("tg-dev", self._allowed_agents_through_the_router())

    def test_saving_the_whole_file(self):
        sha = self._sha()
        edited = self._text().replace("[extras]", '[entry_types]\nallowed = ["note"]\n\n[extras]')
        status, headers, _b = self.web.post(
            "/nodes/n1/profile",
            {
                "csrf": self.csrf,
                "sha": sha,
                "toml": edited.replace("\n", "\r\n"),  # what a browser's textarea sends
                "reason": "notes only on this wall",
            },
        )
        self.assertEqual(status, 303)
        self.assertIn("m=profile-saved", headers["Location"])
        self.assertEqual(self.toml.read_bytes(), edited.encode())  # LF on disk, byte for byte
        _s, _h, body = self.web.get("/nodes/n1/profile")
        self.assertIn(b"notes only on this wall", body)
        self.assertIn(b"+allowed = [&quot;note&quot;]", body)

    def test_refusals_change_nothing_and_keep_the_draft(self):
        start = self._text()
        sha = self._sha()
        cases = [
            ({"toml": "[agents\n# my-draft\n", "reason": "x", "sha": sha}, 400, b"not valid"),
            ({"toml": start + "# x\n", "reason": "", "sha": sha}, 400, b"needs a reason"),
            (
                {"toml": start.replace('name = "n1"', 'name = "n2"'), "reason": "x", "sha": sha},
                400,
                b"cannot change",
            ),
            ({"toml": start, "reason": "x", "sha": sha}, 400, b"nothing changed"),
            ({"toml": start + "# x\n", "reason": "x", "sha": "0" * 64}, 409, b"changed after"),
            ({"toml": start + "# x\n", "reason": "x"}, 409, b"changed after"),
        ]
        for form, want_status, want_text in cases:
            with self.subTest(want=want_text):
                status, _h, body = self.web.post("/nodes/n1/profile", {"csrf": self.csrf, **form})
                self.assertEqual(status, want_status)
                self.assertIn(want_text, body)
                if want_text == b"not valid":
                    self.assertIn(b"# my-draft", body)  # the draft survives the refusal
        for seat, lane, want in [
            ("TG-dev", "x", b"lowercase"),
            ("code", "again", b"already registered"),
            ("tg-dev", "", b"needs a lane"),
        ]:
            with self.subTest(seat=seat, lane=lane):
                status, _h, body = self.web.post(
                    "/nodes/n1/profile/seats", {"csrf": self.csrf, "seat": seat, "lane": lane}
                )
                self.assertEqual(status, 400)
                self.assertIn(want, body)
        self.assertEqual(self._text(), start)
        self.assertIn(b"No changes since", self.web.get("/nodes/n1/profile")[2])

    def test_the_doors_are_shut_to_everyone_else(self):
        form = {"seat": "x", "lane": "y"}
        self.assertEqual(self.web.post("/nodes/n1/profile/seats", form)[0], 403)  # no csrf
        self.assertEqual(
            self.web.post("/nodes/n1/profile/seats", {"csrf": "wrong", **form})[0], 403
        )
        self.assertEqual(self.web.get("/nodes/n1/profile/seats")[0], 405)
        self._root.provision("bob", "bn")
        self.assertEqual(self.web.get("/nodes/bn/profile")[0], 404)
        self.assertEqual(
            self.web.post("/nodes/bn/profile/seats", {"csrf": self.csrf, **form})[0], 404
        )
        self.web.cookies.clear()
        self.assertEqual(self.web.get("/nodes/n1/profile")[0], 303)  # signed out
        self.assertNotIn("x", tomllib.loads(self._text())["agents"])


if __name__ == "__main__":
    unittest.main()
