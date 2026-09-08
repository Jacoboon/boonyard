# Changelog

All notable changes to the `boonyard` package are recorded here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning follows [ADR-0002 / architecture 04](docs/architecture/04_distribution.md): **the
major version is the schema version.** A package on `3.x` reads and writes v3 nodes. A major
bump means a schema rollover, never a marketing decision.

## [3.4.0] — 2026-09-07

One addition to `MCPServer` and one refactor that had to be made safely (ADR-0014, accepted
at umbrella #397). The `entry` table is untouched (ADR-0002/0005).

### Added
- **`MCPServer(nodes={slug: path})` — the account door.** A third construction: several named
  nodes, writable. A call that names a node is served against that node's file exactly as
  single-node mode does; a read that names none, or several, is served by an `Aggregator` over
  the same map. This is what lets one connector reach every node in an account — and equally
  what lets a self-hoster point one server at three local nodes (ADR-0006: the package is the
  SaaS, so the hosted layer must not hold an algorithm the package lacks).
- **`account_tool_defs()`** — `TOOL_DEFS` with `node` **required** on every write tool,
  *derived* from the module default and from `_WRITE_TOOLS`, never retyped. `tools/list` is
  answered per connection, so the account door advertises `node` and the per-node door does
  not (ADR-0014 §3). Requiring it is the structural half of §4's "no default node": a misfile
  becomes a wrong argument rather than a forgotten one, and append-only means a misfile can
  only be corrected, never taken back.
- A write naming an unknown node now gets an error that **names the nodes that exist**, so a
  model that guessed wrong can fix itself in one turn.
- Each node's own `boonyard.toml` governs soft validation at the account door, loaded beside
  its file and cached — the same write behaves the same at either door.

### Changed
- **`_read_only` is explicit, not derived.** It was `aggregator is not None`, which was the
  entire protection on the read-only `_aggregate` endpoint. `nodes` mode holds an aggregator
  *and* permits writes, so that expression would have made `_aggregate` silently writable.
  The mode is now set once in the constructor and read-only follows from it.
- A server validates tool names and required parameters against **its own** surface rather
  than the module-level one.
- `MCPServer(nodes=…)` refuses to construct without a `meter_path`: with no single home node
  there is nothing to derive, and an endpoint metered by nothing is worse than a loud error.

### Tests
- `tests/test_account_door.py` (23 cases). The load-bearing one asserts the two modes differ
  over the **same node map**: aggregator-mode refuses `log_entry`, nodes-mode accepts it, and
  the refusal writes nothing. Shown red first by flipping the explicit state — 5 failures
  across the suite, 3 of them in this file.
- Package suite 318 (was 295).

## [Unreleased]

### Repo, not the package
- **The legal pages, served** — `saas/boonyardnn/legal.py`: `/app/terms` (new) and
  `/app/privacy` (the full blessed policy; the three-heading page it replaces was its §1/§4/§7
  in short). Every bracket in `docs/legal/*.md` resolved from the running system; the served
  bodies contain no `[`. Footer and signup form link both. *(2026-09-07; umbrella #361/#364.)*

## [3.3.0] — 2026-09-07

Three additions, no change to the `entry` table (ADR-0002/0005): a node made before this
release and one made after are identical the moment they upgrade (umbrella #362).

### Added
- **`instructions` — the package readme, one static call away.** `boonyard.instructions`
  builds a ≤ 3,500-byte readme for a model (what a node is; the read law; the write
  conventions; the registers; skills; one line per tool, assembled from `TOOL_DEFS`); the MCP
  `initialize` result carries it as the spec's `instructions` string, so a client that
  honours it hands the text to the model on every connect. Tool `instructions(scope?)` →
  `{package, version, readme}` where `readme` is the node's own readme: the newest revision of
  the skill with the reserved slug `readme` (ADR-0004 clarification). `node_info` gains
  `has_readme` / `readme_id`. CLI `boonyard instructions` (with `--db`, appends the readme).
  The machinery test: every `_TOOL_NAMES` entry must appear in the text — a tool added without
  a readme line fails CI. *(Professor's idea, boonyard #125; ADR-0013 §adjacent.)*
- **Read heat — the sidecar (ADR-0013 §2a).** `meter.db` gains `read_hit(ts, tool, node,
  entry_id)`: one row per entry id a READ returned, written by a separate hook AFTER dispatch
  (`record_hits`, cannot raise; never the query, never the caller — `record()` keeps its
  no-arguments contract). `entry_heat()` → `{id: {reads, last_read}}`; `rollup()` folds rows
  older than 180 days into `read_hit_rollup` counts; CLI `boonyard meter rollup`. In aggregator
  mode hits are attributed per row by its `source` node.
- **`ghosts` — the orphan sweep, derived (ADR-0013 §2b).** `views.ghosts(limit=20,
  older_than_days=30)`: root entries (`related_id IS NULL`, not `meta`) with no children, older
  than the window, and no read inside it, coldest first; rows of `{id, timestamp, agent,
  entry_type, first_line, tags, reads, last_read}`. Tool and CLI `boonyard ghosts`. The dated
  half of the sweep stays `upcoming_dates(prefix="open")`.
- The MCP server exposes **20 tools** (was 18); additive, hence a minor bump (architecture 06).

### Tests
Package: the machinery test (a tool name deleted from the readme → red), the hook test (hook
removed → `by_id` writes no `read_hit` → red), `get_thread` records root + children, a write
records nothing, the `ghosts` fixture (unthreaded-unread listed; with-child not; read not),
`rollup` moves exactly the old rows. Shown red first, then green; full suite green; `ruff`
clean. Versions in both files (`pyproject.toml`, `__init__.py`) read 3.3.0.

### Repo, not the package (carried)
- **The node browser, limits and backups** — `saas/` slice 3 (`boonyardnn` 0.3.0.dev0):
  `browser.py` (the dashboard's single-node view at `/app/nodes/{slug}`: recent, search by
  text or tag, threads, write an entry as the human seat, retag with a reason, export,
  tombstone a node with typed confirmation — no entry edit, no entry delete, per
  ADR-0005); ADR-0008's per-key rate limits in the router (Free 30 writes / 600 reads per
  minute, Pro 600 / 6000, burst 10×; HTTP 429 + `Retry-After`); the Free 10,000-entries-
  per-node cap on the write path (`quota_exceeded`); `Registry.remove_node` (tombstone +
  key revocation), `set_plan` (the account's plan mirrored for the router), and
  `boonyardnn backup-config`, which emits the `[nodes]` table the nightly `backup_walls.py`
  reads so every hosted node is bundled and restore-proven without a config edit
  (umbrella #339). *(2026-09-07; boonyard #118/#119.)*
- **The signup platform** — `saas/` slice 2 (`boonyardnn` 0.2.0.dev0): `accounts.py`
  (`system/users.db`: signup, email verification, sign-in by emailed link *or* password,
  sessions, founder seats), `web.py` (the app at `boonyard.com/app`: signup → verify →
  dashboard with create node / mint key shown once / revoke / export; `/app/founders.json`
  is the public counter the landing page reads; `/app/privacy`), `mailer.py` (AgentMail
  over `urllib`; `log`/`none` modes), and `serve-web` / `account` / `mail` CLI commands.
  The first twenty verified signups are founders, free for a year. Nothing under
  `package/` changed. *(2026-09-07; Professor's order at boonyard #109/#113/#115.)*
- **The domain is boonyard.com.** Every `boonyardnn.com` in the canon, the roadmap, the
  glossary, the README, SECURITY.md, CLAUDE.md/AGENTS.md and the `saas/` tree is replaced by
  `boonyard.com`; each canon doc carries a dated note; the glossary keeps a `→` redirect. The
  old name was the gen0, vectorscape-era registration and is retired in full. *(2026-09-06;
  Professor's decision at boonyard #109.)*
- `saas/` — the hosted layer (`boonyardnn`: provisioner + path router, Phase 2 slice 1).
  A separate, unversioned distribution that *depends on* `boonyard`; it is not part of the
  package wheel and imports the package through `saas/boonyardnn/adapter.py` only.
  Nothing under `package/` changed. *(2026-09-06; umbrella #335.)*

## [3.2.0] — 2026-09-06

Two additive tools landed on `main` between 2026-08-24 and 2026-08-25 while `pyproject.toml`
still said 3.1.0. Architecture 06's rule — a new MCP tool is a minor bump — makes this cut due.
No PyPI upload; the tag is the release.

### Added
- **`upcoming_dates` — the kill-date register.** `query.upcoming_dates()`,
  `Aggregator.upcoming_dates()`, MCP tool `upcoming_dates`, CLI `boonyard umbrella dates`.
  A prefix scan over tags shaped `<prefix>:YYYY-MM-DD` (default prefix `killdate`), soonest
  first. **Overdue rows are never dropped**: they return with `overdue=true` and a negative
  `days_out` until a human retires them; only the future side is bounded by `within_days`.
  Returns an envelope `{today, within_days, prefix, dates[], warnings[]}` rather than a bare
  list because the warnings channel is load-bearing — a malformed tag or a skipped node is
  *seen*, not silently dropped. `days_out` is measured against the local wall-clock date.
  *(2026-08-24; architecture 06 §upcoming_dates, ADR-0003 dated clarification.)*
- **`read_stats` — the meter.** `meter.read_stats()`, `Aggregator.read_stats()`, MCP tool
  `read_stats`, CLI `boonyard meter`. How often a node is READ versus WRITTEN over the last
  `within_days` (default 7, ending today inclusive): `{window_days, since, until,
  totals{reads, writes, ratio}, by_tool, by_day, warnings}`. A ratio below 1 means the wall is
  written more than it is consulted. The meter lives in a sidecar `meter.db` beside the node —
  **never in `entry`** — and records tool name, node, kind and a local timestamp only.
  **Arguments are never recorded**, so a search query carrying a person's name cannot leak
  into a second file; `tests/test_meter.py` pins this with a sentinel. Fail-soft: if the
  sidecar cannot be opened, `record()` returns `False` and the read it was measuring is still
  served. The aggregator unions each node's sidecar and reports an unreadable or absent meter
  as a warning. *(2026-08-25; umbrella #228 Layer 3.)*
- The MCP server exposes **18 tools** (was 16). Both additions are additive — hence a minor
  bump, per architecture 06 ("additions are minor-version bumps; removals are major").
- `.gitattributes` — `* text=auto`, shell scripts pinned LF, database/zip files binary. The
  repo had been committed from a `core.autocrlf=true` machine with nothing enforcing line
  endings; every tracked file was already LF, so the renormalisation changed no bytes.
- `LICENSE` (Apache 2.0). The license was decided in
  [ADR-0006](docs/adr/0006-oss-core-saas-freemium.md) on 2026-05-20 and stated in the README
  from genesis, but the file itself was never committed. *(2026-08-22.)*
- `CONTRIBUTING.md` — the inbound = outbound model promised by ADR-0006, plus the locked
  constraints a PR has to respect. `SECURITY.md` — one maintainer, no SLA, no bounty,
  coordinated disclosure to `security@boonyard.com`. *(2026-08-22 / 2026-08-25.)*
- This changelog.

### Fixed
- **A non-v3 node in the registry no longer takes down the whole union.** The aggregator now
  checks at attach that a node has a v3 `entry` table; a v2-schema straggler (or a file that
  is not a boonyard node at all) is skipped and reported in the result envelope as
  `{"kind": "node_skipped", "node": ..., "detail": ...}` instead of raising
  `no such table: <node>.entry` across every node. This is the degrade-don't-crash path
  ADR-0003's dated clarification (2026-08-24) asks for, and it closes the second known open
  item from 3.1.0 *(boonyard node #76, finding 2)*.
- The meter parity test in `tests/test_mcp.py` had frozen "today" at the date it was written
  and aged out of its own 7-day window; it now uses the real local date. Test-only.
- README corrected. It had said *"Status: Pre-Phase-1… What it does not yet contain: working
  package code"* — false since 2026-07-18, when M1–M8 shipped. It also pointed at the v2
  `nn.vectorscape.uk` wall as the place to track progress; that node is v2-schema and was
  deregistered from the aggregator on 2026-07-26.

### Convention (documentation, not code)
- **Retiring a register row: `killdate:` → `killdate-retired:`, `open:` → `open-retired:`**,
  via `boonyard retag` (the audited tags-only mutation, ADR-0005; the `meta_log` row is the
  receipt). `upcoming_dates` matches the exact prefix, so a retired row vanishes from the
  reader while its date stays greppable in the tag. Nothing in `retag.py` knows about the
  suffix — it is a naming convention, proposed at boonyard node #79 and first applied at
  umbrella #311. The near-miss shape `killdate-YYYY-MM-DD` (hyphen, no colon) is *not* a
  retirement: the reader never matched it in the first place (umbrella #274).

### Tests
277 total, package 98% line coverage (`pytest --cov=boonyard`, fresh venv, Python 3.12.6,
2026-09-06). The suite also runs bare under `python -m unittest`. `ruff check` clean.
Re-taken at the cut, not re-cited.

### Known open items
- **Aggregator rejects hyphenated node names.** `aggregator._IDENT` is `^[A-Za-z0-9_]+$`
  because node names become SQL `ATTACH` identifiers, but `docs/ADOPTION.md` mints hyphenated
  slugs (`boonyard init --name mycelium-sky`). A registry holding a hyphenated key crashes
  every read across *all* nodes in the union. Worked around in config today by using
  underscore keys as labels. Fix is either (a) allow hyphens after auditing every SQL
  interpolation of node names, or (b) normalize-or-reject loudly at write time. Design call
  pending. *(boonyard node #76, finding 1. Unchanged at 3.2.0.)*
- `log_entry()` in the Python API accepts `tags` only as a comma-separated string; the MCP
  layer accepts a list. Architecture 06 specifies list-preferred at both surfaces.
  `_normalize_tags` should accept `list | str | None`. *(boonyard node #58. Unchanged.)*
- Vendored/hand-copied `BOONYARD.md` manuals drift as the package evolves. Right-shaped fix
  is for `boonyard init` (or a `boonyard manual` command) to emit the manual from the
  installed package, so the version stamp is always true. *(boonyard node #63. Unchanged.)*
- `ruff format --check` reports two package files it would reformat (`aggregator.py:108`,
  `cli.py:251`); `ruff check` (lint) is clean. Left as-is at the cut — a release cut does not
  touch package code.

## [3.1.0] — 2026-07-20

### Added
- **Capability-URL auth for the MCP server.** The key may now be supplied *either* as the
  `Authorization: Bearer` header (unchanged) *or* as the leading URL path segment —
  `POST https://host/<key>`. Timing-safe comparison (`hmac.compare_digest`) on both paths;
  wrong or missing on both still returns 401. This exists because the Claude app's
  custom-connector dialog offers OAuth or nothing — there is no header field — so a header-only
  server could not be wired from a chat surface.
- Streamable-HTTP compatibility hardening: clean `405` on `GET` (the server offers no
  server→client SSE stream), `202 Accepted` for notifications with no body,
  `application/json` responses, and the full `initialize` / `tools/list` / `tools/call`
  lifecycle over HTTP.

### Security note
Capability URLs carry the secret in the path, so it can appear in proxy and access logs. This
server never logs the URL (`log_message` is a no-op), but intermediaries may. The header path
remains available and is preferable wherever a client can send one.

### Tests
195 total; `mcp.py` at 94% coverage, package total 97%; ruff clean.

## [3.0.0] — 2026-07-18

First working release. Schema v3. Zero runtime dependencies
([ADR-0001](docs/adr/0001-stdlib-only.md)).

### Added
- **M1 — skeleton + schema.** `db.py` with the v3 DDL: the closed 8-column `entry` table,
  FTS5 external-content index with insert/update/delete triggers, the `entry_tag` companion
  table, `meta` and `meta_log`. `connect()` applies WAL, foreign keys, `synchronous=NORMAL`,
  and `query_only` when read-only; commits on success, rolls back on exception, always
  closes. `init_db()` is idempotent and preserves node identity across re-init.
- **M2 — write path.** `log_entry()`, `log_skill_revision()`, and the audited `retag`
  operation — the only legal mutation ([ADR-0005](docs/adr/0005-append-only-no-deletes.md)).
- **M3 — read path.** `query.py`: `recent`, `by_id`, `get_thread`, `search_text` (FTS5),
  `search_by_tag`, `search_by_tag_exact`, `list_tags`, `list_agents`, `list_entry_types`,
  `list_skills`, `latest_skill`, `node_info`, `audit_doctor`.
- **M4 — profile + aggregator.** `boonyard.toml` schema profiles (soft validation: unknown
  agents and entry types warn, never reject) and the read-only over-many aggregator that
  unions many nodes with source tagging.
- **M5 — CLI.** 21 commands via argparse.
- **M6 — backup + export/import.** SQLite online-API backups (consistent without quiescing
  writes) and portable export bundles.
- **M7 — MCP server.** `mcp.py`, stdlib `http.server` only, 16 tools, bearer-key auth
  ([ADR-0008](docs/adr/0008-mcp-routing-and-auth.md)).
- **M8 — self-hosting.** The project stood up its own node and began journaling to it.

### Hotfix (post-3.0.0, pre-3.1.0)
UTF-8 CLI output on Windows consoles; threaded MCP server; bearer key read from the process
environment rather than `argv`, so it never appears in a process listing or a shell history.

[Unreleased]: https://github.com/Jacoboon/boonyard/compare/v3.2.0...HEAD
[3.2.0]: https://github.com/Jacoboon/boonyard/releases/tag/v3.2.0
[3.1.0]: https://github.com/Jacoboon/boonyard/releases/tag/v3.1.0
[3.0.0]: https://github.com/Jacoboon/boonyard/releases/tag/v3.0.0
