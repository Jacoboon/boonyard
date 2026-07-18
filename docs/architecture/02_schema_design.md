# Architecture 02 — Schema Design (full DDL, triggers, query patterns)

This is the operational companion to ADR-0002. Where the ADR explains *why* the schema looks the way it does, this document is *what it is*, line by line, ready for Code to implement against.

## The full schema (v3, the BoonyardNN canon)

```sql
-- =====================================================
--  BoonyardNN node schema v3
--  Idempotent: every CREATE uses IF NOT EXISTS.
-- =====================================================

-- ---- entry: the irreducible row -----------------------------------------
CREATE TABLE IF NOT EXISTS entry (
    id          INTEGER  PRIMARY KEY AUTOINCREMENT,
    timestamp   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    agent       TEXT     NOT NULL,
    entry_type  TEXT     NOT NULL,
    content     TEXT     NOT NULL,
    related_id  INTEGER  REFERENCES entry(id),
    tags        TEXT,
    extras      TEXT  -- JSON; NULL unless the schema profile enables it
);

CREATE INDEX IF NOT EXISTS idx_entry_agent      ON entry(agent);
CREATE INDEX IF NOT EXISTS idx_entry_timestamp  ON entry(timestamp);
CREATE INDEX IF NOT EXISTS idx_entry_type       ON entry(entry_type);
CREATE INDEX IF NOT EXISTS idx_entry_related_id ON entry(related_id);

-- ---- full-text search over content (FTS5, external-content) -------------
CREATE VIRTUAL TABLE IF NOT EXISTS entry_fts USING fts5(
    content,
    content='entry',
    content_rowid='id'
);

CREATE TRIGGER IF NOT EXISTS entry_ai_fts
AFTER INSERT ON entry
BEGIN
    INSERT INTO entry_fts(rowid, content) VALUES (new.id, new.content);
END;

CREATE TRIGGER IF NOT EXISTS entry_ad_fts
AFTER DELETE ON entry  -- ADR-0005: this trigger should effectively never fire
BEGIN
    INSERT INTO entry_fts(entry_fts, rowid, content)
    VALUES ('delete', old.id, old.content);
END;

-- entry_au_fts is intentionally NOT a content-update trigger:
-- the substrate does not edit content. The tags-only retag path
-- (ADR-0005 exception) does not touch FTS-indexed columns.

-- ---- entry_tag: per-(entry, tag) denormalized lookup --------------------
CREATE TABLE IF NOT EXISTS entry_tag (
    entry_id INTEGER NOT NULL REFERENCES entry(id) ON DELETE CASCADE,
    tag      TEXT    NOT NULL,
    PRIMARY KEY (entry_id, tag)
);

CREATE INDEX IF NOT EXISTS idx_entry_tag_tag ON entry_tag(tag);

CREATE TRIGGER IF NOT EXISTS entry_ai_tags
AFTER INSERT ON entry
WHEN new.tags IS NOT NULL AND new.tags != ''
BEGIN
    -- Split new.tags on commas, trim whitespace, INSERT one row per tag.
    -- Implemented in application code via a follow-up INSERT, not in the
    -- trigger itself (SQLite triggers can't easily loop over a split string).
    -- The package's log_entry() calls _populate_entry_tags(new_id, new.tags)
    -- in the same transaction as the entry INSERT.
    -- The trigger placeholder remains as a marker; the actual splitting
    -- happens in Python. See package/boonyard/log.py.
    SELECT 1;  -- no-op; see comment above
END;

CREATE TRIGGER IF NOT EXISTS entry_ad_tags
AFTER DELETE ON entry  -- ADR-0005: should effectively never fire
BEGIN
    DELETE FROM entry_tag WHERE entry_id = old.id;
END;

-- The retag path UPDATEs entry.tags and calls _repopulate_entry_tags(id, new_tags)
-- in Python, atomically. No trigger handles UPDATE because the only allowed
-- update is the audited retag operation, which has app-level coordination.

-- ---- meta: schema versioning and node identity --------------------------
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Bootstrap rows; INSERT OR IGNORE makes init_db() idempotent.
INSERT OR IGNORE INTO meta (key, value) VALUES ('schema_version', '3');
INSERT OR IGNORE INTO meta (key, value) VALUES ('node_uuid', NULL);  -- populated on init
INSERT OR IGNORE INTO meta (key, value) VALUES ('node_name', NULL);  -- populated from boonyard.toml on init
INSERT OR IGNORE INTO meta (key, value) VALUES ('created_at', NULL); -- populated on init

-- ---- meta_log: append-only log of meta operations (retags, schema migrations) --
-- Every retag and every schema migration writes one row here.
-- This is the audit trail for the only mutable surface (entry.tags) and for
-- schema_version bumps. Append-only by convention; never modified.
CREATE TABLE IF NOT EXISTS meta_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    op         TEXT NOT NULL,         -- 'retag', 'schema_migrate', 'profile_change'
    entry_id   INTEGER,               -- nullable; the row affected, if applicable
    payload    TEXT NOT NULL,         -- JSON: before/after, reason, etc.
    actor      TEXT NOT NULL          -- who did it; usually an agent or 'system'
);

CREATE INDEX IF NOT EXISTS idx_meta_log_timestamp ON meta_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_meta_log_op        ON meta_log(op);
CREATE INDEX IF NOT EXISTS idx_meta_log_entry_id  ON meta_log(entry_id);
```

## Pragmas applied on connect

```sql
PRAGMA journal_mode = WAL;       -- writers don't block readers
PRAGMA foreign_keys = ON;        -- enforce REFERENCES entry(id)
PRAGMA synchronous = NORMAL;     -- durable enough; faster than FULL
```

Read-only connections (the aggregator, plus any reader path that should be physically incapable of writing) add:

```sql
PRAGMA query_only = ON;
```

## Hot expression indexes for extras (when enabled by profile)

If `boonyard.toml` declares `[extras]` with `indexes = [...]`, the init path creates one expression index per declared field:

```sql
-- e.g., for Vectorscape's player_id (string):
CREATE INDEX IF NOT EXISTS idx_entry_extras_player_id
    ON entry(json_extract(extras, '$.player_id'));

-- e.g., for Vectorscape's x coordinate (int — note the CAST for type-correct comparison):
CREATE INDEX IF NOT EXISTS idx_entry_extras_x
    ON entry(CAST(json_extract(extras, '$.x') AS INTEGER));
```

The package's `init` command (also re-runnable via `boonyard reindex`) reads the profile and generates these index DDL statements. Adding a new hot field after the fact requires re-running `boonyard reindex`, which is fast even on large nodes.

## Validators

Per ADR-0002, validation is *soft*: writes succeed regardless, but warnings surface in stderr / the CLI / the MCP response metadata. The package's `log_entry` performs:

1. **Required fields present:** `agent`, `entry_type`, `content` non-empty (hard fail — these are NOT NULL).
2. **Profile soft-validation:** if `[agents.allowed]` is declared and `agent` is not in it, emit a warning. Same for `entry_type`.
3. **Tag well-formedness:** lowercase, hyphen-or-colon delimited, no whitespace inside a tag, no empty tags. Malformed tags emit a warning; the row still inserts with the cleaned tags (whitespace stripped, lowercase forced).
4. **Tag namespace declaration:** if a tag matches `<prefix>:<value>` and `prefix` is not in `[tags.namespaces]`, emit a warning.
5. **Extras typing:** if `extras` is non-empty and `[extras].enabled = false`, emit a warning (the column should be NULL by profile rule); if `enabled = true` and a field's value violates its declared type (e.g., `"x:int"` but extras has `"x": "not a number"`), emit a warning.
6. **Related_id existence:** if `related_id` is non-NULL and no entry with that id exists, hard fail (FK constraint).

The `boonyard doctor` CLI command runs the validators across every existing entry and reports any that would have warned, so a node migrated in from an older schema can be audited without re-writing every entry.

## Query patterns

### `recent`

```sql
SELECT id, timestamp, agent, entry_type, content, related_id, tags, extras
FROM entry
WHERE (:agent IS NULL OR agent = :agent)
  AND (:entry_type IS NULL OR entry_type = :entry_type)
ORDER BY id DESC
LIMIT :limit;
```

Sorted by `id DESC` rather than `timestamp DESC` because `id` is autoincrement and gives a stable tiebreaker for entries with the same second-precision timestamp.

### `by_id`

```sql
SELECT * FROM entry WHERE id = :id;
```

### `search_by_tag` (substring — kept for casual use)

```sql
SELECT * FROM entry
WHERE tags LIKE '%' || :tag || '%'
ORDER BY id DESC
LIMIT :limit;
```

### `search_by_tag_exact` (uses companion table; recommended for tooling)

```sql
SELECT e.*
FROM entry e
JOIN entry_tag t ON t.entry_id = e.id
WHERE t.tag = :tag
ORDER BY e.id DESC
LIMIT :limit;
```

The `entry_tag` join uses `idx_entry_tag_tag` for an indexed equality lookup; fast at any scale.

### `search_text` (FTS5)

```sql
SELECT e.*
FROM entry e
JOIN entry_fts f ON f.rowid = e.id
WHERE entry_fts MATCH :query
ORDER BY e.id DESC
LIMIT :limit;
```

`:query` accepts FTS5 syntax: `fuse AND boot`, `"exact phrase"`, `smoke*`, etc.

### `get_thread`

```sql
SELECT *
FROM entry
WHERE id = :root_id OR related_id = :root_id
ORDER BY id;
```

One level deep, by design (ADR-0004). Skills use root-anchored revisions to remain visible.

### `list_tags`

```sql
SELECT tag, COUNT(*) AS n
FROM entry_tag
WHERE (:prefix IS NULL OR tag LIKE :prefix || '%')
GROUP BY tag
ORDER BY n DESC, tag ASC;
```

Uses the `entry_tag` companion table — no full-table scan over `entry.tags`. The `tree=True` variant is then post-processed in Python: group by the text before the first hyphen.

### Extras queries

```sql
-- Find all diff entries in a 3D region (Vectorscape example)
SELECT *
FROM entry
WHERE entry_type = 'diff'
  AND CAST(json_extract(extras, '$.x') AS INTEGER) BETWEEN 100 AND 200
  AND CAST(json_extract(extras, '$.y') AS INTEGER) BETWEEN 400 AND 500
ORDER BY id DESC
LIMIT 100;
```

The expression indexes on `x` and `y` make this fast.

### Aggregator query (over-many mode)

Generated by the aggregator from the scope param:

```sql
-- For scope = ['planescape', 'jrhood', 'spore']:
ATTACH DATABASE '/data/.../planescape/journal.db' AS planescape;
ATTACH DATABASE '/data/.../jrhood/journal.db'     AS jrhood;
ATTACH DATABASE '/data/.../spore/journal.db'      AS spore;

SELECT 'planescape' AS source, * FROM planescape.entry
UNION ALL
SELECT 'jrhood'     AS source, * FROM jrhood.entry
UNION ALL
SELECT 'spore'      AS source, * FROM spore.entry
ORDER BY timestamp DESC
LIMIT 20;
```

The aggregator opens its primary connection without any DB; all entries come through ATTACH. This isolates failures (a corrupt node makes its UNION leg fail; others continue) and avoids accidentally writing.

## Index inventory (the full set on a fresh v3 node)

```
idx_entry_agent           on entry(agent)
idx_entry_timestamp       on entry(timestamp)
idx_entry_type            on entry(entry_type)
idx_entry_related_id      on entry(related_id)
idx_entry_tag_tag         on entry_tag(tag)
idx_meta_log_timestamp    on meta_log(timestamp)
idx_meta_log_op           on meta_log(op)
idx_meta_log_entry_id     on meta_log(entry_id)

-- plus, if profile enables extras with indexes = [...]:
idx_entry_extras_<field>  on entry(json_extract(extras, '$.<field>'))
                          (one per declared field; CAST if numeric)
```

Plus the FTS5 virtual table's internal indexes (`entry_fts_*`, managed by SQLite).

## What's NOT in the schema

Several things that *could* be added are deliberately not:

- **No `updated_at` column.** Entries don't update (except tags, which has its own audit via `meta_log`). An `updated_at` field would imply update-tracking that doesn't apply.
- **No `deleted_at` column.** Per ADR-0005.
- **No `source_uri` column for entries imported from elsewhere.** A migration-time tag namespace (`migrated-from:planescape-jrhood-v2`) covers this without a column.
- **No `version` per entry.** Skills version themselves via root-anchored revision threads; no version column needed.
- **No `score` or `relevance` column for ranking.** FTS5 ranks at query time via BM25.
- **No `embedding` column.** Per ADR-0010.

Adding any of these is a future-ADR decision with the bar set high.

## Schema migrations

Each migration is a one-shot script that:

1. Backs up the live `journal.db` to `journal.db.pre-vN.bak` next to it.
2. Runs all DDL inside a single transaction.
3. Backfills any data shape changes (e.g., re-populating `entry_tag` from `entry.tags` on the v2→v3 migration).
4. Updates `meta.schema_version`.
5. Writes a `meta_log` row recording the migration.
6. Verifies the new schema with `boonyard doctor` before exiting non-zero on any failure.

Migration scripts live in `package/boonyard/migrations/` and are named `<from>_to_<to>.py`. They are idempotent (safe to re-run) and they refuse to run if `meta.schema_version` is not the expected `from` version.

The v1 schema (PlaneScape's original `_dev/journal/db.py`) is the starting point for migration. The v2 schema (v1.1 implementation appendix's FTS5 + skill type additions) is an intermediate version. The v3 schema is this document. JRHood's `agent_log` schema is *not* in this version sequence — it's a sibling fork, and its migration to v3 is one-step via the migration script described in `08_migration.md`.

## Operational notes

- Triggers on `entry` are intentionally minimal. Heavy logic (tag splitting, validation) lives in the package's Python layer, not in SQL. This keeps the schema portable to other engines if we ever need to (we don't plan to), and keeps the SQL easy to reason about.
- The `entry_tag` triggers are placeholders for delete cascades; the INSERT-side population happens in `boonyard.log` (Python) in the same transaction. This is a deliberate trade — SQLite trigger string-splitting is awkward; Python loop is clear.
- `WAL` mode means there are typically three files per node: `journal.db`, `journal.db-wal`, `journal.db-shm`. Backups and exports must either checkpoint first (`PRAGMA wal_checkpoint(TRUNCATE)`) or copy all three. The package's `export` and `backup` commands handle this.
- The schema is small enough to fit on a single screen. This is part of why every doc says the substrate is small.

## See also

- ADR-0002 — the schema decision (the why)
- ADR-0005 — append-only (the constraint the schema embodies)
- `01_core_primitive.md` — what each field means semantically
- `08_migration.md` — how JRHood / PlaneScape / Spore map into this
- `package/boonyard/db.py` — the implementation
- `package/boonyard/migrations/` — the migration scripts
