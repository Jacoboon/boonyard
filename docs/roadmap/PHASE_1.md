# Phase 1 — Package Extraction + Dogfood Across Jacob's Projects

> Lift the substrate into a standalone stdlib-only package, migrate the existing live NNs onto it, run them in production for long enough that "the substrate compounds value" is *demonstrated*, not asserted.

> **SCOPE CORRECTION — 2026-07-16, Professor's call (live NN entries 94–95).** BoonyardNN builds and designs; it does not import other NNs' data ("no mixing of the batter bowls"). Consequences for this document as written below:
>
> - **Migrations struck from Phase 1 entirely** — no `migrations/` directory in the package (deliverables 3, 4, 8; acceptance criteria 2, 3). The legacy NNs are one-of-a-kind; each repo handles its own rollover on its own timeline with bespoke scripts written then. `architecture/08_migration.md` remains as guidance documentation, not shipped code.
> - **Dogfood reshapes to self-hosting.** During the build, the existing vectorscape wall stays the working journal. When the package is stable, BoonyardNN stands up its **own node** on the package — the first production consumer — and the soak happens there.
> - **New Phase 1 work item: vectorscape-wall audit.** When Boonyard's node goes live, the vectorscape NN gets a full audit for content pertinent to the NN's evolution; pertinent material is *distilled* (referenced, not bulk-imported) into the Boonyard node. The vectorscape NN is eventually archived once each involved repo completes its own audit.
> - Net Phase 1 scope: extract package (no migrations) + full test suite + CLI + MCP server + Boonyard's own node + wall audit/distill + soak.

## Goal

Make BoonyardNN exist as runnable code that Jacob's existing projects actually depend on. PlaneScape's NN runs on the package. JRHood's NN runs on the package. (Spore and Vectorscape follow when they're being worked on; not gates for Phase 1 completion.) The MCP doorway at `nn.vectorscape.uk/sse` is unchanged from a user perspective but is internally running on the boonyard package.

## Why this phase

CHARTER's dogfood pact: BoonyardNN earns its keep on user zero's projects *before* opening to other users. Phase 1 is where that proof happens. If the substrate doesn't compound value across PlaneScape + JRHood after a month of real use, Phase 2 (SaaS MVP) doesn't proceed.

## Deliverables

### 1. The `boonyard` package — extracted, complete

Lift `PlaneScape/_dev/journal/` into `package/boonyard/` and apply the canon. Output: an importable Python package with:

```
package/boonyard/
    __init__.py
    db.py              # connect, init_db, the DDL from architecture/02
    log.py             # log_entry, log_skill_revision, validators
    query.py           # recent, by_id, get_thread, search_by_tag, search_text,
                       # list_tags, list_agents, list_entry_types, list_skills,
                       # latest_skill, search_by_tag_exact, node_info, audit_doctor
    aggregator.py      # the over-many reader
    profile.py         # boonyard.toml parsing + soft-validation
    cli.py             # the boonyard CLI surface from architecture/04
    mcp.py             # the stdlib http.server-based MCP server
    migrations/
        __init__.py
        v1_to_v2.py
        v2_to_v3.py
        from_jrhood.py
        from_spore.py  # placeholder
    retag.py           # the audited retag operation (ADR-0005 exception)
    backup.py          # SQLite online-backup + WAL-aware copy
    export.py          # the export bundle producer
    constants.py       # SCHEMA_VERSION, etc.
```

Stdlib-only (ADR-0001). Python 3.11+. No `requirements.txt`. `pyproject.toml` declares Python version and the empty `dependencies` list.

### 2. Test suite

`tests/` with unittest-runnable coverage of:

- Every public API function with happy path + at least one failure path.
- Soft validation: unknown agent / entry_type / tag namespace warns but inserts.
- Hard validation: missing required field rejects.
- FTS5 trigger correctness: insert produces searchable entry; tag-trigger denormalization.
- `entry_tag` lookup correctness for tag namespaces.
- Append-only enforcement: API has no delete / update; running raw `DELETE FROM entry` works (we don't break SQLite) but a `boonyard doctor` audit flags it as suspicious.
- Aggregator correctness: multi-DB UNION returns expected rows; `query_only` blocks writes.
- Migration correctness: v2 source → v3 target → entry counts match, content preserved, FTS index queryable, entry_tag populated.
- CLI surface: every command's `--help` works; every command's exit code is correct.

Target: ≥90% line coverage on the package. Test runtime ≤30s.

### 3. PlaneScape NN migrated

Per `architecture/08_migration.md` §1. Steps:

1. Run `boonyard migrate from_planescape PlaneScape/_dev/journal/journal.db` → produces `PlaneScape/_dev/journal/journal.db.new`.
2. Spot-check: `recent 20` matches between old and new.
3. Run validation: row count, FTS query, list_tags output.
4. Stop the MCP server at `nn.vectorscape.uk/sse`.
5. Atomic swap: `mv journal.db journal.db.pre-v3.bak && mv journal.db.new journal.db`.
6. Restart the MCP server (now serving via the boonyard package's MCP module instead of the old `_dev.journal` directly).
7. Verify: every Opi seat (Code, Cowork-Opus, Chat-Opus, Professor) makes a successful read + write.

The MCP doorway URL stays the same (`nn.vectorscape.uk/sse`); only the implementation behind it changes.

### 4. JRHood NN migrated

Per `architecture/08_migration.md` §2. Steps:

1. Run `boonyard migrate from_jrhood JRHood/data/jrhood.db --table agent_log` → produces `JRHood/data/journal.db` (note: separate file from the operational `jrhood.db` which holds refunds, claims, etc.).
2. Spot-check: random 20 entries' content matches when joining old `action + notes` vs new `content`. Case-number tags match the count of non-null `case_number` values.
3. Update `JRHood/agents/agent_log.py` to write to the new boonyard-package node (it becomes a thin wrapper that calls `boonyard.log_entry` with the appropriate translation: action+notes → content, case_number → `case:` tag).
4. Run JRHood's existing scripts against the wrapper — verify CI green.
5. Cutover: production scripts now write to the boonyard node. The old `agent_log` table is renamed `agent_log_pre_v3` and not written to anymore (kept as archive).
6. Update JRHood's NN.md to point at the new schema location.

### 5. The MCP doorway is the package's MCP server

Today: a hand-written MCP server fronts the PlaneScape NN at `nn.vectorscape.uk/sse`. After Phase 1: `boonyard mcp --db .../journal.db --port 8765` serves the same node, behind the same cloudflared tunnel, at the same URL. The hand-written MCP code retires.

The MCP tool surface from `architecture/06_mcp_surface.md` is fully wired up — including the new tools (`search_by_tag_exact`, `list_skills`, `latest_skill`, `list_nodes`, `audit_doctor`).

### 6. The CLI is real

`boonyard` is installable and runnable on Jacob's machine. Every CLI command in `architecture/04_distribution.md` works. The PlaneScape `_dev/journal/cli.py` retires; its commands are now `boonyard` subcommands.

### 7. Seed skills

The substrate now exists as the substrate intended for skills. Backfill the first batch of "skills with nowhere to live until now":

- FUSE boot ritual (the canonical example; live NN entry 66 has the pattern).
- Smoke-harness conventions (subprocess + tempdir + PYTHONPATH + UTF-8 stdout; live NN tags `smoke-harness`).
- RNG-consumption-order branching (the P24 brown-dwarf gotcha; live NN entry 66).

Three skill entries, root-anchored, fully templated, tagged `skill, skill-<slug>, fuse / smoke-harness / rng-determinism, prompt-<N>`.

### 8. Live NN documentation

Update the existing live NN's host project (PlaneScape) docs:

- `PlaneScape/_dev/journal/` retires; the README at that location becomes a forwarding note ("The NN now lives in the boonyard package. The journal.db file in this directory IS a boonyard node; manage it via `boonyard` CLI.").
- `PlaneScape/CLAUDE.md` updates the NN section to reference the new commands and the canonical conventions from this canon.

JRHood's `NN.md` gets a similar update.

### 9. Phase 1 marker entry in the live NN

```
agent: code
entry_type: implementation
tags: implementation,boonyard,phase-1,milestone
content: BoonyardNN Phase 1 complete. boonyard package extracted, tested, runs both PlaneScape NN (this MCP doorway) and JRHood NN in production. Three seed skills backfilled. PlaneScape's _dev/journal/ retired; JRHood's agent_log_pre_v3 archived. Dogfood proof: <N> days of production use, <M> entries written via the package, zero data loss, all four seats reading and writing successfully. Phase 2 (SaaS MVP) is gated on Jacob's review of dogfood evidence.
```

## Acceptance criteria

Phase 1 is complete when:

1. The `boonyard` package is installable (`pip install -e .` from the repo works), passes its full test suite, and has docs for every public API function.
2. The PlaneScape NN runs on the package, served via `boonyard mcp` behind the existing cloudflared tunnel at `nn.vectorscape.uk/sse`.
3. The JRHood NN runs on the package; production scripts write via the boonyard wrapper.
4. The three seed skills are present in the PlaneScape NN, retrievable via `latest_skill`.
5. The convention splices from Phase 0 are still in place; CLAUDE.md / NN.md updates reflect the new surface.
6. ≥ 1 week of real use across both projects with zero data-loss incidents and the substrate continuing to compound value (the question to answer: "is the substrate making my work better, or is it overhead?" — answer must be the former, with evidence).
7. The Phase 1 marker entry is logged.

## What Phase 1 does NOT include

- No SaaS deployment at boonyardnn.com (Phase 2).
- No multi-tenant code (Phase 2 / Phase 3).
- No billing (Phase 3).
- No public sign-ups (Phase 3).
- No webhook / push notification (deferred earned feature, Phase 3.5+).
- No embeddings (ADR-0010; deliberately never default).

## Risks

- **Migration introduces subtle bugs.** Mitigation: extensive spot-checks, parallel-run both old and new for 24h before retiring the old, keep the .bak files for 30 days.
- **The CLI rewrite breaks operational tooling.** Mitigation: ship backward-compatible flags where possible; one-time update of any scripts that used `python -m _dev.journal.cli`.
- **JRHood's `agent_log.py` wrapper has edge cases.** Mitigation: snapshot test of every code path that calls `log_action` to confirm behavior preserved.
- **The package adds friction to the live NN.** Mitigation: nothing in the package should make the existing workflows slower or harder. If Phase 1 ends and the substrate feels worse than the pre-Phase-1 setup, do not proceed to Phase 2; address the regression first.
- **Scope creep.** Phase 1 is extraction + dogfood. Anything else (new MCP tools beyond what's already in the canon, web dashboard work, etc.) is Phase 2+. Apply Project-Six guardrail rigorously.

## Estimated effort

The hard work is the package authoring (architecture 01-08 specify it; the code mostly writes itself from there) + the migrations (well-defined per architecture 08) + the rollout discipline. Realistic estimate: 2–3 focused work sessions for the package, 1–2 sessions for each migration, 1–2 weeks of soak time, then the marker entry.

## Then what

When Phase 1 is complete and the dogfood evidence is solid: Phase 2 — SaaS MVP for user zero (Jacob signs up on his own boonyardnn.com, the same way other users eventually will, to prove the SaaS deployment shape works).

If Phase 1's dogfood evidence is thin or negative: pause, log the issue as a `discussion` entry in the live NN, reassess the canon, consider Phase 1.5 (refinements) before Phase 2.
