"""The Terms of Service and Privacy Policy, served at ``/app/terms`` and ``/app/privacy``.

Hand-converted from ``docs/legal/TERMS_OF_SERVICE_DRAFT.md`` and
``docs/legal/PRIVACY_POLICY_DRAFT.md`` — the ``.md`` files are the source of truth and the
H2 headings here are theirs, verbatim. Blessed by Professor 2026-09-07 (umbrella #361)
as legal-ese-for-now, not lawyer-reviewed.

Every square bracket in the drafts was a measurement, resolved here from the running
system (CODE_ORDER_SOFT_LAUNCH_WAVE_0907 §4), and ``tests/test_legal.py`` greps the served
bodies for ``[`` so an unresolved one can never ship. The at-rest sentences are the
[TODAY] versions; the [AFTER TIER 1] versions arrive with ADR-0012, not before.
"""

EFFECTIVE = "2026-09-07"

TERMS_HTML = f"""
<p class="muted">Effective {EFFECTIVE}. Not lawyer-reviewed; written in plain English from
what the service actually does.</p>
<p>These terms are between you and <b>Mindstorm Unlimited LLC</b>, a Florida limited liability
company ("we", "us"), for the hosted service at boonyard.com and mcp.boonyard.com (the
"Service"). The open-source <code>boonyard</code> package is separate: it is licensed under
Apache 2.0 and these terms do not apply to running it yourself.</p>

<h2>1. The short version</h2>
<p>You own what you write. We host it, back it up, and serve it to your agents. We do not
read it except to answer your own requests, and we say so plainly in the Privacy Policy. You
can export everything, at any time, for free, as an ordinary SQLite file. Entries are
append-only by design: they cannot be edited or deleted one at a time. If you leave, your
data leaves with you.</p>

<h2>2. Your account</h2>
<ul>
<li>You must be 18 or older and able to enter a contract.</li>
<li>One person per account. Keep your sign-in credentials and API keys to yourself; anything
done with a valid key is done by you, so revoke a key the moment you think it has leaked (the
dashboard does it instantly).</li>
<li>You give us a working email address. We use it to sign you in, to verify you, and to tell
you about your account, and for nothing else (Privacy Policy §5).</li>
</ul>

<h2>3. Your nodes and your entries</h2>
<ul>
<li><b>You own your content.</b> Everything you or your agents write into a node is yours. We
claim no rights in it beyond what is needed to store it and serve it back to you.</li>
<li><b>Append-only.</b> The Service is built so that an entry, once written, is not edited or
deleted individually: by you, by us, or by anyone. Corrections are new entries threaded to the
old. This is a feature of the product, not a limitation we are working on. If a personal detail
is logged by mistake and must be removed, write to hello@boonyard.com; we will handle it by
hand, and we will tell you exactly what was changed.</li>
<li><b>You can delete a whole node</b>, and <b>you can close your account</b>; both remove your
files from our systems on the schedule in Privacy Policy §7.</li>
<li><b>Export is always free</b>, on every plan, in every account state, including a suspended
one.</li>
</ul>

<h2>4. Acceptable use</h2>
<p>Do not use the Service to store or distribute content that is illegal where you or we are,
to command or control malware, to attack the Service or anyone else, or to harass. Do not try
to read another account's data or circumvent limits. We may scan for known-malicious payloads
for operational protection only (Privacy Policy §4); we do not otherwise inspect content. If an
account is abusive we may suspend it; you can still export.</p>

<h2>5. Plans, limits, and founders</h2>
<ul>
<li><b>Free</b> accounts get the limits shown on your dashboard: today 3 nodes, 10,000 entries
per node, and rate limits on API keys. When a limit is reached, new writes are refused; nothing
you already wrote is ever deleted to make room.</li>
<li><b>Founders.</b> The first twenty verified accounts are founders: a year of the paid plan's
limits at no charge, no card required, from the date of verification, and <b>half price on the
paid plan for as long as you stay subscribed after that</b>. The founder number on your account
is permanent.</li>
<li><b>Pro</b> is a paid plan with higher limits: <b>$8 a month or $80 a year</b> at launch.
The checkout page is authoritative for the current price; there are no hidden fees.</li>
</ul>

<h2>6. Payment (applies only once billing exists)</h2>
<ul>
<li>Payments are handled by Stripe. We never see or store your card.</li>
<li>Subscriptions renew until you cancel from the billing page; cancellation takes effect at
the end of the current period.</li>
<li><b>Refunds:</b> the first charge on any subscription is refundable in full on request
within 14 days, no questions asked; after that, cancellation takes effect at the end of the
period you paid for and partial periods are not refunded.</li>
<li>If a payment fails, your paid limits continue for 7 days while Stripe retries; after that
your account moves to Free limits. Nothing is deleted.</li>
<li>Moving from Pro to Free never deletes anything. If you are over Free limits, writes pause
until you upgrade, export, or delete a node yourself. After 30 days over-limit with no action,
the account is suspended, with no writes and no API, until resolved; export still works.</li>
</ul>

<h2>7. Availability</h2>
<p>This is a small service run by a small company, during a soft launch. We work to keep it up
and we back it up every night, but we make <b>no uptime guarantee</b> on Free or founder
accounts, and no service-level agreement on Pro until one is published. We will announce
planned downtime by email or on boonyard.com when we can.</p>

<h2>8. Ending things</h2>
<ul>
<li><b>You</b> can close your account at any time by email to hello@boonyard.com (a dashboard
button is coming). Export first; the schedule for removal is in Privacy Policy §7.</li>
<li><b>We</b> can suspend or close an account for breach of §4, for non-payment under §6, or if
we shut the Service down, in which case we will give at least 30 days' notice and keep export
working through the notice period.</li>
</ul>

<h2>9. Warranties and liability</h2>
<p>The Service is provided <b>"as is."</b> To the extent the law allows, we disclaim implied
warranties, and our total liability to you for anything arising from the Service is limited to
the amount you paid us in the twelve months before the claim (which, on a Free or founder
account, is zero). We are not liable for indirect or consequential loss. Nothing here limits
liability that cannot be limited by law.</p>

<h2>10. Changes</h2>
<p>We may change these terms. If a change matters, we will email you at least 14 days before it
takes effect; continuing to use the Service after that is acceptance. The current version is
always at boonyard.com/app/terms with its effective date.</p>

<h2>11. Law and contact</h2>
<p>These terms are governed by the laws of the State of Florida, USA, and any dispute is brought
in the state or federal courts located in Florida. Questions: hello@boonyard.com. Security
reports: security@boonyard.com.</p>
"""

PRIVACY_HTML = f"""
<p class="muted">Effective {EFFECTIVE}. Every sentence below is true of the service as it runs
today. The at-rest sentences were updated on 2026-09-08, when encrypted storage went live and
was verified: they now describe more protection than they did, not less.</p>
<p>This policy covers the hosted service at boonyard.com and mcp.boonyard.com, run by
<b>Mindstorm Unlimited LLC</b> (Florida, USA). The open-source package phones home to nothing
and collects nothing; this policy is about the hosted service only.</p>

<h2>1. The short version</h2>
<p>We store your email, your username, a hash of your password if you set one, and the nodes
you create. We read your entries only to answer your own requests. We keep no analytics, no
tracking, no advertising, and we never train anything on your data or sell it. You can export
everything as a plain SQLite file at any time. The honest sentence: a server that can search
your entries can technically read them, and so can the person who runs it. We don't. If that is
not good enough for what you are storing, run the same software yourself: it is free, and a
self-hosted node never touches our disk.</p>

<h2>2. What we store, and why</h2>
<table>
<tr><th>What</th><th>Why</th><th>How long</th></tr>
<tr><td>Email address</td><td>sign-in links, verification, account notices</td>
<td>until your account is closed, then scrubbed at the end of the removal window (§7)</td></tr>
<tr><td>Username (slug)</td><td>your URL: mcp.boonyard.com/<i>you</i>/<i>node</i></td>
<td>kept after closure so nobody can take your name and impersonate your old URLs</td></tr>
<tr><td>Password</td><td>only as a salted, slow hash (scrypt); we cannot read it</td>
<td>until you change it or close the account</td></tr>
<tr><td>Sign-in and verification tokens, session cookie</td>
<td>to keep you signed in; stored only as hashes</td>
<td>tokens expire in 24 hours (verification) or 20 minutes (sign-in link);
sessions 30 days</td></tr>
<tr><td>API keys</td><td>to authenticate your agents; stored only as sha256 hashes. We cannot
recover a key, which is why we show it once</td>
<td>until you revoke it; the revoked row is kept for your audit</td></tr>
<tr><td><b>Your entries</b>, everything you or your agents write into a node</td>
<td>that is the product</td><td>until you delete the node or close the account (§7)</td></tr>
<tr><td>Your IP address at signup, sign-in and mail-sending</td><td>rate limiting, to stop
abuse</td><td>one hour; the row is deleted at the next signup or sign-in attempt after
that</td></tr>
<tr><td>Operational metrics: which <b>tool</b> was called on which node, and when</td>
<td>to keep the service healthy and to show you your own read/write meter</td>
<td>kept for as long as the node exists: tool name, node and timestamp only; never the query
text, never the arguments</td></tr>
<tr><td>The <b>ids</b> of entries a read returned</td>
<td>to power your own "unread" and "arc" views</td>
<td>rolled up to counts after 180 days; ids only, never content or query</td></tr>
<tr><td>The count of founder seats taken</td><td>shown publicly on the site</td>
<td>a number only; never names or emails</td></tr>
</table>
<p>We do not store: payment cards (Stripe holds them if you ever pay), analytics identifiers,
advertising identifiers, or anything from a tracking pixel. There are none.</p>

<h2>3. Cookies</h2>
<p>One cookie, <code>bnys</code>, when you are signed in. It is HttpOnly, Secure, and SameSite;
it identifies your session and nothing else. No third-party cookies, no analytics cookies.
Signing out deletes it.</p>

<h2>4. Who can read your entries</h2>
<ul>
<li><b>You and your agents</b>, through your keys.</li>
<li><b>The service</b>, to answer your own requests (search, threads, tags, recent) and for
nothing else: not analytics, not training, not curiosity, not "insights."</li>
<li><b>The person who runs it.</b> Technically yes: the operator has root on the server and
the server can read your entries. In practice no, and this policy is the promise. The only
things we will ever look at without your request are operational: a known-malicious payload,
an abuse report, or a lawful legal demand (§8).</li>
<li><b>Nobody else.</b> We do not share, sell, or aggregate your content with anyone.</li>
</ul>

<h2>5. Email</h2>
<p>We send mail from hello@boonyard.com only for: verifying your address, signing you in,
telling you something about your account (a limit reached, a founder year ending, a change to
these terms), and answering mail you sent us. No newsletters unless you ask for one. Security
reports go to security@boonyard.com.</p>

<h2>6. Where your data lives, and who we rely on</h2>
<p>Your node lives on a server we rent from <b>DigitalOcean</b> (USA). Traffic reaches it
through <b>Cloudflare</b>, which terminates HTTPS at its edge; like every site Cloudflare
fronts, it sees your requests in plaintext for the instant it takes to forward them. Our email
is sent through <b>AgentMail</b>. If you ever pay, <b>Stripe</b> handles the card. Those four are
the only third parties that touch anything of yours, and each sees only what its job needs.</p>
<p><b>Encryption.</b> Everything between you and the server is encrypted in transit.
At rest, your node lives on an encrypted volume, and every nightly backup is encrypted
before it is written, with a key that is not kept on the server. Your files are readable
only by the service process, in a directory nobody else on the server can open.</p>
<p><b>"Encrypted from you?"</b> Not on the hosted service. A server that cannot read your
entries cannot search them, and searching is what you pay us for. If you need us to be unable
to read your data, run the package yourself: same code, your disk, your keys. That is not a
workaround; it is the design.</p>

<h2>7. Deleting things</h2>
<ul>
<li><b>One entry:</b> cannot be deleted or edited individually. The product is append-only by
design, and that is on the front page. Corrections are new entries. If personal data was logged
by mistake, write to hello@boonyard.com and we will redact it by hand and tell you exactly what
changed.</li>
<li><b>One node:</b> delete it from the dashboard. Its files move to a holding area the same
minute and are removed when we purge that area by hand; our own nightly backups stop including
it at once, and the last copy rotates out within 7 days.</li>
<li><b>Your account:</b> close it by email to hello@boonyard.com (a dashboard button is coming).
Export first. Your files are removed on the same schedule; your email is scrubbed; your username
stays reserved. Server backups we do not control (our provider's daily disk backup) may hold a
copy for up to 7 days after that.</li>
</ul>

<h2>8. Legal demands</h2>
<p>We do not hand over user data to third parties without lawful process, and we will tell you
if we are legally allowed to. We will publish a plain count of such demands if we ever receive
one.</p>

<h2>9. Children</h2>
<p>The service is for adults (18+). We do not knowingly keep an account for anyone younger;
tell us and we will close it.</p>

<h2>10. Changes</h2>
<p>If this policy changes in a way that matters, we email you at least 14 days before it takes
effect. The current version and its date are always at boonyard.com/app/privacy.</p>

<h2>11. Contact</h2>
<p>hello@boonyard.com · security@boonyard.com · Mindstorm Unlimited LLC, Florida, USA.</p>
"""

TERMS_H2 = [
    "1. The short version",
    "2. Your account",
    "3. Your nodes and your entries",
    "4. Acceptable use",
    "5. Plans, limits, and founders",
    "6. Payment (applies only once billing exists)",
    "7. Availability",
    "8. Ending things",
    "9. Warranties and liability",
    "10. Changes",
    "11. Law and contact",
]

PRIVACY_H2 = [
    "1. The short version",
    "2. What we store, and why",
    "3. Cookies",
    "4. Who can read your entries",
    "5. Email",
    "6. Where your data lives, and who we rely on",
    "7. Deleting things",
    "8. Legal demands",
    "9. Children",
    "10. Changes",
    "11. Contact",
]
