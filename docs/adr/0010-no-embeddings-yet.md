# ADR 0010 — No embeddings (yet); if added, optional install only

**Status:** Accepted (negative decision — deliberate non-feature)
**Date:** 2026-05-20
**Deciders:** Jacob (Professor), Cowork-Opus, Chat-Opus (who corrected the "Vector" framing in v1.2)
**Supersedes:** —
**Superseded by:** —

## Context

A reasonable question to ask any modern memory-substrate-for-agents product is "where's the vector search?" The intuition is strong: agents work with semantic content, retrieval by similarity is more powerful than retrieval by exact keyword, embedding-based recall is what every other agent infrastructure ships.

The v1.1 implementation appendix framed embedding search as "making VectorScape NN live up to its name." The v1.2 reframe corrected this. Quoting v1.2 §0:

> The "Vector" mistake. I twice framed embeddings as making "VectorScape NN live up to its name." That premise is wrong on two counts and is struck: (1) "Vector" is the geometry, not the NN. The project was PlaneScape (2D grid procgen). D&D owns Planescape, so it was renamed VectorScape and the grid became a 3D xyz matrix — confirmed by the live code (server/universe.py: a 100×100×100 cube, (x,y,z) → SHA-256 → node). "Vector" = the coordinate space. It has nothing to do with neural-net vectors. (2) The NN predates and outlives VectorScape.

So the naming-honesty argument for embeddings is dead. That leaves only the substantive question: is semantic recall worth the cost it imposes?

The cost is significant:

- Breaks ADR-0001 (stdlib-only). No usable embedding model ships in the Python stdlib. Adopting any embedding path means a runtime dep — sentence-transformers (large), sqlite-vec (newer, smaller, but still external), or a hosted API (network + cost + lock-in).
- Adds storage. A 768-dim float32 embedding is ~3KB per entry; a substrate with 100k entries is 300MB of embeddings. Not huge, but no longer "the file is the data."
- Adds compute. Embeddings must be generated on every write. CPU-only generation is slow; GPU adds another dep tier; hosted API adds network round-trip cost.
- Adds a model-choice decision. Which embedding model? When does it get upgraded? What's the migration path when the chosen model is deprecated by its provider?
- Adds a recall-quality calibration burden. Semantic recall returns *something* always; tuning the relevance threshold so the right thing surfaces is a permanent maintenance task.

Against that cost, the value of embeddings has to be measured against what FTS5 already provides: full-text search over content, with FTS5's BM25 ranking and phrase queries. For a substrate where content is typically short (entries are paragraphs, not papers), and where tag-based retrieval handles category queries, FTS5 covers the high-value cases. The remaining gap — "I want entries semantically similar to *this* one, not entries that share keywords" — is real but not load-bearing for the current use cases (PlaneScape dev journal, JRHood operational log, Spore agent coordination).

This ADR locks the conclusion: embeddings are not in the v1 substrate. If they ever ship, they ship as an optional install behind a clearly-marked flag.

## Decision

**The boonyard package does not include embedding-based search.** No `embed`, `vector_search`, `similar_to`, or any equivalent tool exists in the v1 API. The `search_text` tool (FTS5-backed) is the keyword-based search path; `search_by_tag` is the category-based search path; together they cover what the substrate ships with.

**If embeddings are ever added, they ship as an optional extra:**

```
pip install boonyard               # no embeddings, no extra deps
pip install boonyard[semantic]     # embeddings, with the chosen embedding lib as a dep
```

The core package never imports the embedding lib. The optional install adds new tools (`vector_search`, `similar_to`, etc.) that are absent in the core. A node that wasn't created with embeddings enabled remains queryable by FTS5 + tags; adding embeddings to an existing node is a one-time re-index operation.

**The decision to add embeddings is gated on:**

1. **Demonstrated need.** A clear case where FTS5 + tag retrieval is provably insufficient for a real workflow. "It would be cool" is not a case. "I tried to retrieve X and the substrate had X but couldn't find it via keyword or tag" is a case.
2. **Settled model choice.** A model whose API or weights we can commit to for years, not the latest hot release. Drifting model choices means re-embedding everything per upgrade.
3. **Stdlib-only-respecting implementation path.** Probably `sqlite-vec` (the lightweight Rust SQLite extension), which is small enough to be acceptable as an optional dep. If sqlite-vec or equivalent matures and is widely-available, the optional install becomes viable.
4. **Continued FTS5 + tag adequacy assessment.** Reviewed annually or per major release. Embeddings are added only if the answer to "is this still adequate?" is no.

**If added, embeddings are scope-controllable per node.** A user can have some nodes embedded, others not. The schema profile gains an `[embeddings]` section that declares the model in use; the model becomes part of the schema-version-compatibility check.

## Consequences

**Positive:**
- The package stays stdlib-only (ADR-0001) by default.
- Users who don't want embeddings (most users, initially) get the substrate at its simplest and lightest.
- Users who do want them get a clean opt-in with no ambiguity about what they're adopting.
- We avoid prematurely locking to a model choice that ages badly.
- The decision is reversible cheaply — if embeddings prove needed, the optional-install path is ready.

**Negative:**
- Users coming from other agent-memory products will look for vector search and find none. They will either accept the substrate's positioning ("FTS5 + tags is enough for our use cases") or go elsewhere. Acceptable.
- Some real workflows benefit from semantic recall; users with those workflows will be under-served by v1. They get the optional install when it ships, or build their own embedding layer on top of the substrate (the data is in a SQLite file; nothing prevents a third party from running embeddings over `entry.content`).
- The "modern agent infra" tag is harder to claim. Acceptable; the substrate's positioning is "small, owned, durable, multi-seat," not "cutting-edge agent fashion."

**Neutral:**
- If embeddings ship as `boonyard[semantic]`, we never feature-gate them behind a paywall. The optional install is OSS too. (ADR-0006 / "never paywall an algorithm.")

## Alternatives considered

### Ship embeddings in v1, behind a flag

Add `search_text(..., semantic=True)` that uses embeddings when enabled.

**Why rejected:** Adds embedding-dep complexity to the core package even when the flag isn't used (the import has to be conditional, model loading paths have to be tested both ways). The optional-install path is cleaner.

### Ship embeddings in v1, accept the dep

Add sentence-transformers as a runtime dep; embeddings on by default.

**Why rejected:** Breaks ADR-0001. Adds ~1GB of model weights to every install. Slows first-run dramatically. Makes vendoring impractical. The cost is huge, the benefit is uncertain, and the substrate is supposed to be small.

### Ship embeddings via an external API (OpenAI / Voyage / Cohere)

Embed via HTTP call to a third-party API.

**Why rejected:** Adds network dep, latency, and cost per write. Lock-in to a provider whose pricing and API may change. Privacy concern (user content sent to third party). The "no telemetry" promise (ADR-0006) doesn't permit this for default behavior; optional-install with explicit user consent is the path if this ever lands.

### Defer the decision indefinitely; don't decide

Just don't ship embeddings, don't write the ADR.

**Why rejected:** Then every subsequent contributor has to relitigate the question. This ADR makes the negative decision visible and reversible, with the conditions for reversal explicit.

## A note on the temptation

The "but agents really want vector search" argument is strong because it's culturally encoded in everything you read about agent infrastructure. It's worth pausing on why the substrate's use cases don't actually need it:

- **PlaneScape NN:** seats retrieve by `prompt-N`, by `arc-cosmology`, by `recent(entry_type='skill')`. Semantic similarity rarely matters; structural identity (this prompt, this arc) and keyword recall (FTS5 "FUSE AND boot") cover it.
- **JRHood NN:** entries are operational notes tied to specific cases (`case:521-5400610`), specific phases, specific agent runs. Tag namespace lookups are constant-time; semantic similarity over operational notes is mostly noise.
- **Spore NN:** brain/memory/voice agents write structured events; retrieval is "what did I think yesterday at 8am" or "all entries tagged `mood:contemplative`," not "semantically similar."
- **Vectorscape diff layer:** player diffs are queried by coordinate range and player_id, not semantic similarity.

When and if a use case surfaces where FTS5 + tags genuinely fail and embeddings genuinely succeed, the optional-install path is ready. Until then, the substrate stays small.

## References

- CHARTER.md — "What BoonyardNN is not / not a vector database"
- glossary.md — `FTS5`, `extras`
- v1.2 design doc, §0 — the "Vector" correction; original framing of embeddings as a deliberate-later-decision
- ADR-0001 — stdlib-only (the constraint embeddings would violate)
- ADR-0006 — OSS / SaaS split, "never paywall an algorithm" (which applies to a future optional install too)
- architecture/06_mcp_surface.md — current search tools (FTS5-based, tag-based)
