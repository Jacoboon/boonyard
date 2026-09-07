# boonyard.com — Privacy Policy (DRAFT)

> **DRAFT 2026-09-07, design seat (Conductor, Cowork). Not legal advice.** Every sentence below is either true today (verified against boonyard #114/#116/#120 and the running `web.py`) or marked with the tier that makes it true. Square brackets mark what must be filled or verified before this is served. Two sentences are given in two versions — **[TODAY]** and **[AFTER TIER 1]** (ADR-0012) — and the page must carry the TODAY version until the Tier 1 sitting is verified live. Never the later version early.
>
> **Blessed by: Professor, 2026-09-07** — *"You can do the legal-ese for now. Blessed."* (umbrella wall, the decision entry threaded to #360). **Brackets that remain are measurement items for the Code seat** — retention numbers read from `accounts.py`, the meter's roll-up, the node-delete grace, DigitalOcean's backup retention read from the panel — not wording that waits on a blessing. Fill each from the running system before the page changes; the [TODAY] sentences stand until ADR-0012 Tier 1 is verified live.

Effective: [date]. This policy covers the hosted service at boonyard.com and mcp.boonyard.com, run by **Mindstorm Unlimited LLC** (Florida, USA). The open-source package phones home to nothing and collects nothing; this policy is about the hosted service only.

## 1. The short version

We store your email, your username, a hash of your password if you set one, and the nodes you create. We read your entries only to answer your own requests. We keep no analytics, no tracking, no advertising, and we never train anything on your data or sell it. You can export everything as a plain SQLite file at any time. The honest sentence: a server that can search your entries can technically read them, and so can the person who runs it. We don't. If that is not good enough for what you are storing, run the same software yourself — it is free, and a self-hosted node never touches our disk.

## 2. What we store, and why

| What | Why | How long |
|---|---|---|
| Email address | sign-in links, verification, account notices | until your account is closed, then scrubbed at the end of the removal window (§7) |
| Username (slug) | your URL: mcp.boonyard.com/*you*/*node* | kept after closure so nobody can take your name and impersonate your old URLs |
| Password | only as a salted, slow hash (scrypt); we cannot read it | until you change it or close the account |
| Sign-in and verification tokens, session cookie | to keep you signed in; stored only as hashes | tokens expire in 24 hours (verification) or 20 minutes (sign-in link); sessions 30 days |
| API keys | to authenticate your agents; stored only as sha256 hashes — we cannot recover a key, which is why we show it once | until you revoke it; the revoked row is kept for your audit |
| **Your entries** — everything you or your agents write into a node | that is the product | until you delete the node or close the account (§7) |
| Your IP address at signup, sign-in and mail-sending | rate limiting, to stop abuse | [retention: read from `accounts.py` and state the number] |
| Operational metrics: which **tool** was called on which node, and when | to keep the service healthy and to show you your own read/write meter | [aggregated; per-event rows rolled up after N days — state the number] — never the query text, never the arguments |
| [If ADR-0013 ships:] the **ids** of entries a read returned | to power your own "unread" and "arc" views | rolled up to counts after 180 days; ids only, never content or query |
| The count of founder seats taken | shown publicly on the site | a number only; never names or emails |

We do not store: payment cards (Stripe holds them if you ever pay), analytics identifiers, advertising identifiers, or anything from a tracking pixel — there are none.

## 3. Cookies

One cookie, `bnys`, when you are signed in. It is HttpOnly, Secure, and SameSite; it identifies your session and nothing else. No third-party cookies, no analytics cookies. Signing out deletes it.

## 4. Who can read your entries

- **You and your agents**, through your keys.
- **The service**, to answer your own requests — search, threads, tags, recent — and for nothing else: not analytics, not training, not curiosity, not "insights."
- **The person who runs it.** Technically yes: the operator has root on the server and the server can read your entries. In practice no, and this policy is the promise. The only things we will ever look at without your request are operational: a known-malicious payload, an abuse report, or a lawful legal demand (§8).
- **Nobody else.** We do not share, sell, or aggregate your content with anyone.

## 5. Email

We send mail from hello@boonyard.com only for: verifying your address, signing you in, telling you something about your account (a limit reached, a founder year ending, a change to these terms), and answering mail you sent us. No newsletters unless you ask for one. Security reports go to security@boonyard.com.

## 6. Where your data lives, and who we rely on

Your node lives on a server we rent from **DigitalOcean** (USA). Traffic reaches it through **Cloudflare**, which terminates HTTPS at its edge — like every site Cloudflare fronts, it sees your requests in plaintext for the instant it takes to forward them. Our email is sent through **AgentMail**. If you ever pay, **Stripe** handles the card. Those four are the only third parties that touch anything of yours, and each sees only what its job needs.

**Encryption.** Everything between you and the server is encrypted in transit.

- **[TODAY]** At rest, the disk your node lives on is not yet encrypted; your files are readable only by the service process, in a directory nobody else on the server can open, and nightly backups stay on the same machine under the same permissions.
- **[AFTER TIER 1]** At rest, your node lives on an encrypted volume, and every nightly backup is encrypted before it is written, with a key that is not kept on the server.

**"Encrypted from you?"** Not on the hosted service — a server that cannot read your entries cannot search them, and searching is what you pay us for. If you need us to be unable to read your data, run the package yourself: same code, your disk, your keys. That is not a workaround; it is the design.

## 7. Deleting things

- **One entry:** cannot be deleted or edited individually — the product is append-only by design, and that is on the front page. Corrections are new entries. [If personal data was logged by mistake, write to hello@boonyard.com and we will redact it by hand and tell you exactly what changed.]
- **One node:** delete it from the dashboard. Its files are removed [after a grace period of ______ days]; backups containing it age out within 30 days.
- **Your account:** close it from the dashboard [or by email until the button exists]. Export first. Your files are removed on the same schedule; your email is scrubbed; your username stays reserved. **[TODAY]** Server backups we do not control (our provider's daily disk backup) may hold a copy for up to 7 days after that. **[AFTER TIER 1]** The same, and every copy that exists is encrypted.

## 8. Legal demands

We do not hand over user data to third parties without lawful process, and we will tell you if we are legally allowed to. We will publish a plain count of such demands if we ever receive one.

## 9. Children

The service is for adults (18+). We do not knowingly keep an account for anyone younger; tell us and we will close it.

## 10. Changes

If this policy changes in a way that matters, we email you at least 14 days before it takes effect. The current version and its date are always at boonyard.com/app/privacy.

## 11. Contact

hello@boonyard.com · security@boonyard.com · Mindstorm Unlimited LLC, Florida, USA.
