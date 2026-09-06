# Changelog

All notable changes to the `boonyard` package are recorded here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning follows [ADR-0002 / architecture 04](docs/architecture/04_distribution.md): **the
major version is the schema version.** A package on `3.x` reads and writes v3 nodes. A major
bump means a schema rollover, never a marketing decision.

## [Unreleased]

### Repo, not the package
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
