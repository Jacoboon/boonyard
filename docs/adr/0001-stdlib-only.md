# ADR 0001 — Stdlib-only for the boonyard package

**Status:** Accepted
**Date:** 2026-05-20
**Deciders:** Jacob (Professor), Cowork-Opus
**Supersedes:** —
**Superseded by:** —

## Context

The boonyard package is the OSS heart of BoonyardNN. It is the thing that gets `pip install`ed, vendored, embedded, copied around, run on Windows, run on Linux, run on a Raspberry Pi, run in CI, run inside other projects' build steps, and dropped into any number of unknown future environments. The product story rests on this package being trivially adoptable.

Three constraints pull in the same direction:

1. **Portability.** The substrate has already lived inside ≥5 of Jacob's projects (PlaneScape, JRHood, Spore, and at least three earlier ports). Each project had its own Python version, OS, build pipeline, and whatever the surrounding code was already depending on. The friction of "now also install X, Y, Z" is the friction that historically prevents the substrate from showing up everywhere it could.

2. **Vendorability.** A user should be able to copy the package folder directly into their project (`_dev/boonyard/`) and have it work, no `pip install` step required. This is genuinely useful — it means the substrate can be embedded in projects whose dependency policies are strict, in air-gapped contexts, in projects that ship to environments without Python package managers, and in the rare cases where the lifecycle of the host project is incompatible with the lifecycle of the substrate's release cadence.

3. **Supply chain.** Every external dependency is a supply-chain attack surface, a version-conflict risk, a license-compatibility check, a maintenance follow-along. For an OSS substrate that intends to be widely embedded, the cost of each dependency compounds over time. The cheapest dependency is the one not added.

The v1.2 design doc names this rule explicitly ("No external dependencies. Keep it that way unless there's a real reason"). The live NN, the JRHood NN, and the PlaneScape NN have all been built and operated without runtime deps, and the absence has never caused a problem we couldn't solve with the stdlib.

Python's stdlib happens to provide everything the substrate's primitives need: `sqlite3` for storage; FTS5 inside the bundled SQLite for full-text search; JSON1 inside the bundled SQLite for the extras column; `tomllib` (3.11+) for the schema profile; `argparse` for the CLI; `http.server` and `urllib` for the simplest possible HTTP layer; `secrets`, `hashlib`, `hmac` for any auth primitive. There is nothing the substrate needs that is not already in the box.

## Decision

The boonyard package has **zero runtime dependencies**. The `pyproject.toml`'s `dependencies` list is and remains empty. The package is importable on any Python 3.11+ install with no further setup.

Test-only and dev-only dependencies (pytest, ruff, mypy if we want it) are fine because they don't run inside user environments — but even those are kept minimal, and the test suite must remain runnable using only `python -m unittest` as a fallback so that "I want to verify boonyard works in my environment" never requires installing anything.

This rule applies to the **package only**. The SaaS layer (the web service that runs boonyardnn.com) is allowed to depend on whatever it needs (Flask/FastAPI, a web framework, cloudflared, etc.). The SaaS is a separate deployment that *uses* the package; the package does not import any SaaS code. See ADR-0006.

## Consequences

**Positive:**
- The package is trivially vendorable. `cp -r boonyard/ my_project/_dev/` is a supported installation method.
- New project adoption is one decision (use it or don't), not three (install it, resolve conflicts, audit the deps).
- Supply-chain footprint is exactly the size of the Python interpreter the user already trusts.
- Version-conflict bugs are impossible — there are no versions to conflict with.
- Test-in-isolation is trivial; the test suite has nothing to mock that the package brought in.

**Negative:**
- We write more code ourselves. Tag parsing, simple HTTP for the MCP server, basic auth primitives — all hand-rolled. The cost is bounded because the substrate is small.
- No pydantic-style declarative validation. We get the same effect with light hand-written validators in `boonyard.log`.
- No SQLAlchemy. Queries are raw SQL with parameter binding. The full query surface is also small; this is fine.
- **Embeddings are not available by default and remain out of scope.** Any reasonable vector-search path (sentence-transformers, sqlite-vec, an embeddings API) requires a runtime dep. If we ever add semantic search, it ships as an optional install (`pip install boonyard[semantic]`) and is never required by the core. See ADR-0010.
- The MCP server inside the package uses `http.server`, which is acceptable for single-tenant and embedded use but does not scale. The hosted SaaS at boonyardnn.com runs a separate, dependency-using web layer in front of the package. See architecture 06.

**Neutral:**
- Python 3.11+ requirement (for `tomllib` and modern type-hint syntax). Acceptable; 3.11 is widely available on every target platform as of 2026.

## Alternatives considered

**Allow pydantic for validation.** Tempting because validation is exactly the kind of code that pydantic eliminates. Rejected because the substrate's validation surface is small (six core columns plus tag format plus optional schema-profile constraints), and pydantic's value increases with the complexity of the schema being validated. We are deliberately not increasing that complexity. Hand-rolled validators in `boonyard.log` cost ~40 lines.

**Allow SQLAlchemy for the data layer.** Considered for the same "less hand-written SQL" reason. Rejected because the substrate's schema is fixed (immutable core + JSON extras), the queries are few and well-known, and ORM machinery would obscure the operational properties we care about (FTS5, expression indexes, ATTACH-DATABASE-based aggregation) more than it would help. Raw SQL is honest here.

**Allow a small ergonomics dep like `rich` for the CLI.** Rejected for the vendoring story: a vendored copy of boonyard with a transitive dep on `rich` is no longer vendorable. The CLI uses plain `print` with simple formatting. Anyone who wants prettier output can wrap the Python API themselves.

**Allow a web framework (Flask / FastAPI) for the package's own MCP server.** Rejected because it forces a runtime dep on every install, including the embedded / vendored cases where the user does not want any HTTP at all. The package ships a `http.server`-based MCP server suitable for local single-tenant use; the SaaS layer (separate codebase, allowed to depend on Flask or whatever) handles multi-tenant production HTTP. See ADR-0006 and architecture 04.

**Reverse the policy: depend freely, just keep deps small.** This is the default policy of most Python packages and it works fine for most of them. Rejected here because the substrate's adoption pattern is fundamentally different — it lives *inside* other projects rather than alongside them, and the friction it adds is the friction of all those host projects combined. The unusual constraint reflects the unusual deployment shape.

## References

- v1.2 design doc (`PlaneScape/_dev/visions/NN Fiuture/NN_upgrade_phase0_conventions_and_boonyard_reframe_v1.2.md`), §3 "Stdlib-alignment note"
- CHARTER.md — "Load-bearing beliefs"
- ADR-0006 — OSS core + SaaS split (why the SaaS is allowed to depend on things)
- ADR-0010 — No embeddings (yet)
