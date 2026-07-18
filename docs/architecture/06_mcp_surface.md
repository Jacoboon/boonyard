# Architecture 06 — The MCP Surface (every tool, every signature)

The MCP server is the principal access path for AI seats. This document is the canonical list of every tool the server exposes, what it does, what it accepts, and what it returns. Anything not in this document is not a BoonyardNN MCP tool. Adding a new tool requires a corresponding ADR or amendment.

## Conventions

- All tools accept an optional `scope` parameter (per ADR-0003 / `03_scope_model.md`). Writers accept it only as a single node name; readers accept any scope form.
- All readers return objects with the same shape: `{id, timestamp, agent, entry_type, content, related_id, tags, extras, source?}`. The `source` field is present only in aggregator responses, naming the originating node.
- `tags` returned in API responses is the parsed list of strings, not the comma-separated raw column value. The column-as-CSV is an internal storage convention; the API is structured.
- Errors are returned as MCP errors with structured payload `{error: <code>, message: <human text>, hint?: <suggestion>}`.
- All tool definitions are versioned with the package — adding a new tool bumps the package's minor version; renaming or removing a tool bumps the major version.

## Write tools

### `log_entry`

```
log_entry(
    agent: str,
    entry_type: str,
    content: str,
    related_id: int | None = None,
    tags: list[str] | str | None = None,
    extras: dict | None = None,
    scope: str | None = None,        # writes target one node
) -> { id: int }
```

Appends one entry. The universal write path.

Semantics:
- `agent`, `entry_type`, `content` are required and non-empty (validated; HTTP 400 / MCP error on violation).
- `tags`: accepts a list of strings (preferred), a single comma-separated string (legacy / CLI convenience), or None. Normalized to the list form before storage.
- `extras`: accepts a dict (preferred) or a JSON-encoded string. Stored as JSON in `entry.extras`.
- `related_id`: if given, the target entry must exist (FK constraint).
- `scope`: if omitted, writes to the key's default node; if given, writes to that named node (the key must be authorized for it; aggregator keys reject writes).

Returns the new entry's `id`.

### `log_skill_revision`

```
log_skill_revision(
    slug: str,               # the stable skill identity, e.g. 'fuse-boot-ritual'
    content: str,            # full SKILL/WHEN/STEPS/GOTCHAS/SOURCE template body
    agent: str,
    extra_tags: list[str] | None = None,
    scope: str | None = None,
) -> { id: int, root_id: int }
```

Convenience over `log_entry` that handles root-anchoring (ADR-0004).

Semantics:
- Finds the root entry for the given `slug` by looking up entries with `entry_type='skill'` and tags containing `skill-{slug}`, sorted by `id ASC`, taking the first.
- If a root exists, INSERT a new entry with `entry_type='skill'`, `related_id=root.id`, and tags `[skill, skill-{slug}, *extra_tags]`.
- If no root exists, this is the first revision; INSERT with `related_id=None` (which becomes the root).
- Returns the new entry's `id` and the root entry's `id` (which may equal the new id for first revisions).

Failure modes:
- Slug must be lowercase-hyphen (validated).
- Content should start with a `SKILL:` line; warning if not (soft).

## Read tools

### `recent`

```
recent(
    limit: int = 20,
    agent: str | None = None,
    entry_type: str | None = None,
    scope: str | None | list[str] = None,
) -> list[Entry]
```

Newest-first entries, optionally filtered by agent and/or entry_type.

Implementation: `ORDER BY id DESC LIMIT :limit` per node, unioned across scope.

### `by_id`

```
by_id(
    entry_id: int,
    scope: str | None | list[str] = None,
) -> Entry | None
```

Returns one entry by id, or null. In aggregator mode with a list scope, returns the first found (entries have node-local ids; aggregator returns the first match with a `source` field naming the node).

### `search_by_tag`

```
search_by_tag(
    tag: str,
    limit: int = 20,
    scope: str | None | list[str] = None,
) -> list[Entry]
```

Substring tag match (LIKE %tag%). Kept for casual use and backward compatibility with PlaneScape's existing tag-search habits. For exact-match tag retrieval with namespace support, use `search_by_tag_exact`.

### `search_by_tag_exact`

```
search_by_tag_exact(
    tag: str,                # e.g. 'case:521-5400610' or 'skill-fuse-boot-ritual'
    limit: int = 20,
    scope: str | None | list[str] = None,
) -> list[Entry]
```

Exact tag equality via the `entry_tag` companion table. Fast at any scale. The preferred tool for tag namespace lookups (`case:...`, `player:...`, etc.) and for `skill-<slug>` identity lookups.

### `search_text`

```
search_text(
    query: str,              # FTS5 syntax: 'fuse AND boot', 'smoke*', '"exact phrase"'
    limit: int = 20,
    scope: str | None | list[str] = None,
) -> list[Entry]
```

FTS5 search over `content`. Newest-first within match.

### `get_thread`

```
get_thread(
    root_id: int,
    scope: str | None | list[str] = None,
) -> list[Entry]
```

The root entry plus all entries with `related_id = root_id`. One level deep (ADR-0004). For skill threads where root-anchoring is followed, this returns the full revision lineage.

## Metadata / discovery tools

### `list_tags`

```
list_tags(
    prefix: str | None = None,        # 'case:', 'skill-', etc.
    tree: bool = False,
    scope: str | None | list[str] = None,
) -> list[{tag, count}] | dict[category, list[{tag, count}]]
```

The tag menu. Returns every unique tag with its usage count, most-used-first. With `prefix`, only tags starting with the prefix. With `tree=True`, grouped by top-level category (text before first hyphen).

Backed by the `entry_tag` companion table (no full-table scan over `entry.tags`).

### `list_agents`

```
list_agents(
    scope: str | None | list[str] = None,
) -> list[{agent, count}]
```

Every unique agent with its entry count. Useful for "who's been writing here," for the dashboard, for the `boonyard doctor` audit (surfaces unknown agents not in the profile's `allowed` list).

### `list_entry_types`

```
list_entry_types(
    scope: str | None | list[str] = None,
) -> list[{entry_type, count}]
```

Same shape, for entry_types. Surfaces unknown types in the profile audit.

### `list_skills`

```
list_skills(
    limit: int = 50,
    scope: str | None | list[str] = None,
) -> list[Skill]
```

Each `Skill` is `{root_id, slug, latest: Entry, all_revisions: list[Entry], is_deprecated: bool}`. The skill catalog; sugar over `recent(entry_type='skill')` plus per-slug grouping.

Implementation: SELECT entries with `entry_type = 'skill'`, group by the `skill-{slug}` identity tag, materialize each skill with its root + revisions + deprecation status. Deprecation: any revision with `skill-{slug}-deprecated` tag.

### `latest_skill`

```
latest_skill(
    slug: str,
    scope: str | None | list[str] = None,
) -> Entry | None
```

The newest revision of the named skill, or null if no skill with that slug exists. Convenience for "what does this skill say *now*."

### `list_nodes`

```
list_nodes() -> list[{name, slug, created_at, entry_count, last_write_at}]
```

In aggregator deployments, returns the nodes the caller has access to. In single-node deployments, returns the one node. Used by the dashboard and by seats wanting to know what scope values are valid.

## Operational tools (admin-y; exposed in OSS, gated in SaaS)

### `node_info`

```
node_info(scope: str | None = None) -> {
    name, uuid, schema_version, created_at, entry_count,
    storage_bytes, profile: dict, last_write_at, last_read_at
}
```

Full node metadata. In SaaS, available to the owner via dashboard or API key with scope on that node.

### `audit_doctor`

```
audit_doctor(scope: str | None = None) -> {
    warnings: list[{kind, count, sample_ids}],
    suggestions: list[str],
    skill_threads_not_root_anchored: list[{slug, broken_revision_id}],
    unprecedented_tags: list[{tag, count}],
    unknown_agents: list[{agent, count}],
    unknown_entry_types: list[{entry_type, count}],
}
```

The substrate's self-audit. Exposed in OSS; in SaaS, throttled (it's a full-table scan) and gated to authenticated owner keys.

## Tools that do NOT exist (and why)

- **`delete_entry`** — per ADR-0005.
- **`update_entry_content`** — per ADR-0005.
- **`vector_search`** — per ADR-0010.
- **`subscribe`** / **`notify`** — no push/pubsub in v1; future earned feature (webhooks).
- **`run_query`** / **`execute_sql`** — the substrate does not expose raw SQL. The API surface is the substrate's contract; raw SQL would bypass the contract and create binding-by-implementation. Power users can open `journal.db` with any SQLite tool for raw SQL.
- **`embed_entry`** / **`set_embedding`** — per ADR-0010.
- **`set_entry_tags`** (the retag operation) — exposed as a CLI command (`boonyard retag`) and a Python API call (`retag_entry`) but **not** as an MCP tool, because the retag is a privileged operational action that shouldn't be invoked casually by an AI seat. Seats wanting to suggest a retag write a `decision` entry recommending it; a human or admin executes it.

## Tool versioning and stability promises

- **Stable forever:** `log_entry`, `recent`, `by_id`, `search_by_tag`, `search_text`, `get_thread`, `list_tags`. These are the v1 contract. Their names and required parameters do not change.
- **Stable since v3:** `search_by_tag_exact`, `log_skill_revision`, `list_skills`, `latest_skill`, `list_agents`, `list_entry_types`, `list_nodes`, `node_info`, `audit_doctor`.
- **Additions are minor-version bumps; removals are major-version bumps.** A breaking change to any of the above bumps the package's major version, which (per `04_distribution.md`) means a schema migration too.

## Error model

| MCP error code | When | What the seat should do |
|---|---|---|
| `not_authenticated` | No key, or key has been revoked | Re-fetch / re-issue the key |
| `not_authorized` | Key valid but not for this scope | Use a key for the right node |
| `not_found` | Node, entry, or skill doesn't exist | Stop; the reference is wrong |
| `validation` | Field missing, malformed tag, etc. | Fix the request and retry |
| `rate_limited` | Per-key rate cap hit | Wait `Retry-After`, then retry |
| `quota_exceeded` | Node-level entries or storage cap reached | Free quota or upgrade |
| `read_only` | Write attempted on aggregator endpoint | Target a specific node for writes |
| `internal` | Server-side bug | Report; do not retry blindly |

All errors include a `message` and (when possible) a `hint` suggesting the corrective action.

## See also

- ADR-0003 — scope model (which the tools implement)
- ADR-0004 — skill semantics (which `log_skill_revision`, `list_skills`, `latest_skill` codify)
- ADR-0005 — append-only (the basis for "no delete / no update tools")
- ADR-0008 — MCP routing + auth (transport / auth around these tools)
- ADR-0010 — no embeddings (why no `vector_search`)
- `01_core_primitive.md` — the Entry shape these tools return
- `03_scope_model.md` — how scope works under the hood
