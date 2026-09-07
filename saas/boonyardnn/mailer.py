"""The mailer — one function, one provider behind it (boonyard #111, decided #113).

Verification and sign-in links go out by mail; this is the only place the hosted
layer talks to anything outside the box. The provider is AgentMail (Professor's
choice) over its REST API through ``urllib`` — no SDK, no dependency. ``LogMailer``
captures instead of sending (tests, and a dry-run mode for an operator); ``NullMailer``
refuses, so a misconfigured box fails loudly at signup rather than silently.

Nothing here logs an address, a link or a body.
"""

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

AGENTMAIL_BASE = "https://api.agentmail.to"
SENDER_NAME = "Boonyard"


class MailError(RuntimeError):
    """The mail could not be sent (provider refused, network failed, or no provider)."""


class LogMailer:
    """Keeps every message in ``sent`` (and appends JSON lines to ``outbox`` if given).

    Example:
        m = LogMailer(); m.send("a@example.test", "hi", "body"); m.sent[0]["to"]
    """

    def __init__(self, outbox: str | Path | None = None):
        self.sent: list[dict[str, str]] = []
        self.outbox = Path(outbox) if outbox else None

    def send(self, to: str, subject: str, text: str) -> None:
        msg = {"to": to, "subject": subject, "text": text}
        self.sent.append(msg)
        if self.outbox is not None:
            with open(self.outbox, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(msg) + "\n")


class NullMailer:
    """No provider configured: every send raises :class:`MailError`."""

    def send(self, to: str, subject: str, text: str) -> None:
        raise MailError("mail is not configured on this server")


class AgentMailer:
    """AgentMail: ``POST /v0/inboxes/{inbox_id}/messages/send`` with a bearer key.

    Example:
        AgentMailer(api_key, "boonyard@agentmail.to", reply_to="hello@boonyard.com")
    """

    def __init__(
        self,
        api_key: str,
        inbox_id: str,
        *,
        reply_to: str | None = None,
        base_url: str = AGENTMAIL_BASE,
        opener=urllib.request.urlopen,
        timeout: float = 15.0,
    ):
        if not api_key or not inbox_id:
            raise MailError("AgentMail needs an api key and an inbox id")
        self._api_key = api_key
        self.inbox_id = inbox_id
        self.reply_to = reply_to
        self.base_url = base_url.rstrip("/")
        self._opener = opener
        self.timeout = timeout

    def send(self, to: str, subject: str, text: str) -> None:
        payload: dict = {"to": to, "subject": subject, "text": text}
        if self.reply_to:
            payload["reply_to"] = self.reply_to
        req = urllib.request.Request(
            f"{self.base_url}/v0/inboxes/{urllib.request.quote(self.inbox_id)}/messages/send",
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "User-Agent": "boonyardnn",
            },
        )
        try:
            with self._opener(req, timeout=self.timeout) as resp:
                if not 200 <= resp.status < 300:
                    raise MailError(f"AgentMail answered {resp.status}")
        except urllib.error.HTTPError as err:
            raise MailError(f"AgentMail answered {err.code}") from None
        except urllib.error.URLError as err:
            raise MailError(f"AgentMail unreachable: {type(err.reason).__name__}") from None


def mailer_from_env(env=None):
    """Pick the provider from the environment.

    ``BOONYARDNN_MAIL`` = ``agentmail`` (needs ``AGENTMAIL_API_KEY`` + ``AGENTMAIL_INBOX``,
    optional ``AGENTMAIL_REPLY_TO``), ``log`` (optional ``BOONYARDNN_MAIL_OUTBOX`` file),
    or ``none``. Unset: ``agentmail`` when a key is present, else ``none``.

    Example:
        mailer_from_env({"BOONYARDNN_MAIL": "log"})  # -> LogMailer
    """
    env = os.environ if env is None else env
    mode = (env.get("BOONYARDNN_MAIL") or "").strip().lower()
    key = env.get("AGENTMAIL_API_KEY") or ""
    if not mode:
        mode = "agentmail" if key else "none"
    if mode == "agentmail":
        return AgentMailer(
            key,
            env.get("AGENTMAIL_INBOX") or "",
            reply_to=env.get("AGENTMAIL_REPLY_TO") or None,
        )
    if mode == "log":
        return LogMailer(env.get("BOONYARDNN_MAIL_OUTBOX") or None)
    if mode == "none":
        return NullMailer()
    raise MailError(f"unknown BOONYARDNN_MAIL mode {mode!r}")


# --------------------------------------------------------------------------
# The two messages
# --------------------------------------------------------------------------
def verify_mail(link: str, *, slug: str) -> tuple[str, str]:
    """Subject and body of the verification mail.

    Example:
        verify_mail("https://boonyard.com/app/verify?t=…", slug="jacoboon")
    """
    return (
        "Confirm your Boonyard account",
        f'You (or someone using this address) signed up for Boonyard as "{slug}".\n\n'
        f"Confirm the address by opening this link within 24 hours:\n\n  {link}\n\n"
        "If that wasn't you, ignore this mail and nothing happens.\n\n"
        "— Boonyard · https://boonyard.com\n",
    )


def login_mail(link: str) -> tuple[str, str]:
    """Subject and body of the sign-in mail.

    Example:
        login_mail("https://boonyard.com/app/login/link?t=…")
    """
    return (
        "Your Boonyard sign-in link",
        f"Open this link to sign in. It works once and expires in 20 minutes:\n\n  {link}\n\n"
        "If you didn't ask for it, ignore this mail — nobody can use it but you.\n\n"
        "— Boonyard · https://boonyard.com\n",
    )
