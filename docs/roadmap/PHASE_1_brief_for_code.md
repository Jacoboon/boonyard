# Phase 1 — Execution Brief for Claude Code

> Authored by the design seat (Cowork, Fable), 2026-07-17. This brief operationalizes
> `PHASE_1.md` **as amended by live NN entries 94–95** (the scope reshape). Where this
> brief and the original body of `PHASE_1.md` disagree, the reshape wins; where this
> brief and the wall disagree, the wall wins. Threaded on the wall to entry 95.

You are Code, the implementing seat. Boot per `CLAUDE.md` (CHARTER first, then the wall,
then the ADRs relevant to the milestone you're on). This document tells you *what to
build, in what order, and where to stop*. The canon tells you how. You make no
load-bearing design decisions — those are already made; when you think you've found one
that isn't, that's a `discussion` entry, not a judgment call.

---

## Instruction 0 — Version control genesis (do this before anything else)

The repo has **no version control**. Phase 0 shipped an entire canon with no history.
Fix that first, before a single line of package code exists:

1. `git init` in `C:\Users\Jacob\Code\BoonyardNN\`.
2. Create `.gitignore` before the first commit:

   ```gitignore
   __pycache__/
   *.py[cod]
   .ruff_cache/
   .coverage
   htmlcov/
   dist/
   *.egg-info/
   # Boonyard's own live node (M8) — data never goes in git.
   # (Comment kept on its own line: gitignore does NOT support inline
   # comments — the original draft had one here, which silently broke the
   # pattern. Caught by Code at M8, node entry 1 / commit 8344c62.)
   node/
   *.db
   *.db-wal
   *.db-shm
   ```

3. Genesis commit: the canon exactly as it stands — `CHARTER.md`, `CLAUDE.md`,
   `README.md`, `docs/` (glossary, 10 ADRs, architecture 00–08, roadmap incl. this
   brief), `landing/index.html`. Suggested message:

   ```
   Genesis: BoonyardNN canon — CHARTER, 10 ADRs, architecture 00-08,
   roadmap, glossary, landing. Phase 0 complete per wall entry 92.
   ```

4. Annotated tag `phase-0-complete` on the genesis commit.

From here on, **every milestone below ends in a commit** (more than one is fine; zero is
not). Commit messages reference the ADRs they realize (e.g. `M2: log_entry + soft
validation (ADR-0002, ADR-0005, ADR-0009)`). The repo's history should read like the
wall's implementation thread.

---

## Scope — one paragraph

Extract the substrate into `package/boonyard/` (stdlib-only, Python 3.11+), with a full
unittest suite, a working `boonyard` CLI, and the package's own MCP server — **no
`migrations/` directory, no legacy-NN import code of any kind** (struck per entry 95).
When the package is stable, stand up **Boonyard's own node** on it — the first
production consumer — and soak. The vectorscape wall stays the working journal during
the build and **you do not touch the live doorway at `nn.vectorscape.uk/sse`** — it
keeps running its existing hand-written server until PlaneScape does its own rollover on
its own timeline, which is not your job and not this phase.

### Explicitly NOT in Phase 1

- No `migrations/` package code; no `boonyard migrate` CLI command; no
  from_planescape / from_jrhood / from_spore anything. `docs/architecture/08_migration.md`
  is guidance for *other repos' future work*, not a spec for you.
- No changes to PlaneScape, JRHood, Spore, or any other repo. This repo only.
- No importing other NNs' data into anything ("no mixing of the batter bowls", entry 94).
- No SaaS, no multi-tenancy, no billing, no REST API, no Docker (Phase 2+).
- No embeddings (ADR-0010). No delete/update paths (ADR-0005). No eighth entry column
  (ADR-0002). No new MCP tools beyond `architecture/06_mcp_surface.md`.

---

## Source material

You are extracting and canonicalizing, not inventing. Read-only references:

- `C:\Users\Jacob\Code\PlaneScape\_dev\journal\` — the v2 reference implementation
  (the substrate as it runs today behind the live doorway).
- `C:\Users\Jacob\Code\PlaneScape\_dev\visions\NN Fiuture\NN_upgrade_implementation_appendix_v1.1.md`
  — tested FTS5 + `list_tags` + skill-pattern code. Lift with attribution in docstrings
  where it survives intact.
- The canon: `docs/architecture/01–06` specify every module; ADRs 0001–0010 constrain them.

Lifting means: take what works, apply the canon's naming/typing/validation discipline,
leave the source repos untouched.

---

## Milestones

Each milestone = code + tests + commit + one `implementation` entry on the wall
(protocol below). Definition of done per `CLAUDE.md` ("What good work looks like").
Sequence is dependency-ordered; don't reorder without a `discussion` entry.

### M1 — Skeleton + schema

- `pyproject.toml`: Python ≥3.11, `dependencies = []`, ruff config (dev tooling may be
  pip-installed; the *package* imports stdlib only, per ADR-0001).
- `package/boonyard/__init__.py`, `constants.py` (`SCHEMA_VERSION` etc.),
  `db.py` — `connect()`, `init_db()`, DDL constant **exactly** per
  `architecture/02_schema_design.md`: the entry table (its column set is closed —
  additions need their own ADR per ADR-0002), FTS5 external-content index + triggers,
  `entry_tag` companion table, `meta`, `meta_log`. Note: entry_tag population is
  **application-side** (`_populate_entry_tags`, same transaction as the insert — the
  trigger is a documented no-op placeholder; see arch 02's comments).
- `tests/test_db.py`: init on `:memory:`, idempotent re-init, FTS trigger fires on
  insert and the row is searchable, meta bootstrap rows present.

### M2 — Write path

- `log.py`: `log_entry`, `log_skill_revision` (root-anchoring per ADR-0004), validators.
  Hard validation: required fields, `related_id` must exist. Soft validation: unknown
  agent / entry_type / tag namespace **warns but inserts** (ADR-0002, ADR-0009). If you
  find yourself hard-rejecting a soft case, you have misread an ADR — stop and surface.
- `retag.py`: the audited tags-only mutation (ADR-0005's sole exception) — logs a
  `meta_log` record with before/after/reason.
- Tests: happy paths, each hard-fail, each soft-warn-but-insert, `entry_tag` rows
  populated in-transaction, skill root-anchoring including first-revision-becomes-root,
  retag audit record present.

### M3 — Read path

- `query.py`: `recent`, `by_id`, `get_thread`, `search_by_tag`, `search_by_tag_exact`,
  `search_text`, `list_tags`, `list_agents`, `list_entry_types`, `list_skills`,
  `latest_skill`, `node_info`, `audit_doctor`. Signatures and return shapes per
  `architecture/06_mcp_surface.md` (the MCP doc is the contract; query.py is its
  in-process form). One parameterized SQL statement per function; `PRAGMA query_only = ON`
  on read-only paths.
- Tests: every function happy + failure path; `search_by_tag` substring vs
  `search_by_tag_exact` equality distinction; `audit_doctor` flags a raw-SQL `DELETE`
  as suspicious; skill grouping + deprecation detection in `list_skills`.

### M4 — Profile + aggregator

- `profile.py`: `boonyard.toml` parsing (stdlib `tomllib`), config precedence per
  `architecture/04_distribution.md` §Configuration, soft-validation wiring into log.py.
  The `[agents]` section is an **advisory seat registry** (see M8 for the full
  convention) — it informs warnings, never rejections. `audit_doctor` gains two soft
  checks: unknown seats (already specced in arch 06) and AI-seat entries missing a
  `model:` namespace tag.
- `aggregator.py`: the over-many reader (ADR-0003) — opens N node files read-only
  (`query_only` enforced), unions with `source` field, never writes.
- Tests: precedence order, malformed toml warns-not-crashes, multi-DB union
  correctness, write attempt through aggregator fails.

### M5 — CLI

- `cli.py`: the surface from `architecture/04_distribution.md` **minus** `boonyard
  migrate`. `argparse`, stdlib only. All output lives here (no `print` in library code).
- Tests: every command's `--help` exits 0; exit codes correct; `boonyard log` →
  `boonyard recent` roundtrip on a tmp node; `boonyard doctor` runs clean on a fresh node.

### M6 — Backup + export

- `backup.py`: SQLite online-backup API, WAL-aware. `export.py`: the export bundle
  producer; `boonyard import <path>` accepts *boonyard export bundles only* (this is
  bundle roundtrip, not legacy migration — do not generalize it).
- Tests: backup of a live node equals source content; export→import roundtrip
  preserves counts, content, tags, FTS searchability.

### M7 — MCP server

- `mcp.py`: stdlib `http.server`-based MCP server exposing exactly the tools in
  `architecture/06_mcp_surface.md` — no more, no fewer. `retag` is deliberately **not**
  an MCP tool. Error model per that doc's table. Auth/routing per ADR-0008 (local
  single-node mode is what ships this phase; per-node keys can be config-stubbed).
- Tests: tool discovery lists the canonical set; log→recent roundtrip over HTTP;
  validation errors return the structured error shape; write via aggregator scope
  returns `read_only`.
- **Do not point this at the PlaneScape node. Do not touch the cloudflared tunnel.**

### — GATE: Professor review —

Package complete, tests green, coverage ≥90%, runtime ≤30s. Log a `verification` entry
summarizing the suite, then **stop and wait**. Professor decides the package is "stable
enough to hold it" (entry 95's words) before M8. Do not proceed on your own clock.

### M8 — Boonyard's own node (late phase, gated above)

- `boonyard init --name boonyard` → node at `node/journal.db` (gitignored; path is a
  design-seat proposal — Professor may relocate it at the gate).
- Author `boonyard.toml` for this node per the **agent-identity convention** (Professor,
  wall entry 97; realized entirely by ADR-0002 soft validation + ADR-0009 namespaces —
  no schema change):
  - `[agents]` is an **advisory seat registry, not an allowlist**. Seats are *roles*,
    not models: `code`, `cowork`, `chat`, `professor`, `system` (register others as
    they earn a lane — e.g. `conductor`). Each with a one-line lane description.
    Unknown seats warn-but-insert, per canon; a recurring unknown seat is a signal to
    *register it*, not reject it.
  - **Model self-identification rides on tags**: every AI-seat entry carries a
    `model:` namespace tag with the exact model string — `model:claude-fable-5`,
    `model:gpt-5`, whatever is actually in the seat. Seats survive model swaps; the
    tag records who was driving. Provider-agnostic by construction: a GPT connected
    via MCP writes `agent=chat, tags=[..., model:gpt-5]` and everything works day one.
  - `boonyard doctor` / `audit_doctor` **softly** flags AI-seat entries missing a
    `model:` tag (`professor` and `system` exempt). Warn, never reject.
- Serve it locally via `boonyard mcp`. First entry in the new node: a genesis entry
  logging its own birth, by you, threaded to nothing, tagged `milestone, phase-1`.
- From this point, *Boonyard work* journals to the Boonyard node; the vectorscape wall
  gets a pointer entry announcing the move.

### M9 — Wall audit + soak (design-seat led; you assist)

- The vectorscape-wall audit/distill (entry 95) is the design seat's and Professor's
  work: pertinent history gets *distilled* into the Boonyard node — referenced, never
  bulk-imported. Your part: whatever query tooling they ask for, using the package's
  own read surface (dogfood).
- Soak: ≥1 week of real use on the Boonyard node, zero data loss, the CHARTER's
  question answered with evidence ("what project of Jacob's got better because this
  exists?" — this phase's honest answer: BoonyardNN itself runs on it, and the build
  was journaled through it).
- Phase 1 marker entry (adapted from `PHASE_1.md` deliverable 9 — self-hosting
  numbers, not migration numbers), logged to **both** nodes.

---

## Orphaned items from the original PHASE_1.md (dispositions — APPROVED)

The entry-95 banner struck deliverables 3, 4, 8; two more items were left dangling by
the reshape. Both dispositions **approved by Professor 2026-07-17 (wall entry 97)**,
with amendments:

1. **Seed skills (deliverable 7) — fresh start, approved.** The three PlaneScape-flavored
   seeds (FUSE ritual, smoke-harness, RNG gotcha) move to PlaneScape's own rollover.
   The Boonyard node starts clean; ADR-0004 gets dogfooded with *Boonyard-native*
   skills written from real M8+ experience. Professor's amendment: historical *lore*
   may be deliberately trickled in later via the M9 audit/distill lane (referenced,
   curated, never bulk-imported) — but every new occurrence is a clean slate.
2. **Doorway swap (deliverable 5) + acceptance criteria 2–5 — superseded, approved.**
   MCP server ships (M7) and serves *Boonyard's* node (M8). The live doorway's
   *infrastructure* stays fenced: you don't re-point, restart, or replace it.
   Professor's amendment: you **keep the wall connector** — the vectorscape wall is
   your working journal until M8, and a read-source after. Understand what it is: a
   historical, eventually-obsolete artifact that this project is redesigning and
   improving upon. Journal to it; learn from it; never intermingle its data with the
   Boonyard node outside the curated M9 distill.

## Acceptance criteria (reshaped)

1. Repo under git; genesis commit + tagged; history reads clean per-milestone.
2. `pip install -e .` works; package imports nothing outside stdlib.
3. Full test suite green, ≥90% line coverage on `package/boonyard/`, runtime ≤30s.
4. Every CLI command works; every MCP tool from architecture 06 serves correctly.
5. Boonyard's own node runs on the package, MCP-served, with its genesis entry and
   ≥1 week of real journaled use, zero data loss.
6. Wall audit/distill complete (design-seat led); marker entries logged to both nodes.
7. Professor answers the dogfood question in the affirmative, on the record.

---

## Cross-cutting rules (recap — CLAUDE.md governs in full)

- Stdlib-only, append-only, closed column set, soft validation. The four load-bearing
  must-nots; each has an ADR; violating one means you misread the canon — stop, surface.
- Canon docs (CHARTER, ADRs, architecture, glossary, roadmap) are **not yours to
  edit**. Implementation-revealed doc gaps → `discussion` entry on the wall.
- Wall protocol: for now the working journal is the vectorscape wall
  (`nn.vectorscape.uk/sse`). Every session ends with an `implementation` entry. Use tag
  `boonyardnn` (the live thread's tag, entries 84–97 — supersedes the bare `boonyard`
  in CLAUDE.md's earlier example; substring search catches both), plus `phase-1`, the
  milestone (`m1`…`m9`), relevant `adr-NNNN` tags, and your `model:` tag (the
  agent-identity convention applies to your wall writes too — e.g.
  `model:claude-opus-4-8` or whatever you actually are). Thread `related_id` to entry
  95 or to your own prior milestone entry.
- When in doubt: CHARTER → ADRs → wall → `discussion` entry → smallest reversible change.

## Estimated shape

M1–M7: three to five focused sessions (the architecture docs mean the code mostly
writes itself). Gate: Professor's call, async. M8: one session. M9: a week of living in
it. No deadline pressure — the deadline-shaped thing this phase is the *gate discipline*,
not the calendar.
