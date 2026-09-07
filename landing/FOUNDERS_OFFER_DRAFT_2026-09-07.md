# The founders' offer — one paragraph, two places (DRAFT 2026-09-07)

> Design seat (Conductor, Cowork). For the landing page's "hosted" block and for Professor's Discord post. Every claim maps to something live at boonyard.com/app tonight (boonyard #116, #120) or to a choice marked in brackets (ADR-0011). **Two things are deliberately NOT promised here:** the hosted cross-node aggregator (the `_aggregate` endpoint is not built — umbrella #335 (d)) and encryption at rest (ADR-0012, not yet). The page already says "a paid tier for cross-node aggregation" as a future; leave that sentence as it is.
>
> Blessed by: ______

## For the landing page (replaces the "hosted — open to founders" sentence pair)

**hosted — open to founders.** Sign up, create a node, get an MCP URL and a key, point a seat at it. Same package, same file format, our disk and our backups instead of yours. The first twenty verified accounts are founders: a year of the paid plan — every node you want, the higher limits — free, no card, and half price for as long as you stay after that. Your founder number is yours forever. What you write is yours forever too: append-only memory, one SQLite file per node, exported in one click whenever you like. *N of 20 founder seats taken.*

## For the Discord post (his voice; edit freely)

Boonyard is live. It's the append-only memory I've been running my own AI seats on since July — one SQLite file per node, an MCP endpoint your agents point at, full-text search, threads, tags, skills. Open source, stdlib only, `pip install` it and run it on your own machine for free, forever.

There's now a hosted version at **boonyard.com** so you don't have to run anything: sign up, make a node, get a URL and a key, paste it into Claude (or whatever you use) as an MCP connector, and your seats have a memory that survives the thread.

The **first twenty accounts are founders** — a year of the paid tier free, no card, half price for life after that, and your founder number on the account permanently. Honest bit: it's a soft launch, one small box, one guy. Export is a plain SQLite file, always, so nothing you write is ever stuck with me. The seat count is live on the front page.

boonyard.com — questions to hello@boonyard.com or right here.

## Notes for whoever pastes it

- The founders' rate is DECIDED (Professor, 2026-09-07): a year free, then 50% off Pro for life (ADR-0011 §3). Both versions above say so.
- "the higher limits" is deliberately vague until ADR-0011 fixes what Pro is; do not write numbers on the page that the limits page does not also show.
- The privacy sentence on the landing page ("who can see it") should link `/app/privacy` — it exists and it is honest today.
