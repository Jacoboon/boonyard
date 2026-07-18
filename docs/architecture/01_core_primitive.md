# Architecture 01 — The Core Primitive

> Entry + tags = memory. The rest is plumbing.

## What an entry is

An **entry** is one row in the `entry` table of a node's SQLite database. It is the irreducible unit of the substrate. Everything BoonyardNN does — storing, querying, threading, aggregating, exporting, replicating — operates on entries.

An entry has eight fields — five core ones the writer chooses, two auto-managed administrative ones, and one optional structured one:

| Field | Type | Required? | Layer | Purpose |
|---|---|---|---|---|
| `id` | INTEGER | auto | administrative | The row's primary key. Stable, monotonically increasing, never reused. |
| `timestamp` | DATETIME | auto | administrative | When the entry was written. UTC. Default `CURRENT_TIMESTAMP`. |
| `agent` | TEXT | yes | core | Who wrote it. The named seat / actor. |
| `entry_type` | TEXT | yes | core | What kind of entry it is. `note`, `decision`, `skill`, etc. |
| `content` | TEXT | yes | core | The body. Free-form text. Indexed by FTS5. |
| `related_id` | INTEGER | no | core | Pointer to another entry's `id`, forming a thread. |
| `tags` | TEXT | no | core | Comma-separated labels. Indexed via `entry_tag` companion table. |
| `extras` | TEXT | no | optional | JSON blob for structured custom fields. Only used if the schema profile enables it. |

The **five core fields** (`agent`, `entry_type`, `content`, `related_id`, `tags`) are what CHARTER and the glossary call "the core columns" — they're load-bearing, they're what the writer composes, and they're immutable across every node forever (ADR-0002). The two administrative fields (`id`, `timestamp`) are the substrate's bookkeeping; the writer doesn't supply them and the substrate guarantees them. The one optional field (`extras`) is the structured-custom-data escape valve, enabled per-node by the schema profile when needed.

Together these eight fields cover every legitimate "what does this entry need to express" case the substrate has encountered across PlaneScape, JRHood, Spore, Vectorscape, and the prior NN ports. Project-specific data lives in tags, in `extras`, or both. Never in additional columns.

## What each field does

### `id`

Autoincrementing integer. The substrate never reuses an id; the autoincrement guarantee is what `related_id` references can rely on. Even if an entry is conceptually "obsolete," its id is permanent (entries are never deleted per ADR-0005).

### `timestamp`

UTC datetime stamped at INSERT time. The `recent` reader's primary sort. Timezone handling is the host's concern; the substrate stores UTC and lets readers localize on display.

### `agent`

The named seat that wrote the entry. The string is whatever the seat chooses to call itself; the schema profile may declare an `allowed` set (soft-validated, ADR-0002). The PlaneScape NN's canonical agents are `code`, `opus`, `professor`; JRHood adds `cli`, `dispatch`, `scraper`, `lookup`, `letter`, etc.

`agent` is the primary attribution layer. Every entry is *by* someone. Anonymous writes are rejected at the API layer (the `agent` column is `NOT NULL`).

### `entry_type`

The kind of entry. The default `allowed` set (soft-validated) is:

- `prompt` — a prompt or directive given to a seat
- `implementation` — a record of work done
- `decision` — a choice with rationale (often paired with an ADR)
- `discussion` — exploratory back-and-forth
- `lint_finding` — a noted issue, code smell, observation
- `verification` — a confirmation that something was tested or holds
- `vision` — a future-looking direction, longer than a note
- `error` — a recorded failure or incident
- `note` — the catch-all for anything that doesn't fit the others
- `skill` — a reusable how-to (see ADR-0004)
- `hotfix` — a rapid fix, often paired with a related entry pointing at the root cause

A node's schema profile can extend this list (Vectorscape adds `diff`, `event`, `spawn`, `death`, etc.). Unknown types warn but insert (the substrate captures, doesn't gatekeep).

### `content`

The body of the entry. Free-form text. Markdown is fine. Code blocks are fine. Multi-paragraph is fine. The PlaneScape NN has entries from one-liner notes to 50-line vision docs; the substrate doesn't care.

FTS5 indexes the content automatically via triggers (see `02_schema_design.md`). `search_text("FUSE AND boot")` returns entries whose content matches the FTS5 query.

### `related_id`

Points at another entry's `id`. The substrate's threading primitive.

- A `decision` entry may have `related_id = <discussion's id>` showing what discussion led to the decision.
- A `hotfix` entry may have `related_id = <error's id>` showing what bug it fixed.
- A `skill` revision has `related_id = <original skill's id>` (always the root, per ADR-0004).

`get_thread(root_id)` returns the root entry plus every entry whose `related_id` points at it, sorted by id ascending. **The threading is one level deep**: it does not transitively follow chains. The skill convention of root-anchored revisions exists because of this one-level depth (ADR-0004).

For deeper structures, write a `discussion` or `note` entry that links to a list of `id`s in its content, or compose multiple `get_thread` calls. The substrate intentionally doesn't ship recursive-CTE threading; it would complicate the reader for cases that arise rarely.

### `tags`

Comma-separated text. The substrate's categorization layer.

Tags drive:
- `search_by_tag` (substring LIKE, fine for casual use)
- `entry_tag` companion-table equality lookups (fast, via trigger-maintained denormalization)
- `list_tags` (the menu)
- `list_tags(tree=True)` (grouped by top-level category)
- `list_tags(prefix='case:')` (the values inside a tag namespace)

Every entry has at minimum its `entry_type` as a tag — the write path adds it automatically. Tag discipline (ADR-0009) governs how the column should be used.

### `extras`

JSON blob, nullable. Only populated if the schema profile enables it. Holds structured custom fields (Vectorscape's `(x, y, z)` coordinates; Spore's telemetry).

Queryable via SQLite's `json_extract`. Indexable via expression indexes (declared in the schema profile, materialized at init). Default value is NULL; entries that don't need extras pay no storage cost.

## Why these seven and not more

Every additional column is a tax forever. The cost of a column shows up in:

- The schema profile (every column needs to be declared somewhere).
- The aggregator (cross-node queries have to handle the column uniformly).
- The migration path (every existing node has to be brought to the new schema).
- The MCP tool definitions (writes have to accept the column; reads have to return it).
- The CLI surface, the dashboard UI, the export format.

The seven listed above are the ones whose absence has caused real pain in the live NN's lineage. Anything else has, so far, been expressible as a tag, a tag namespace, or a JSON extras field — without a column.

The bar for adding an eighth column is: "the absence of this column produces pain in real use that tags and extras *cannot* solve." So far, nothing meets that bar. If something ever does, it gets its own ADR.

## The substrate guarantees

Anything you write into the substrate has the following properties forever:

1. **It will be there.** No deletion (ADR-0005).
2. **It won't have changed.** No in-place edits to content, agent, entry_type, related_id, or extras. (Tags may be retagged via the audited `retag` operation; ADR-0005's exception.)
3. **You can find it by id.** `by_id(N)` always returns the same row for the same N forever.
4. **You can find it by what's in it.** FTS5 over content; substring LIKE over tags; equality over `entry_tag`; type-equality over the column.
5. **You can find what it points at and what points at it.** `get_thread(N)` returns the root + direct children.
6. **You can export it.** The data is a SQLite file. SQLite is open, ancient, ubiquitous.
7. **You can replicate it.** The file is a file. `cp`, `rsync`, S3 — pick your tool.

These seven guarantees are what makes the substrate substrate. Removing any of them — adding deletion, allowing edits, hiding the storage format, requiring a service to read — turns it back into a database with a UI, and the substrate's whole reason for existing evaporates.

## What the substrate is not

The substrate is not:

- **A queue.** It doesn't pop. It doesn't have a consumer offset. It doesn't notify on write. Reading is on-demand pull.
- **A vector store.** No embeddings in v1 (ADR-0010). Queries are keyword (FTS5), tag, type, agent, id, or thread.
- **A graph database.** Entries point at one parent (`related_id`); that's the only structural relationship. Anything more graph-like is encoded in tags (e.g., a tag `mentions:42` could indicate a soft reference, but the substrate doesn't materialize it as a graph edge).
- **A general-purpose key/value store.** It is text-and-metadata storage with strong attribution and threading. Use Redis or SQLite directly for KV.
- **A document database.** Documents would suggest mutation; entries are append-only.
- **A workflow engine.** The substrate records what agents did; it doesn't orchestrate what they do next.

These boundaries are part of the substrate's identity. They keep the surface small enough to be load-bearing for many things; expanding them in any one direction would make the substrate worse at being substrate.

## Putting it together: the lifecycle of one entry

1. Some seat (`opus` say) decides to record something — a decision, a thought, a skill, an observation.
2. The seat calls `log_entry(agent="opus", entry_type="discussion", content="...", related_id=<maybe>, tags="discussion,arc-cosmology,...")`.
3. The package validates: agent is non-empty, entry_type is non-empty (and warns if unknown to the profile), content is non-empty, related_id (if given) exists, tags are well-formed.
4. INSERT into `entry`. Autoincrement assigns the `id`. Triggers populate `entry_fts` (content for search) and `entry_tag` (each comma-split tag as its own row).
5. The new row's `id` is returned to the caller.
6. From this moment forward: `by_id(<that id>)` returns this row. `recent` shows it newest-first. `search_text` and `search_by_tag` find it on matching queries. `get_thread(<root_id>)` includes it if its `related_id` matches. The aggregator sees it in the unioned view if its node is in scope. The MCP exposes it via `recent` and friends. The dashboard renders it.
7. Forever.

That is the whole substrate.
