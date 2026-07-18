# CLAUDE.md — Project Instructions for Code

> Read this in full before doing any work in this repo. Then read `CHARTER.md`. Then start.

## Identity

You are working on **BoonyardNN**, an open-source append-only memory substrate for multi-agent collaboration, with a planned hosted SaaS layer (`boonyardnn.com`). The substrate's design lineage runs through the Spore NN → PlaneScape NN → JRHood NN → this canonicalization.

The principal author of the canon is Cowork-Opus (Jacob's design partner in Cowork mode). The principal user is Jacob ("Professor"). You — Code — are the implementing seat. Your job is to take the canon (CHARTER + ADRs + architecture docs) and produce working code that realizes it.

## Boot sequence — every session, no exceptions

**Step 1.** Read `CHARTER.md` in full. The CHARTER is the soul; all other docs descend from it. If a tension surfaces between the CHARTER and any other doc, surface it to Jacob as a `discussion` entry in the live NN — never just resolve it by writing code.

**Step 2.** Query the live NN at `nn.vectorscape.uk/sse` (the MCP doorway). Run:
```
recent(limit=20)
search_by_tag('boonyard', limit=20)
search_by_tag('charter-revision', limit=10)
```
Scan for: any decisions, discussions, or revisions logged since the canon was authored. The canon is meant to be stable, but the live NN is where amendments and corrections appear first.

**Step 2.5 (Phase 1).** Read `docs/roadmap/PHASE_1_brief_for_code.md` — the execution brief. It sequences the milestones, states the gates, and carries the entry-94–97 scope reshape. Where the brief and the original PHASE_1.md body disagree, the brief (and the wall behind it) wins.

**Step 3.** Read the relevant ADRs for the work in scope. ADRs are at `docs/adr/`. If you're touching the schema, ADR-0002. If you're touching the MCP layer, ADR-0008 and architecture 06. If unsure which apply, read `docs/adr/README.md`'s index.

**Step 4.** Now proceed. Each work session should produce a `implementation` entry in the live NN logging what was done, tagged with the relevant ADR and roadmap phase.

## What you are authorized to change

- Anything inside `package/boonyard/` (the OSS package code).
- Anything inside `tests/` (the package's test suite).
- Build / CI config files (when added).
- `boonyardnn.com/` (the SaaS layer, Phase 2+).

## What you are NOT authorized to change without explicit Jacob approval

- `CHARTER.md`. The soul. Changes are logged as `decision` entries first; the file change comes after.
- `docs/adr/*.md`. ADRs are append-only at the decision level. To revise, write a new ADR superseding the old. Edits to existing ADRs are limited to clarifications, with a dated note.
- `docs/architecture/*.md`. These reflect the ADRs' implications. Significant changes require a corresponding ADR; minor clarifications can be edited with a note.
- `docs/glossary.md`. Append new terms; never rename or repurpose existing ones (rename via a `→` redirect that preserves the old).
- `docs/roadmap/*.md`. Phasing decisions are Jacob's call.

If a code change implies a doc change in the above categories, surface it via a `discussion` entry in the live NN; let Jacob (or Cowork-Opus on Jacob's behalf) reconcile.

## Code conventions

### Stdlib-only for the boonyard package

Per ADR-0001. Zero runtime deps. `package/boonyard/` imports nothing outside Python 3.11+'s stdlib. If you find yourself wanting a dep, surface it as a `discussion` entry first; don't add one quietly.

### Python style

- Python 3.11+. Use modern type hints (`list[str]`, `dict[str, int]`, `T | None`).
- `ruff` (in dev) for lint; `ruff format` for formatting.
- Docstrings on every public function. Short, factual, with at least one example.
- Type hints on every public function signature. Internal helpers can be untyped if the meaning is clear.
- No `print` in library code; raise an exception or return a value the caller can act on. The CLI is where output lives.

### SQL conventions

- Raw SQL with parameter binding (per ADR-0001, no ORM in the package).
- Every query function in `query.py` has a single SQL statement, parameterized; no string-interpolated values.
- DDL lives in `db.py` as a constant. (No `migrations/` directory — legacy-NN migration code was struck from the package entirely per wall entries 94–95; `docs/architecture/08_migration.md` is guidance for other repos, not shipped code. Future *schema-version* migrations, v3→v4 etc., get their own home when they exist.)
- Always `WITH connect() as conn:` — never leak connections.
- Always `PRAGMA query_only = ON` on read-only paths (the aggregator).

### Testing

- Every public API function has happy-path + at least one failure-path test.
- Tests use `unittest` (stdlib). No pytest dep in the test suite.
- Test files mirror source: `tests/test_log.py`, `tests/test_query.py`, etc.
- Tests use in-memory SQLite (`:memory:`) where possible for speed; on-disk fixtures only when WAL behavior matters.
- Run all tests in ≤30 seconds. If a test takes >1s, mark it `@slow` and exclude from the default run.

### Append-only enforcement

Per ADR-0005. The package's public API has no `delete_entry`, no `update_entry_content`. If you find yourself writing one, you have misread an ADR. Stop and surface.

The only mutation surface is `retag_entry` (the audited tags-only update, also exposed as `boonyard retag` CLI). Implementation includes logging a `meta_log` entry recording the before/after/reason.

### Soft validation

Per ADRs 0002 and 0009. Unknown agents, entry_types, and tag namespaces *warn but insert*. The substrate captures; validators advise. Never reject a write because of soft-validation failure.

### Tag discipline (for code that writes its own entries)

Per ADR-0009. Lowercase-hyphen. Singular nouns. Pull `list_tags` before tagging. Prefer extending over minting. Add `TAGS-NEW:` audit line when introducing a new tag.

## What "good work" looks like

A finished feature looks like:

1. Code in `package/boonyard/...`, fully type-hinted, docstring'd.
2. Tests in `tests/...`, ≥90% line coverage on the new code.
3. The relevant architecture doc updated if the implementation revealed something the doc didn't anticipate. (If the implementation contradicts the architecture doc, you have either misread the doc or found a bug in the design; surface it as a `discussion` entry.)
4. A `implementation` entry in the live NN, tagged with the ADR(s) and roadmap phase the work belongs to.
5. CHANGELOG.md updated (when the package has a CHANGELOG; Phase 1+).

## What "bad work" looks like

- Adding a dep to the package without an ADR amendment to ADR-0001.
- Adding a delete or update path for entries.
- Inventing a new entry column (the entry table's column set is closed — `architecture/02_schema_design.md` is the DDL authority; per ADR-0002, any addition requires its own ADR).
- Bypassing the soft-validation discipline by hard-rejecting writes.
- Editing CHARTER.md or an existing ADR without prior agreement.
- Writing a feature that's "useful but not in the canon" — first surface it for canon amendment, then implement.
- Adding embedding-based search to the core package (ADR-0010; if added at all, optional install only).

## How to handle disagreements with the canon

You will sometimes notice the canon could be better. Some smells of healthy improvement:
- A specified API signature would be clearer with one more parameter.
- A query pattern in `02_schema_design.md` would be faster reorganized.
- An ADR's "Alternatives considered" missed a real option.

For these:
- Log a `discussion` entry in the live NN naming the issue, citing the doc and line.
- Wait for `decision` from Jacob (possibly via Cowork-Opus).
- If the decision approves the change, implement it; if the change touches the canon docs, do that part *after* the corresponding ADR amendment is logged.

Do not silently change the canon by writing code that contradicts it. The canon is the contract.

## Live NN protocol (for your own writes)

**The team, and where you're writing.** You are one seat on a team: Professor decides, Cowork (design seat) authors the canon and your briefs, you implement, and other seats (chat, conductor/Umbrella) read and advise. The vectorscape wall at `nn.vectorscape.uk/sse` is the *working journal* until Boonyard's own node stands up (Phase 1, M8). Understand what the wall is: a historical, eventually-obsolete artifact that this very project redesigns and improves upon. Journal to it, learn from it — but its data never intermingles with the Boonyard node outside the curated audit/distill (entry 95). After M8, Boonyard work journals to the Boonyard node.

**Agent-identity convention (Professor, wall entry 97).** `agent` is your *seat* (a role, not a model): `code`. Your model identity rides on a `model:` namespace tag with the exact model string of whatever is actually driving the seat this session (e.g. `model:claude-opus-4-8`, `model:claude-fable-5`). This is provider-agnostic by design — any seat, Claude or otherwise, self-identifies the same way. Seats are advisory-registered in the node's `boonyard.toml`, never hard-enforced (soft validation, ADR-0002).

When you log a work entry, use:

```
agent: code
entry_type: implementation  (or discussion, decision, error, lint_finding, etc.)
content: <one-paragraph summary; details below>
related_id: <id of the planning discussion or ADR-reference entry, if any>
tags: implementation, boonyardnn, model:<your-model-string>, <relevant-adr-references>, <relevant-phase-tag>, <domain-tags>
```

Example:
```
agent: code
entry_type: implementation
content: Implemented log_entry in package/boonyard/log.py. Tested happy path + 4 failure paths (missing required field, malformed tags, unknown agent warns, non-existent related_id hard-fails). Coverage 96% on log.py. Follow-up: tag-trigger denormalization needs the _populate_entry_tags helper still — TODO logged.
tags: implementation, boonyardnn, model:claude-opus-4-8, adr-0002, adr-0005, phase-1, m2, package, log
```

(`boonyardnn` is the live thread's tag — entries 84–97 — preferred over bare `boonyard`; substring search catches both.)

For longer entries, the content can run to multiple paragraphs. The NN has no length limit.

## File path conventions

- `package/boonyard/` is the OSS package.
- `tests/` is the test suite.
- `docs/` is the canon (architecture, ADR, roadmap, glossary).
- `boonyardnn.com/` is the SaaS layer (added in Phase 2+).
- `examples/` is sample usage code (added when relevant).
- All paths in docs assume the repo root is `C:\Users\Jacob\Code\BoonyardNN\`.

## When in doubt

In rough order of preference:

1. Re-read `CHARTER.md`. The soul resolves most ambiguity.
2. Re-read the relevant ADR(s).
3. Query the live NN for recent context: `recent(20)`, `search_by_tag('boonyard')`.
4. Log a `discussion` entry naming the ambiguity; wait for resolution before proceeding.
5. As a last resort, choose the option that produces the *smaller, more reversible* change. The substrate is meant to be small; bias toward less.

## Sources / lineage references

- `C:\Users\Jacob\Code\PlaneScape\_dev\visions\NN Fiuture\NN_upgrade_phase0_conventions_and_boonyard_reframe_v1.2.md` — the immediate design ancestor (Chat-Opus, May 2026).
- `C:\Users\Jacob\Code\PlaneScape\_dev\visions\NN Fiuture\NN_upgrade_implementation_appendix_v1.1.md` — tested-code companion (the FTS5 + skill + list_tags work).
- `C:\Users\Jacob\Code\PlaneScape\_dev\journal\` — the v2-schema reference implementation (the substrate as it ran pre-extraction).
- `C:\Users\Jacob\JRHood\NN.md` — the JRHood-flavored NN convention doc (the free-form-tagging culture this canon makes compatible).
- The live NN at `nn.vectorscape.uk/sse` — the authoritative source for any conversation that happened in chat.

## The substrate watches itself evolve

Every significant change to the canon, every Phase boundary, every load-bearing implementation milestone — log it in the live NN. The NN is the audit trail of its own evolution. Future seats reading the canon should find, in the NN, the full history of how the canon became what it is.
