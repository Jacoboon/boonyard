# Changelog

All notable changes to the `boonyard` package are recorded here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning follows [ADR-0002 / architecture 04](docs/architecture/04_distribution.md): **the
major version is the schema version.** A package on `3.x` reads and writes v3 nodes. A major
bump means a schema rollover, never a marketing decision.

## [Unreleased]

### Added
- `LICENSE` (Apache 2.0). The license was decided in
  [ADR-0006](docs/adr/0006-oss-core-saas-freemium.md) on 2026-05-20 and stated in the README
  from genesis, but the file itself was never committed.
- `CONTRIBUTING.md` — the inbound = outbound model promised by ADR-0006, plus the locked
  constraints a PR has to respect.
- This changelog.

### Fixed
- README corrected. It had said *"Status: Pre-Phase-1… What it does not yet contain: working
  package code"* — false since 2026-07-18, when M1–M8 shipped. It also pointed at the v2
  `nn.vectorscape.uk` wall as the place to track progress; that node is v2-schema and was
  deregistered from the aggregator on 2026-07-26.

### Known open items
- **Aggregator rejects hyphenated node names.** `aggregator._IDENT` is `^[A-Za-z0-9_]+$`
  because node names become SQL `ATTACH` identifiers, but `docs/ADOPTION.md` mints hyphenated
  slugs (`boonyard init --name mycelium-sky`). A registry holding a hyphenated key crashes
  every read across *all* nodes in the union. Worked around in config today by using
  underscore keys as labels. Fix is either (a) allow hyphens after auditing every SQL
  interpolation of node names, or (b) normalize-or-reject loudly at write time. Design call
  pending. *(boonyard node #76, finding 1.)*
- **A non-v3 node in the registry takes down the whole union.** A v2-schema node (table
  `journal`, not `entry`) raised `no such table: <node>.entry` and broke reads across every
  registered node, not just itself. The soft-validation spirit says the aggregator should
  detect the version at attach, skip the node, and warn in the result envelope. ADR-0003
  clarification candidate. *(boonyard node #76, finding 2.)*
- `log_entry()` in the Python API accepts `tags` only as a comma-separated string; the MCP
  layer accepts a list. Architecture 06 specifies list-preferred at both surfaces.
  `_normalize_tags` should accept `list | str | None`. *(boonyard node #58.)*
- Vendored/hand-copied `BOONYARD.md` manuals drift as the package evolves. Right-shaped fix
  is for `boonyard init` (or a `boonyard manual` command) to emit the manual from the
  installed package, so the version stamp is always true. *(boonyard node #63.)*

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

[Unreleased]: https://github.com/Jacoboon/boonyard/compare/v3.1.0...HEAD
[3.1.0]: https://github.com/Jacoboon/boonyard/releases/tag/v3.1.0
[3.0.0]: https://github.com/Jacoboon/boonyard/releases/tag/v3.0.0
