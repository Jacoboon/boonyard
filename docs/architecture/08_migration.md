# Architecture 08 — Migration Paths from Existing NNs

How each of Jacob's existing NN deployments becomes a BoonyardNN node. The migrations are one-shot scripts living under `package/boonyard/migrations/from_<source>/`. They are idempotent (safe to re-run) and non-destructive (the source DB is never modified; a new Boonyard-shaped DB is produced alongside it).

## Migration principle

Every migration:

1. Reads the source DB (open with `query_only=ON`).
2. Initializes a fresh BoonyardNN v3 schema in a new `journal.db` file.
3. Writes one `boonyard.toml` profile derived from the source's known shape.
4. Translates each source row to one or more Boonyard entries, preserving timestamps, agents, content, threads, and adapting custom fields to tag namespaces / extras / content.
5. Validates the result (entry count matches; spot-check sample fields; FTS index populated; entry_tag populated).
6. Writes one `meta_log` entry recording the migration: source path, row count, transformation map, completed_at.
7. Reports a delta summary the user reviews before pointing seats at the new node.

The source DB is preserved. The user can keep running the old NN in parallel for a while; the canonical migration is the user-controlled cutover, not the script run.

## Migration 1 — PlaneScape (`_dev/journal/journal.db`, schema v2)

The closest source to the BoonyardNN canon. The PlaneScape NN already has FTS5, the `skill` entry_type, and the v1.1 conventions. The migration is essentially a schema rename + the v2→v3 additive changes (extras column, entry_tag companion, meta_log).

### Source schema (PlaneScape, v2)

```sql
journal(
    id, timestamp, agent, entry_type, content, related_id, tags
)
journal_fts (FTS5 over content)
```

### Target schema (BoonyardNN, v3)

Per `02_schema_design.md`: `entry`, `entry_fts`, `entry_tag`, `meta`, `meta_log`, optional `extras`.

### Transformation

Per row in `journal`:

```
new_entry.id           = same        (preserve for related_id reference integrity)
new_entry.timestamp    = same
new_entry.agent        = same
new_entry.entry_type   = same
new_entry.content      = same
new_entry.related_id   = same
new_entry.tags         = same (normalized: lowercase, hyphen-form, trim)
new_entry.extras       = NULL  (PlaneScape doesn't use extras)
```

Tag normalization: PlaneScape's existing `prompt-43`, `arc-cosmology`, etc. are already in canonical form. The `prompt-N` style is treated as a tag namespace by convention (no rename needed — `prompt-43` and `prompt:43` are both valid; the namespace-with-colon syntax is preferred for *new* tag namespaces, but existing `prefix-` style tags are grandfathered).

### Profile

```toml
[node]
name = "planescape"
schema_version = 3

[agents]
allowed = ["opus", "code", "professor", "system"]

[entry_types]
allowed = ["prompt", "implementation", "decision", "discussion",
           "lint_finding", "verification", "vision", "error", "note",
           "skill", "hotfix"]

[tags.namespaces]
prompt = "Prompt sequence number"
arc    = "Long-running design arc"
adr    = "Architecture Decision Record reference"
book   = "Lore Book volume reference"

[extras]
enabled = false
```

### Verification

- Row count matches.
- Random 20-entry spot-check: id, timestamp, content, agent identical.
- FTS query for a known string returns the expected entries.
- `list_tags` returns the same tag set, with `entry_tag` denormalization complete.

### Cutover

The PlaneScape NN currently runs as the MCP doorway at `nn.vectorscape.uk/sse`. The cutover:

1. Run the migration to produce `planescape_journal_v3.db`.
2. Stop the MCP server.
3. Move the old `journal.db` to `journal.db.pre-v3.bak`.
4. Move `planescape_journal_v3.db` to `journal.db`.
5. Drop the migration-produced `boonyard.toml` next to it.
6. Restart the MCP server (now serving the BoonyardNN v3 schema).
7. Verify with a `recent 5` call from any seat.

Rollback: stop server, swap files back. The .bak is untouched.

## Migration 2 — JRHood (`data/jrhood.db`, table: `agent_log`)

JRHood's NN has the largest schema-shape divergence: different table name, different column set (`action`, `notes` instead of `content`; `case_number` as a hard column; no `entry_type`).

### Source schema (JRHood)

```sql
agent_log(
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       DATETIME DEFAULT CURRENT_TIMESTAMP,
    agent           TEXT NOT NULL,
    action          TEXT NOT NULL,        -- the scannable summary
    case_number     TEXT,                 -- nullable, FK to refunds.case_number
    related_id      INTEGER,
    notes           TEXT,                 -- long-form reasoning
    tags            TEXT                  -- comma-separated
)
```

### Transformation

Per row in `agent_log`:

```
new_entry.id           = same
new_entry.timestamp    = same
new_entry.agent        = same
new_entry.entry_type   = 'note'                              # default (see refinement below)
new_entry.content      = action + "\n\n" + (notes or "")
new_entry.related_id   = same
new_entry.tags         = normalized tags + ['case:' + case_number] if case_number else tags
new_entry.extras       = NULL
```

**Entry type refinement:** JRHood's NN didn't track `entry_type` as a column, but the `tags` field often implies it. Migration applies these rules in order:

1. If tags contain `decision-*`, set `entry_type='decision'`.
2. If tags contain `error` or `hotfix-*`, set `entry_type='error'` or `'hotfix'`.
3. If tags contain `vision-*` or `roadmap-*`, set `entry_type='vision'`.
4. If tags contain `skill-*`, set `entry_type='skill'`.
5. If tags contain `implementation` or `prompt-*`, set `entry_type='implementation'` or `'prompt'`.
6. Otherwise, `entry_type='note'`.

The auto-derivation is reported in the migration summary so the user can review and (if desired) apply manual corrections after migration (via per-entry `retag` operations or by ignoring — `entry_type='note'` is a safe default).

**Case-number handling:** `case_number` becomes a tag namespace `case:521-5400610` in the new schema. The `entry_tag` denormalization makes `WHERE tag = 'case:521-5400610'` as fast as the original `WHERE case_number = '521-5400610'`. JRHood's existing case-filter queries gain a small wrapper:

```python
# old:
"SELECT * FROM agent_log WHERE case_number = ? ORDER BY id", (case_no,)

# new:
"""SELECT e.* FROM entry e
   JOIN entry_tag t ON t.entry_id = e.id
   WHERE t.tag = ? ORDER BY e.id""", (f"case:{case_no}",)
```

The JRHood codebase's `agents/agent_log.py` helper module gets a one-time update to use the new schema; see PHASE_1 roadmap.

### Profile

```toml
[node]
name = "jrhood"
schema_version = 3

[agents]
allowed = ["opus", "cli", "dispatch", "supervisor",
           "scraper", "lookup", "letter", "mail", "drip", "deploy", "jacob"]

[entry_types]
allowed = ["prompt", "implementation", "decision", "discussion",
           "lint_finding", "verification", "vision", "error", "note",
           "skill", "hotfix"]

[tags.namespaces]
case  = "FK to refunds.case_number (HUD refund tracer leads)"
phase = "Project phase identifier (P1, P8, etc.)"
ops   = "Operational concern"

[extras]
enabled = false
```

### Verification

- Row count matches.
- `case:` tag count matches the count of non-null `case_number` values.
- Entry-type distribution review (the auto-derivation outcomes summary).
- `recent(scope='jrhood', limit=10)` returns the same content the old `recent(10)` did, with action and notes combined.

### Cutover

JRHood runs its NN as part of the production pipeline. Cutover:

1. Run migration to produce `jrhood_journal_v3.db`.
2. Update `agents/agent_log.py` helper functions to read/write the new schema (one-file change; tests run).
3. Switch the production cron / scripts to use the new helper.
4. After 24h validation, archive the old `agent_log` table (rename to `agent_log_pre_v3` in `jrhood.db`).

The new BoonyardNN node lives at `JRHood/data/journal.db` (separate from the operational `jrhood.db` which holds refunds, claims, etc.). The previous in-file `agent_log` table is preserved for archive but no longer written.

## Migration 3 — Spore (`spore.db`, schema TBD)

Spore's NN schema isn't fully catalogued in this canon. The migration script for Spore will be drafted at migration time after auditing the actual schema. Expected pattern: similar shape to JRHood (custom columns like `device_id`, `mood`, `battery_level`), translates to tag namespaces + extras.

A placeholder migration script `from_spore.py` exists in `package/boonyard/migrations/` with TODO markers; it is completed during PHASE_1 when Spore migration is in scope.

## Migration 4 — Vectorscape player-diff (no existing NN; greenfield in-project)

Vectorscape's player-diff layer is currently not implemented on a BoonyardNN node — it uses ad-hoc storage. Migration 4 isn't a migration so much as a *first install*: introducing the BoonyardNN package into the Vectorscape server, creating one node per world, and replacing the existing diff-storage path with `log_entry` calls.

See `roadmap/PHASE_1.md` and `roadmap/PHASE_2.md` for sequencing.

## Generic migration: from arbitrary SQLite event log

The package ships a `boonyard import-sqlite` command for ad-hoc migration of any source SQLite event log:

```bash
boonyard import-sqlite \
    --source ./source.db \
    --table events \
    --map "agent=author,entry_type=kind,content=body,timestamp=ts,tags=labels" \
    --tag-namespace "ref=ref_id" \
    --target ./journal.db
```

The `--map` flag defines column-to-Boonyard-field mappings. The `--tag-namespace` flag defines source-column-to-tag-namespace translations. The command logs a `meta_log` entry recording the mapping, runs the import, validates, and reports.

For sources that don't fit the entry shape (e.g., a CSV log), the user writes a small Python script using the `boonyard.log_entry` API directly. The package ships example scripts under `docs/examples/import_from_<source>/`.

## Reverse migration (Boonyard → other)

Per CHARTER's no-lock-in promise, the substrate exports cleanly:

```bash
boonyard export ./journal.db ./export.zip
```

Produces:

```
export.zip/
    journal.db              # the SQLite file itself (consistent snapshot)
    boonyard.toml           # the schema profile
    README.md               # how to read this without BoonyardNN
    schema_dump.sql         # `.schema` output for reference
```

Anyone with `sqlite3` can read the export. The user can drop the unzipped contents into another vendored install, into Docker, into the SaaS, or into a non-Boonyard system as the source of a custom import.

## See also

- ADR-0002 — fixed core + tag namespaces + extras (the target the migrations land on)
- ADR-0005 — append-only (preserved through migration)
- `02_schema_design.md` — the v3 schema
- `roadmap/PHASE_1.md` — when each migration actually runs
- `package/boonyard/migrations/` — the implementation
