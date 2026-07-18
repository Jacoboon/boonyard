# ADR 0002 — Fixed core schema + tag namespaces + optional JSON extras

**Status:** Accepted
**Date:** 2026-05-20
**Deciders:** Jacob (Professor), Cowork-Opus
**Supersedes:** —
**Superseded by:** —

## Context

This is the load-bearing schema decision. Jacob explicitly flagged it during the initial design conversation: *"The magic is 'entry + tags = memory'. Certain things like 'speaker or agent' and 'related entries' will be standard throughout each NN, but they need to be easily customizable or extendable at setup time."*

The substrate has to satisfy two pulls that look opposed:

1. **Universality.** Every project that adopts BoonyardNN should be using the same core. An aggregator that opens many nodes (the over-many / Umbrella mode) needs to ask the same questions across all of them and get the same column names back. Skills, queries, tooling, MCP endpoints — all of them should work identically against any node.

2. **Per-project extensibility.** Projects have genuinely different domain references. JRHood needs to attach entries to `case_number` (FK to refunds.case_number). Vectorscape needs to attach diff entries to `(x, y, z)` coordinates and `player_id`. Spore needs to attach telemetry to entries. A future project will need something nobody anticipated. The substrate has to accommodate this without forking the schema per project.

The existing live NNs have solved this in incompatible ways, which is itself the evidence for why the decision matters:

| Project | Solution | Cost |
|---|---|---|
| PlaneScape | Tags only (`prompt-43`, `arc-cosmology`) | Limited typing; no FK |
| JRHood | Custom column (`case_number TEXT, INDEX`) | Fork of core schema; aggregator-hostile |
| Spore | (mixed; not catalogued for this ADR) | Drift unknown |

We need a single recommendation that absorbs all three patterns and works for the next project too, without breaking the universality property.

## Decision

The node schema has three layers:

### Layer 1 — Immutable core (every node, always)

The `entry` table has exactly these columns, in exactly this shape, in every node, forever:

```sql
CREATE TABLE entry (
    id          INTEGER  PRIMARY KEY AUTOINCREMENT,
    timestamp   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    agent       TEXT     NOT NULL,
    entry_type  TEXT     NOT NULL,
    content     TEXT     NOT NULL,
    related_id  INTEGER  REFERENCES entry(id),
    tags        TEXT,
    extras      TEXT  -- JSON; NULL unless the schema profile enables it
);
```

Supporting infrastructure that is also part of the immutable core:

```sql
-- Indexes on core columns
CREATE INDEX idx_entry_agent      ON entry(agent);
CREATE INDEX idx_entry_timestamp  ON entry(timestamp);
CREATE INDEX idx_entry_type       ON entry(entry_type);
CREATE INDEX idx_entry_related_id ON entry(related_id);

-- Full-text search over content
CREATE VIRTUAL TABLE entry_fts USING fts5(
    content,
    content='entry',
    content_rowid='id'
);

-- Companion table: one row per (entry, tag) pair
-- Auto-populated by triggers from entry.tags. Gives fast tag equality lookups.
CREATE TABLE entry_tag (
    entry_id INTEGER NOT NULL REFERENCES entry(id) ON DELETE CASCADE,
    tag      TEXT    NOT NULL,
    PRIMARY KEY (entry_id, tag)
);
CREATE INDEX idx_entry_tag_tag ON entry_tag(tag);

-- Triggers to keep FTS and entry_tag in sync with entry
-- (full DDL in architecture 02)

-- Meta table for schema version + node identity
CREATE TABLE meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
INSERT INTO meta (key, value) VALUES ('schema_version', '3');
INSERT INTO meta (key, value) VALUES ('node_name', '<from boonyard.toml>');
INSERT INTO meta (key, value) VALUES ('node_uuid', '<one-time generated>');
```

The core never changes shape between nodes. Aggregators can rely on it forever. Schema migrations apply uniformly. The full DDL lives in `docs/architecture/02_schema_design.md`.

### Layer 2 — Tag namespaces (zero-schema custom references)

A **tag namespace** is a tag whose key encodes a typed reference, by convention `<namespace>:<value>`. Examples:

- JRHood: `case:521-5400610` for the case-number reference.
- Vectorscape: `player:p042` for the player reference.
- Spore: `device:pi-3b-corner` for the host hardware.
- Cross-project: `prompt:43`, `arc:cosmology`, `session:2026-05-20`.

These are *just tags*. They are stored in `entry.tags` like any other tag, automatically denormalized into `entry_tag` by triggers, and queryable via `entry_tag.tag = 'case:521-5400610'` — which is an indexed equality lookup, fast at any scale we care about. The `list_tags(prefix='case:')` reader gives the full menu of all values that have appeared in the namespace, no schema change required.

Reserved namespaces are declared in the schema profile (see Layer 3) so they are discoverable and so the validator can warn if an entry uses a namespace that isn't declared. But the substrate works with or without the declaration — undeclared namespaces just don't get the discoverability benefit.

This layer handles ≥80% of "I have a project-specific reference" needs, and it does so without touching the schema, without breaking aggregation, and with full discoverability via `list_tags`.

### Layer 3 — JSON extras (typed structured custom fields)

When a project needs *structured* custom data — multiple correlated fields, non-string types you want preserved, or high-frequency queries that need their own index — the schema profile enables the `extras` column and declares the fields. The `extras` column holds JSON; SQLite's JSON1 functions query it; expression indexes accelerate hot fields.

```sql
-- e.g. Vectorscape enables extras and declares (x, y, z, player_id):
-- (these indexes are created at init, based on boonyard.toml)
CREATE INDEX idx_entry_extras_x         ON entry(CAST(json_extract(extras, '$.x') AS INTEGER));
CREATE INDEX idx_entry_extras_y         ON entry(CAST(json_extract(extras, '$.y') AS INTEGER));
CREATE INDEX idx_entry_extras_z         ON entry(CAST(json_extract(extras, '$.z') AS INTEGER));
CREATE INDEX idx_entry_extras_player_id ON entry(json_extract(extras, '$.player_id'));
```

Insert:
```sql
INSERT INTO entry (agent, entry_type, content, tags, extras)
VALUES ('player', 'diff', 'placed wall at (123, 456, 789)',
        'diff,player:p042,build',
        '{"x":123,"y":456,"z":789,"player_id":"p042","action":"place_wall"}');
```

Query:
```sql
-- Find diffs in a 3D region
SELECT * FROM entry
WHERE entry_type = 'diff'
  AND json_extract(extras, '$.x') BETWEEN 100 AND 200
  AND json_extract(extras, '$.y') BETWEEN 400 AND 500;
```

Extras are optional. A node that doesn't need them leaves the column NULL everywhere and pays nothing. The schema profile gates which fields exist; nothing else can write to extras without the profile's blessing (soft-validated, like `entry_type`).

### Layer 4 — Schema profile (the per-node contract)

Every node has a `boonyard.toml` file next to its `journal.db`. It declares:

```toml
[node]
name           = "jrhood"
uuid           = "auto"           # generated on init
schema_version = 3

[agents]
# Soft-validated. Unknown agents warn but insert.
allowed = ["opus", "code", "cli", "dispatch", "supervisor",
           "scraper", "lookup", "letter", "mail", "drip", "deploy", "jacob"]

[entry_types]
# Soft-validated. Unknown types warn but insert.
allowed = ["prompt", "implementation", "decision", "discussion",
           "lint_finding", "verification", "vision", "error", "note", "skill"]

[tags.namespaces]
# Reserved tag namespaces. Discoverable via list_tags(prefix=...).
# The value is human-readable documentation, retrievable via the API.
case  = "FK to refunds.case_number — JRHood lead reference"
phase = "Project phase identifier (P1, P8, etc.)"
arc   = "Long-running development arc"

[extras]
enabled = false  # JRHood doesn't need structured extras; tag namespaces cover it.

# When enabled = true, you also declare:
# fields  = ["x:int", "y:int", "z:int", "player_id:str"]
# indexes = ["x", "y", "z", "player_id"]
```

The profile is read by the package at init and at each operation. The CLI / Python API / MCP layer consult it to surface the menus (`list_agents`, `list_entry_types`, `list_tag_namespaces`) and to soft-validate writes. The profile never *prevents* a write — it warns and inserts — because the substrate's job is to capture, not gatekeep. Hard-validation is a project decision implemented above the substrate, not inside it.

## Consequences

**Positive:**
- One canonical schema across every node — aggregators can rely on it forever.
- Tag namespaces handle most "custom reference" needs with zero schema cost, full discoverability, and indexed equality lookups via `entry_tag`.
- JSON extras handle structured / typed / high-frequency custom data without forking the column set.
- Migration between projects is trivial: copy entries, drop the profile in. Existing per-project columns (JRHood's `case_number`) become tag namespaces and/or extras fields without changing the data shape.
- The `entry_tag` companion table makes tag equality lookups O(log n), removing the historic `LIKE %tag%` substring problem (which remains supported via `search_by_tag` for casual use, but is no longer load-bearing).
- The schema profile is the customization surface, not the schema. Customization is config, not code or DDL.

**Negative:**
- The `entry_tag` companion table doubles the storage cost of tags. Acceptable; tags are short and the table is narrow.
- JSON `extras` queries are less ergonomic than native columns (`json_extract(extras, '$.x')` vs. `x`). Expression indexes mitigate the performance side. Ergonomic queries are wrapped in the Python API (`Entry.extras['x']`).
- Schema profile validation is *soft* — unknown agents / types / namespaces warn but insert. This is a feature (substrate captures even when validators are stale) but it requires discipline to review the warnings. The `boonyard doctor` CLI command lists every unknown value seen.
- Adding hot indexes on extras fields after the fact requires a one-time `CREATE INDEX` migration. This is supported by `boonyard reindex` and is fast even on large nodes.

**Neutral:**
- Existing JRHood / PlaneScape nodes need migration to the canonical schema. That work is sequenced in roadmap PHASE_1 and documented in `architecture/08_migration.md`. The migration is idempotent and non-destructive.

## Alternatives considered

### Option A — JSON extras only (no tag namespaces)

Every custom field lives in `extras`. No `case:` tag namespace; instead `extras = {"case_number": "521-5400610"}`. Tags are pure category labels.

**Why rejected:** Loses the `list_tags(prefix='case:')` discoverability. A new seat opening a JRHood node would see in the tag tree that there are dozens of `case:*` tags and immediately understand the namespace; the same seat looking at extras has to grep through entries or read the profile. The tag-namespace pattern is the simpler, more discoverable answer for reference-style custom fields. Extras still wins for structured / multi-field / typed data.

### Option B — Per-project `ALTER TABLE` columns (the v1.2 "schema profile creates columns" reading)

Schema profile declares `case_number TEXT`; package issues `ALTER TABLE entry ADD COLUMN case_number TEXT; CREATE INDEX ...` at init. Each project's node has its own native column for its custom fields.

**Why rejected:** Forks the schema per project. The aggregator that opens JRHood + PlaneScape + Vectorscape gets three different column sets and cannot run a single uniform `SELECT * FROM entry` across them. The aggregator's queries become "schema-aware" — bad. Universality property breaks. Also: ALTER TABLE on a long-lived database is operationally heavier than the JSON path, and migrations between projects require renaming columns.

### Option C — Tag namespaces only (no extras column)

Everything project-specific goes into a tag namespace. JRHood: `case:521-5400610`. Vectorscape: `x:123, y:456, z:789, player:p042`. No JSON.

**Why rejected:** Loses native typing on integer / float / bool data. Vectorscape's `x:123, y:456, z:789` is fine for equality but rough for range queries (`WHERE x BETWEEN 100 AND 200` becomes substring math on tag strings). Loses the ability to store structured data atomically (a diff entry's coordinates belong together, not as three separate tags). Tag pollution: hot per-entry custom fields (like coordinates) would flood the tag namespace and dilute the categorical signal tags are meant to carry. Tags are for *categories*, not arbitrary data.

### Option D — Side-tables per custom field type

Profile declares `case_number TEXT`; package creates a `entry_extra_case_number(entry_id, value)` side table with an index. Each custom field gets its own EAV-ish side table.

**Why rejected:** Multiplies the number of tables per node. Aggregator queries across projects become unions across heterogeneous side-table sets. Schema migrations multiply. Adds nothing the JSON extras pattern doesn't give us with one table and `json_extract`. JSON1 + expression indexes is the simpler answer.

### Option E — Schema-version per project (let drift exist; aggregator adapts)

Accept that JRHood and PlaneScape have different schemas, version them separately, and have the aggregator adapt at query time (column-name mapping per source node).

**Why rejected:** Pushes complexity from a single design decision into every query consumer forever. Every aggregator query has to know "JRHood's case_number maps to PlaneScape's nothing." Encodes drift as a permanent feature. Defeats the substrate-is-small-on-purpose goal. Solves a problem we can avoid by making a one-time decision now.

## Worked examples

### JRHood node

```toml
[node]
name = "jrhood"

[tags.namespaces]
case  = "FK to refunds.case_number"
phase = "Project phase (P1-P10)"
ops   = "Operational concern"

[extras]
enabled = false
```

JRHood's existing `agent_log.case_number = '521-5400610'` migrates to `entry.tags` containing `case:521-5400610`. The `entry_tag` table indexes it; queries that used `WHERE case_number = '521-5400610'` become `WHERE id IN (SELECT entry_id FROM entry_tag WHERE tag = 'case:521-5400610')`, which is just as fast. The `notes` column merges into `content`. The `action` field becomes the first line of `content`.

### PlaneScape node

```toml
[node]
name = "planescape"

[tags.namespaces]
prompt = "Prompt sequence number (prompt:43)"
arc    = "Long-running design arc (arc:cosmology)"
adr    = "Architecture Decision Record (adr:0016)"
book   = "Lore Book volume (book:7)"

[extras]
enabled = false
```

PlaneScape's existing entries already use `prompt-43` style tags. Migration converts the hyphen-prefix convention to the colon-prefix namespace convention (`prompt-43` → `prompt:43`), preserving discoverability via `list_tags(prefix='prompt:')`.

### Vectorscape (in-project diff log)

```toml
[node]
name = "vectorscape-world-prime"

[agents]
allowed = ["player", "system", "npc"]

[entry_types]
allowed = ["diff", "event", "spawn", "death", "login", "logout"]

[tags.namespaces]
player = "Player identifier (player:p042)"
zone   = "World zone name (zone:origin-verita)"

[extras]
enabled = true
fields  = ["x:int", "y:int", "z:int", "player_id:str", "action:str"]
indexes = ["x", "y", "z", "player_id"]
```

Vectorscape uses the substrate as the player-diff layer database (per the in-project mode). Each diff entry has structured coordinates in `extras`, hot-indexed for region queries. Player identity is both a tag namespace (for category-style queries) and an extras field (for joined queries with x/y/z).

### Spore (resident AI on Pi)

```toml
[node]
name = "spore-prime"

[agents]
allowed = ["brain", "memory", "voice", "scheduler", "curiosity", "expression"]

[entry_types]
allowed = ["thought", "perception", "decision", "expression", "telemetry", "skill"]

[tags.namespaces]
session = "Wake session identifier (session:2026-05-13T08:00)"
mood    = "Current mood tag (mood:contemplative)"

[extras]
enabled = true
fields  = ["battery:float", "uptime_hours:int", "ambient_db:float"]
indexes = ["battery"]
```

## References

- CHARTER.md — "Load-bearing beliefs / Entry + tags = memory"
- glossary.md — `tag namespace`, `extras`, `schema profile`, `core columns`
- architecture/01_core_primitive.md — what makes the core irreducible
- architecture/02_schema_design.md — full DDL, triggers, query patterns
- architecture/08_migration.md — how JRHood / PlaneScape / Spore migrate in
- ADR-0003 — DB-per-node (why one schema across all nodes matters for aggregation)
- ADR-0009 — Tag discipline (the singular-noun rule applies inside namespaces too)
- v1.1 implementation appendix, §1c — original FTS5 + triggers pattern (preserved here)
- v1.2 design doc, §1 "Customizable → config, not hardcode"
