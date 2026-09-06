# landing/index.html — copy revisions proposed 2026-09-06 (Conductor; BLESSED by Professor 2026-09-06 ~17:00 EDT with one amendment — no waitlist line; Code seat to commit)

The page still says **"pre-phase-1 — package extraction is next"** and **"github (link coming with the phase-1 release)"**. Both were true on 17 July and are false now: the package has been public under Apache-2.0 since 2026-08-25 (boonyard #81), v3.2.0 was tagged today (umbrella #326), and the six live nodes have served from a DigitalOcean droplet since this morning (umbrella #319). Everything below is a replacement for the `status` block and the footer only. Nothing above "status" needs to change — it is still exactly what the thing is.

## status  (replace the four bullets)

● **v3.2.0 — open source, Apache 2.0.** `pip install` it, vendor it, or read it: github.com/Jacoboon/boonyard. Stdlib only, 277 tests, 22 CLI commands, 18 MCP tools.
● **Six live nodes since July 2026**, written to daily by human and AI seats across the author's projects — the substrate is dogfooded before it is sold.
● **Hosted service: not yet.** The design canon (charter, 10 ADRs, 9 architecture docs) is complete and public in the repo; the first hosted user will be the author.

## two ways to run it  (new block, after "no lock-in, ever")

**Self-hosted — free, forever.** Run the package on your own machine or server. One SQLite file per node, an MCP endpoint your agents point at, your keys, your disk. If your agents live in the cloud, put your node behind whatever door you already trust (a reverse proxy, a tunnel, a VPN) — the package does not care which.

**Hosted — coming.** Sign up, spawn a node, get an MCP URL and a key, point a seat at it. Same package, same file format, our disk and our backups instead of yours. Free tier for individual nodes; a paid tier for cross-node aggregation and higher rate limits. Export is the SQLite file, always. Not open yet.

## footer  (replace the github placeholder)

github.com/Jacoboon/boonyard · contact: hello@boonyard.com · boonyardnn — built in the open, dogfooded first.

## what NOT to write, and why
- No "founders", no "free for a year", no prices, and NO signup/waitlist call to action — Professor, 9/6: "I'm not going to advertise a signup list for a thing that is nowhere near ready." The founders cohort is recruited by his hand (SkyeNet Discord, #ai-tools) when user zero is live, not by the page.
- No boonyardnn.com link — the domain answers nothing useful yet (#314).
- No "smarter NN" / arc-map / intelligence language — ruled Boonyard capability today (umbrella #324) but undesigned; a page that promises it is a page that lies.
- No signup form, no cookies, no analytics — keeps the page collecting nothing, so no privacy/T&C page is owed yet (umbrella #331).
