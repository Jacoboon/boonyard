# Contributing to BoonyardNN

Thanks for looking. Read this before opening a PR — it will save us both time.

## Set expectations first

BoonyardNN is **small on purpose**. It is not trying to become a platform, and it is not
staffed like one. It is maintained by one person at a hobby cadence, alongside several other
projects, and it was built to earn its keep across those projects rather than to win a
feature comparison.

The practical consequence: **most feature requests will be declined, and that is the design
working, not the maintainer being unhelpful.** [CHARTER.md](CHARTER.md) says it plainly —
"the substrate is small, the discipline is everything… each addition is a tax forever." If a
proposal adds surface area, the default answer is no, and the burden is on the proposal to
show the absence costs more than the presence.

Bug reports, correctness fixes, portability fixes, test coverage, and documentation
corrections are welcome without reservation.

## Licensing — inbound = outbound

By submitting a contribution, you agree it is licensed under the
[Apache License 2.0](LICENSE) — the same terms you received the code under. There is no
separate CLA to sign. Your contributions are licensed under the same license as the code you
are contributing to, which is what "inbound = outbound" means.

You keep your copyright. You are granting the project the right to use and redistribute your
work under Apache 2.0, including the patent grant in section 3.

## The hard constraints

These are locked by ADRs. A PR that violates one will be declined regardless of how good it
is otherwise. If you think an ADR is wrong, say so in an issue and make the argument — that
is a legitimate and welcome move. Silently working around one is not.

| Constraint | Where it's decided |
|---|---|
| **Zero runtime dependencies in the package.** SQLite, FTS5 and JSON1 ship inside Python. Nothing else gets added. | [ADR-0001](docs/adr/0001-stdlib-only.md) |
| **The `entry` table's column set is closed.** Project-specific data goes in namespaced tags or the JSON `extras` column — never a new column. | [ADR-0002](docs/adr/0002-fixed-core-plus-tag-namespaces-plus-json-extras.md) |
| **No delete path. No update path.** Corrections are new entries referencing old ones. Bad entries are tombstoned, not removed. | [ADR-0005](docs/adr/0005-append-only-no-deletes.md) |
| **One node = one SQLite file.** The aggregator opens many, read-only. | [ADR-0003](docs/adr/0003-db-per-node-plus-aggregator.md) |
| **Soft validation.** Unknown agents and entry types warn; they do not hard-reject a write. Capture-don't-crash. | [ADR-0002](docs/adr/0002-fixed-core-plus-tag-namespaces-plus-json-extras.md) |
| **No embeddings in the default package.** They break the stdlib-only rule and they are not what this is. | [ADR-0010](docs/adr/0010-no-embeddings-yet.md) |
| **The package phones home to nothing.** No update checks, no telemetry, no version beacon. | [ADR-0006](docs/adr/0006-oss-core-saas-freemium.md) |

## What a good PR looks like

1. **One concern per PR.** If the title needs an "and," it is two PRs.
2. **Tests.** New code carries tests; the suite runs on stdlib `unittest` with no plugins
   required (`python -m unittest discover tests`), and also under `pytest` if you have it.
   Aim for ≥90% line coverage on what you touched.
3. **`ruff check` and `ruff format` clean.** That is the whole lint story; `pip install
   boonyard[dev]` gets you ruff and nothing else.
4. **The relevant architecture doc updated** if the implementation revealed something the
   doc did not anticipate. If your implementation *contradicts* an architecture doc, you have
   either misread it or found a design bug — open an issue rather than quietly diverging.
5. **No new files at the repo root** without a reason stated in the PR description.

## Docs you should not edit casually

`CHARTER.md`, `docs/adr/*.md`, and `docs/glossary.md` are canon.

- The **charter** changes only when reality has outgrown it, and the change is argued before
  it is written. If you find yourself rewriting the charter to justify a feature you want,
  the smell is the rewrite, not the charter.
- **ADRs are append-only at the decision level.** To reverse one, write a new ADR that
  supersedes it and update both files' `Superseded by:` / `Supersedes:` headers. Edits to an
  existing ADR are limited to clarifications, with a dated note.
- The **glossary** is append-only. Add terms; never rename or repurpose an existing one. If a
  term must change, add the new one and leave a `→` redirect that preserves the old.

Architecture docs and the roadmap are more editable, but significant changes to architecture
should have a corresponding ADR behind them.

## Reporting a bug

Include the Python version, the OS, whether the node is local or served over MCP, and the
smallest input that reproduces it. If it involves data loss or a corrupted node, say so in
the first line — that class of bug outranks everything else here, because the entire promise
of this project is that the wall does not forget.

**Do not paste node contents into an issue.** Your entries are yours; reproduce with a fresh
throwaway node instead.

## Security

If you find something that lets one node read or write another, that leaks a bearer key, or
that lets a crafted entry payload escape its node, do not open a public issue. Mail the
address on the GitHub profile of the repository owner with "boonyard security" in the
subject, and give it a few days before disclosing.

## A note on the shape of this project

BoonyardNN was extracted from a working system, not designed in a vacuum — it began as a
journal pattern inside one project, became a multi-seat shared journal inside another, and
was formalized here after roughly a year of load-bearing use. Most of what looks like an odd
constraint is a scar. If a rule seems arbitrary, there is usually an ADR explaining which
failure produced it, and reading that ADR is the fastest way to have a productive argument
about it.
