"""The mailer: AgentMail over urllib, the log/null providers, and the env selector."""

import contextlib
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path

from boonyardnn.mailer import (
    AgentMailer,
    LogMailer,
    MailError,
    NullMailer,
    login_mail,
    mailer_from_env,
    verify_mail,
)


class _FakeResponse:
    def __init__(self, status: int):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class AgentMailerTests(unittest.TestCase):
    def test_posts_the_documented_shape(self):
        seen = {}

        def opener(req, timeout):
            seen["url"] = req.full_url
            seen["method"] = req.get_method()
            seen["auth"] = req.get_header("Authorization")
            seen["ctype"] = req.get_header("Content-type")
            seen["body"] = json.loads(req.data.decode())
            seen["timeout"] = timeout
            return _FakeResponse(200)

        m = AgentMailer(
            "am_secret", "boonyard@agentmail.to", reply_to="hello@boonyard.com", opener=opener
        )
        m.send("a@example.test", "Subject", "Body\n")
        self.assertEqual(
            seen["url"], "https://api.agentmail.to/v0/inboxes/boonyard%40agentmail.to/messages/send"
        )
        self.assertEqual(seen["method"], "POST")
        self.assertEqual(seen["auth"], "Bearer am_secret")
        self.assertEqual(seen["ctype"], "application/json")
        self.assertEqual(
            seen["body"],
            {
                "to": "a@example.test",
                "subject": "Subject",
                "text": "Body\n",
                "reply_to": "hello@boonyard.com",
            },
        )

    def test_provider_errors_become_mail_error_without_the_body(self):
        def refused(req, timeout):
            raise urllib.error.HTTPError(req.full_url, 401, "nope", {}, io.BytesIO(b"secret"))

        m = AgentMailer("k", "inbox@agentmail.to", opener=refused)
        with self.assertRaises(MailError) as ctx:
            m.send("a@example.test", "s", "t")
        self.assertIn("401", str(ctx.exception))
        self.assertNotIn("secret", str(ctx.exception))

        def down(req, timeout):
            raise urllib.error.URLError(OSError("dns"))

        with self.assertRaises(MailError):
            AgentMailer("k", "inbox@agentmail.to", opener=down).send("a@example.test", "s", "t")

    def test_needs_key_and_inbox(self):
        with self.assertRaises(MailError):
            AgentMailer("", "inbox@agentmail.to")
        with self.assertRaises(MailError):
            AgentMailer("k", "")


class OtherProvidersTests(unittest.TestCase):
    def test_log_mailer_records_and_appends(self):
        with tempfile.TemporaryDirectory() as tmp:
            outbox = Path(tmp) / "outbox.jsonl"
            m = LogMailer(outbox)
            m.send("a@example.test", "s1", "t1")
            m.send("b@example.test", "s2", "t2")
            self.assertEqual([x["to"] for x in m.sent], ["a@example.test", "b@example.test"])
            lines = outbox.read_text(encoding="utf-8").splitlines()
            self.assertEqual(json.loads(lines[1])["subject"], "s2")

    def test_null_mailer_refuses(self):
        with self.assertRaises(MailError):
            NullMailer().send("a@example.test", "s", "t")

    def test_env_selector(self):
        self.assertIsInstance(mailer_from_env({"BOONYARDNN_MAIL": "log"}), LogMailer)
        self.assertIsInstance(mailer_from_env({}), NullMailer)
        self.assertIsInstance(mailer_from_env({"BOONYARDNN_MAIL": "none"}), NullMailer)
        am = mailer_from_env({"AGENTMAIL_API_KEY": "k", "AGENTMAIL_INBOX": "x@agentmail.to"})
        self.assertIsInstance(am, AgentMailer)
        self.assertEqual(am.inbox_id, "x@agentmail.to")
        with self.assertRaises(MailError):
            mailer_from_env({"BOONYARDNN_MAIL": "agentmail"})  # no key
        with self.assertRaises(MailError):
            mailer_from_env({"BOONYARDNN_MAIL": "carrier-pigeon"})


class MessageTests(unittest.TestCase):
    def test_messages_carry_the_link(self):
        subject, text = verify_mail("https://x/app/verify?t=abc", slug="alice")
        self.assertIn("Confirm", subject)
        self.assertIn("https://x/app/verify?t=abc", text)
        self.assertIn("alice", text)
        subject, text = login_mail("https://x/app/login/link?t=abc")
        self.assertIn("sign-in", subject)
        self.assertIn("https://x/app/login/link?t=abc", text)
        self.assertIn("20 minutes", text)

    def test_nothing_is_printed(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            LogMailer().send("a@example.test", "s", "t")
        self.assertEqual(out.getvalue(), "")
