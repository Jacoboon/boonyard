# Glossary

Locked vocabulary for BoonyardNN. If a term in any other doc has a definition here, this one wins. New terms get added by appending, alphabetically. Renames get a `→` redirect and the original term stays — the substrate's append-only ethos applies to its own vocabulary.

---

**aggregator** — A reader process that opens multiple node databases at once (via SQLite `ATTACH DATABASE`, read-only) and unions their entries into a single query surface. The mechanism by which the over-many / Umbrella mode is realized. See ADR-0003.

**agent** — The named actor that wrote an entry. Stored in the `agent` column. Free-form by default; constrained by the node's schema profile if one is configured. Examples from live NNs: `opus`, `code`, `cli`, `dispatch`, `professor`. Synonymous with **seat** in most contexts; "seat" is more often used when emphasizing the role-identity aspect, "agent" when emphasizing the data-column aspect.

**append-only** — The substrate's structural guarantee: entries are inserted and never updated or deleted. Corrections happen by writing new entries with `related_id` pointing at the original. Skills evolve by root-anchored revisions. Deprecation happens via tombstone entries. See ADR-0005.

**boonyard** (lowercase) — The OSS Python package. The thing you `pip install boonyard` or vendor into your project's `_dev/boonyard/` folder. Stdlib-only. The substrate's reference implementation.

**BoonyardNN** (camel-case) — The whole product / system, including the package, the SaaS, the canon, the community. When you see this capitalization, it's the umbrella term.

**boonyardnn.com** — The hosted SaaS domain. Where a user can sign up, spawn nodes without running their own server, and get a hosted MCP endpoint per node. Runs the same boonyard package under the hood. See ADR-0006, ADR-0007.

**Code** — A Claude Code instance, or any implementing agent that converts the canon into running source. In the live NN's vocabulary, "Code" writes entries under `agent='code'`. In this repo's vocabulary, "Code" is the principal executor of work designed in the canon.

**core columns** — The five columns of the `entry` table that every node has, every version of the schema preserves, and no project can rename or remove: `agent`, `entry_type`, `content`, `related_id`, `tags`. Plus the implicit `id` (primary key) and `timestamp`. See ADR-0002, architecture 01, architecture 02.

**Cowork-Opus** / **Cowork** — Opus operating in Cowork mode. One of the named seats in the live NN. Architect/orchestrator role; writes markdown, designs prompts, runs design conversations. Does not write source.

**Chat-Opus** — Opus operating in the consumer Claude app. A different seat from Cowork-Opus, with read/write access to the same NN. Authored the v1.1 implementation appendix and v1.2 Boonyard reframe.

**dogfood** (verb) — To use BoonyardNN on Jacob's own projects before opening it to anyone else. The first phase's only proof of value. See `roadmap/PHASE_1.md`.

**entry** — The irreducible unit. One row in the node's `entry` table. Has an `id`, a `timestamp`, an `agent`, an `entry_type`, `content`, an optional `related_id`, and optional `tags`. The whole BoonyardNN substrate exists to keep entries elegant and unbreakable. See architecture 01.

**entry_type** — The kind of entry — `prompt`, `decision`, `discussion`, `implementation`, `lint_finding`, `verification`, `vision`, `error`, `note`, `skill`. Stored in the `entry_type` column. The set is soft-validated by default (unknown types warn but insert anyway); a node's schema profile can declare its own allowed set. See ADR-0004 for skill specifically.

**extras** — An optional JSON column on the `entry` table, enabled per-node via the schema profile, for typed custom fields a project wants stored beyond tags. Example: Vectorscape's `(x, y, z)` diff coordinates. Queryable via SQLite's `json_extract`. Indexable via expression indexes. See ADR-0002.

**FTS5** — Full-text search version 5, the SQLite virtual-table extension bundled with Python's stdlib SQLite. Powers `search_text` over the `content` column. Index is maintained by INSERT/UPDATE/DELETE triggers on the `entry` table. See architecture 02.

**in-project mode** — One of the three usage modes. The boonyard package is embedded inside a project's codebase (vendored or pip-installed) and used as that project's own append-only event substrate — not just for AI agent journaling, but for any append-only event log. Vectorscape's player-diff layer is the worked example. See architecture 00.

**Jacob** / **Professor** — The user at the top of this canon. User zero. The first audience for every BoonyardNN feature. "Professor" is the long-standing role name from the Opiifecta naming convention in the live NN.

**list_tags** — The tag-menu reader. Returns every unique tag in the node with its usage count, sorted most-used-first, optionally prefix-filtered or grouped by top-level category (the text before the first hyphen). The discovery mechanism that prevents tag-vocabulary forking. Added in v1.1. See ADR-0009.

**live NN** — The currently-running journal at `nn.vectorscape.uk/sse`. Where Cowork-Opus / Chat-Opus / Code / Professor all write entries during PlaneScape work. Source-of-truth for design conversations across seats. To be migrated into a Boonyard node in Phase 1.

**MCP** — Model Context Protocol. The protocol AI agents use to call external tools. BoonyardNN exposes a node via an MCP server with tools like `recent`, `log_entry`, `search_by_tag`, `list_tags`, etc. The "MCP doorway" is how AI seats reach the substrate. See architecture 06.

**MCP doorway** — The colloquial term for a node's MCP endpoint. Shipped in May 2026 (live journal entry 77). Currently single-tenant at `nn.vectorscape.uk/sse`; multi-tenant version is Phase 2 work.

**node** — One BoonyardNN instance. Concretely: one SQLite database file plus one `boonyard.toml` schema profile. Conceptually: the unit of scope, the unit of ownership (in SaaS), the unit of export/backup, the unit of MCP endpoint. A node belongs to one project (per-project mode) or is embedded inside one (in-project mode). A user can own many nodes; an aggregator can read across many. See ADR-0003, ADR-0007.

**Opi** / **Opiifecta** — The four-seat team pattern from PlaneScape (Code + Cowork-Opus + Chat-Opus + Professor), all writing into one shared NN. The pattern BoonyardNN is shaped to serve and generalize.

**over-many mode** / **Umbrella mode** — One of the three usage modes. A reader that opens many nodes at once and answers queries across all of them. Implemented by the aggregator. The user's personal cross-project view. See architecture 03.

**per-project mode** — One of the three usage modes. Each of a user's projects owns its own dedicated node. The default and most common shape. PlaneScape's NN is per-project. JRHood's NN is per-project. See architecture 00.

**Project-Six trap** — The pattern named in live journal entry 75: building a sixth meta-project to serve five existing projects, instead of finishing the five. Spending energy on the meta-tool while the things the meta-tool exists to serve languish. BoonyardNN itself is at high risk of becoming a Project-Six instance; the dogfood pact in CHARTER is the explicit guardrail.

**related_id** — The `entry` column that points at another entry's `id`, forming a thread. `get_thread(root_id)` returns the root plus all entries with `related_id = root_id`. Important: only one level deep. Skills version themselves by **root-anchoring** every revision to the original, so the whole lineage stays visible in one `get_thread` call. See ADR-0004.

**root-anchored revision** — A skill revision whose `related_id` points at the *original* skill entry, not at the immediate predecessor revision. Necessary because `get_thread` is one level deep — chaining `v3 → v2 → v1` would silently drop v3 from `get_thread(v1)`. The convention is locked in v1.1 and re-locked in this canon. See ADR-0004.

**SaaS** — Software as a Service. In BoonyardNN context, the hosted offering at boonyardnn.com: user accounts, node spawning, hosted MCP endpoints, web dashboard, optional billing tiers. The OSS package is what runs underneath the SaaS. See ADR-0006.

**schema profile** — The `boonyard.toml` config file that sits next to each node's `journal.db`. Declares the node's name, schema version, allowed agents, allowed entry_types, reserved tag namespaces, whether the extras column is enabled, and which extras fields are hot-indexed. The per-project customization layer. See ADR-0002.

**schema_version** — A numeric column in the `meta` table of every node, indicating which version of the BoonyardNN core schema the node was last migrated to. Drives idempotent upgrade scripts. v1 = the original PlaneScape `_dev/journal/` schema. v2 = the FTS5 + skill-as-entry-type + `list_tags` set introduced in the v1.1 implementation appendix. v3 = the BoonyardNN canon schema with `extras`, `entry_tag` companion table, schema profile.

**scope** — A query parameter introduced in v1.2 that says which node(s) a read should run against. In single-node mode, scope is implicit. In aggregator mode, scope is explicit: a list of node identifiers, or `all`. See ADR-0003.

**seat** — Synonym for agent when emphasizing the role-identity meaning. "The Cowork-Opus seat just wrote entry 79." The four canonical seats around the PlaneScape NN are Cowork, Chat, Code, Professor; future BoonyardNN nodes can have any seats they want.

**skill** — A first-class entry_type for reusable how-tos a seat writes after solving something non-obvious, so a future seat retrieves the answer instead of re-deriving it. Has a templated content shape (SKILL/WHEN/STEPS/GOTCHAS/SOURCE). Retrieved via `recent(entry_type='skill')` — never via tag, because tag search is substring-LIKE and pollutes. See ADR-0004.

**substrate** — The whole BoonyardNN system viewed as foundational infrastructure for something else. Used when contrasting BoonyardNN with the agents / projects / users that build on top of it. "Spore is built on the substrate; PlaneScape is built on the substrate; you can build on the substrate."

**tag** — A free-form lowercase-hyphen string on an entry, comma-separated in the `tags` column. Tags are how categories surface in the NN. The mandatory type tag (matching `entry_type`) plus any domain tags. New tags get a `TAGS-NEW:` audit line in the entry content. See ADR-0009.

**tag namespace** — A tag prefix that encodes a typed reference, like `case:521-5400610` (JRHood's case_number) or `player:42` (Vectorscape's player_id). Discoverable via `list_tags(prefix='case:')`. The first-line answer to "I have a project-specific reference but I don't want a schema change." Schema profile declares reserved namespaces. See ADR-0002, ADR-0009.

**tag tree** — The view `list_tags(tree=True)` returns: tags grouped by the text before the first hyphen. Surfaces ontology forks (e.g. a stray plural splits `skill:` and `skills:` into separate categories). The empirical case for the singular-noun rule. See ADR-0009.

**tombstone** — A final entry written to mark a skill, decision, or other artifact as deprecated. Conventionally tagged with `<thing>-deprecated`. The append-only substitute for deletion. See ADR-0005.

**Umbrella** → see **over-many mode**.

**user zero** — Jacob. The first and only paying customer of BoonyardNN for an undefined period of time. The dogfood pact: BoonyardNN earns its keep on user zero's own projects before opening to anyone else. See CHARTER, `roadmap/PHASE_2.md`.

**v1.1** / **v1.2** — The implementation appendix and Boonyard reframe documents, respectively, in `PlaneScape/_dev/visions/NN Fiuture/`. The design ancestors of this canon. v1.1 supplies the tested FTS5 + list_tags + skill code; v1.2 supplies the extraction direction and the scope-model recommendation.

**vendoring** — Copying the boonyard package folder directly into a project's source tree (as opposed to pip-installing). Made possible by the stdlib-only rule. Equivalent in correctness to pip install; preferred when a project wants total control over its dependencies.

**Vectorscape NN** — The first MCP-exposed instance of the NN, currently at `nn.vectorscape.uk/sse`. The live NN that Cowork-Opus / Chat-Opus / Code / Professor write into during PlaneScape work. Will be migrated to a Boonyard node in Phase 1.
