# Architecture 03 — The Scope Model (per-project, in-project, over-many)

> The single architectural choice that cashes out BoonyardNN's three-mode promise.

This document elaborates ADR-0003 into practical mechanics: how the `scope` parameter works across the Python API, the CLI, and the MCP server; how an aggregator is set up; what the user does in each mode.

## The scope parameter (universal)

Every reader function in the substrate accepts an optional `scope` argument. Writers always target one node and accept `scope` only as "which node" (a string), never as a list.

| `scope` value | Meaning |
|---|---|
| omitted / `'current'` / `None` | The current node (the one the connection is opened against). |
| `'<node_name>'` (a string) | A single named node. In single-node deployments, must match the current node. In aggregator deployments, names one of the configured nodes. |
| `['<a>', '<b>', ...]` (a list of strings) | Read from these named nodes, union the results. Aggregator deployments only. |
| `'all'` | Read from every node visible to the caller. Aggregator deployments only. In SaaS, "visible" means owned by the authenticated user. |

The parameter is the same shape across Python, CLI, and MCP. Adding it once at the API layer flows through every surface.

## Mode 1 — Per-project (the default)

```
my_project/
    journal/
        journal.db
        boonyard.toml
```

One node. The MCP server (or CLI, or Python lib) opens that one file. `scope` is implicit or `'current'`. Cross-node queries don't apply.

### Setup

```bash
cd ~/Code/PlaneScape
boonyard init --name planescape
# creates journal/journal.db + journal/boonyard.toml
```

### Use

```python
from boonyard import log_entry, recent

log_entry(agent="opus", entry_type="decision", content="...")
for e in recent(limit=20):
    ...
```

```bash
boonyard log opus decision "Decided to ..."
boonyard recent 20
boonyard find "FUSE boot"
```

### MCP

```
http://localhost:8765/sse                # no node slug needed; single-node default
```

The MCP server is started with a `--db <path>` flag pointing at the one node file. The server's tools operate on that one node.

## Mode 2 — In-project (embedded)

```
vectorscape/
    server/
        boonyard/                  # vendored package, or pip-installed
        worlds/
            world-prime/
                journal.db         # one node per game world
                boonyard.toml
            world-test/
                journal.db
                boonyard.toml
```

The boonyard package is imported by the host project's runtime. Each "world" (or whatever unit the host project organizes by) has its own node.

### Setup

The package is vendored or pip-installed. The host project's startup code creates the node files at first run via `init_db`:

```python
from boonyard import init_db, log_entry

init_db("/srv/vectorscape/worlds/world-prime/journal.db",
        profile_path="/srv/vectorscape/worlds/world-prime/boonyard.toml")
```

### Use

The host project calls `log_entry` and friends from its own code paths. There's no separate MCP server unless the project's developers want to inspect the node live (which they will; see CLI access below).

```python
# Inside the game server's player-action handler:
log_entry(
    agent="player",
    entry_type="diff",
    content=f"{player_id} placed wall at ({x},{y},{z})",
    tags=f"diff,player:{player_id},build,zone:{zone_id}",
    extras=json.dumps({"x": x, "y": y, "z": z,
                       "player_id": player_id, "action": "place_wall"}),
    db_path="/srv/vectorscape/worlds/world-prime/journal.db",
)
```

The `db_path` argument is optional; the package supports a `set_default_db(path)` call for embedded use that pins the default for subsequent calls.

### CLI / MCP access in this mode

A developer who wants to inspect a world's node from the terminal:

```bash
boonyard --db /srv/vectorscape/worlds/world-prime/journal.db recent 20
boonyard --db /srv/vectorscape/worlds/world-prime/journal.db find "place_wall"
```

A developer who wants to run an MCP server pointing at one world (e.g., to let Claude analyze the player-diff history live):

```bash
boonyard mcp --db /srv/vectorscape/worlds/world-prime/journal.db --port 8765
```

## Mode 3 — Over-many / Umbrella (the aggregator)

```
~/.config/boonyard/umbrella.toml:

[nodes]
planescape  = "/home/jacob/Code/PlaneScape/journal/journal.db"
jrhood      = "/home/jacob/JRHood/data/journal.db"
spore       = "/home/jacob/Code/Spore/journal.db"
vectorscape = "/home/jacob/Code/PlaneScape/server/worlds/world-prime/journal.db"
```

The aggregator opens many nodes read-only at once. Queries can target one, many, or all of them.

### Setup

```bash
boonyard umbrella init               # creates ~/.config/boonyard/umbrella.toml
boonyard umbrella add planescape /home/jacob/Code/PlaneScape/journal/journal.db
boonyard umbrella add jrhood     /home/jacob/JRHood/data/journal.db
boonyard umbrella add spore      /home/jacob/Code/Spore/journal.db
boonyard umbrella list               # prints the configured nodes
```

### Use

```python
from boonyard import aggregator

agg = aggregator("/home/jacob/.config/boonyard/umbrella.toml")

# scope=None defaults to all configured nodes for aggregator instances
for e in agg.recent(limit=20):
    print(f"[{e['source']}] {e['agent']}: {e['content']}")

# narrow to specific nodes
for e in agg.recent(limit=20, scope=['planescape', 'jrhood']):
    print(...)

# find across everything
for e in agg.search_text("FUSE boot"):
    print(...)
```

```bash
boonyard umbrella recent 20
boonyard umbrella recent 20 --scope planescape,jrhood
boonyard umbrella find "FUSE boot"
boonyard umbrella tags --tree
```

`agg.recent` returns rows with an extra `source` field naming the originating node, so you can tell where each entry came from in a unioned result.

### MCP (aggregator endpoint)

```
http://localhost:8765/_aggregate/sse           # OSS local
https://mcp.boonyardnn.com/jacoboon/_aggregate/sse   # SaaS
```

The aggregator MCP endpoint accepts the `scope` parameter on every tool call. Write tools (`log_entry`, `log_skill_revision`) are rejected with an error: aggregator endpoints are read-only.

## Implementation: how the aggregator actually opens nodes

The aggregator's connection lifecycle is:

1. Open a primary in-memory SQLite connection (`:memory:`).
2. For each node in scope, `ATTACH DATABASE '<path>' AS '<node_name>'`.
3. Apply `PRAGMA query_only = ON` to forbid writes through this connection.
4. Generate the unioned query from the configured node names:

   ```sql
   SELECT '<node_a>' AS source, * FROM <node_a>.entry
   UNION ALL
   SELECT '<node_b>' AS source, * FROM <node_b>.entry
   ORDER BY timestamp DESC
   LIMIT N;
   ```

5. Execute, return rows.

For `search_text`, the FTS5 virtual tables are also addressable per-attached-DB:

```sql
SELECT '<node_a>' AS source, e.*
FROM <node_a>.entry e
JOIN <node_a>.entry_fts f ON f.rowid = e.id
WHERE <node_a>.entry_fts MATCH 'FUSE AND boot'
UNION ALL
SELECT '<node_b>' AS source, e.*
FROM <node_b>.entry e
JOIN <node_b>.entry_fts f ON f.rowid = e.id
WHERE <node_b>.entry_fts MATCH 'FUSE AND boot'
ORDER BY timestamp DESC
LIMIT N;
```

> **Clarification (2026-07-18, design seat, per implementation — wall entries 101/105):**
> the sketch above does not parse in practice — FTS5 `MATCH` does not accept a
> schema-qualified or aliased virtual table as its operand across an `ATTACH`
> boundary. The shipped `aggregator.search_text` therefore reuses the per-node
> `query.search_text` (each node opened read-only directly) and merges/sorts/limits
> in Python. The observable contract is identical: read-only union with a `source`
> field. ATTACH+UNION remains the prescribed mechanism for the row readers.

For `list_tags`, the aggregator can union `entry_tag` from each attached node and sum counts:

```sql
SELECT tag, SUM(n) AS n FROM (
    SELECT tag, COUNT(*) AS n FROM <node_a>.entry_tag GROUP BY tag
    UNION ALL
    SELECT tag, COUNT(*) AS n FROM <node_b>.entry_tag GROUP BY tag
)
GROUP BY tag
ORDER BY n DESC, tag ASC;
```

### Attached-DB limit

SQLite's default `SQLITE_MAX_ATTACHED` is 10. For aggregators with more than 10 nodes:

- The aggregator chunks the query into multiple ATTACH-many-then-detach-many rounds, merging results in Python.
- Or, if available, SQLite is compiled with a higher limit (some distributions ship with 125).
- For very-large-N cases (rare; this is a personal-NN substrate, not a Splunk competitor), the aggregator pre-builds a denormalized "umbrella cache" SQLite file by sequentially copying entries from each node into one DB. This is a future optimization not in v1.

## Mixed-mode setups

A user can absolutely run all three modes at once:

- PlaneScape: per-project mode, a node at `PlaneScape/journal/`.
- JRHood: per-project mode, a node at `JRHood/data/`.
- Vectorscape (the game world): in-project mode, embedded in the game server, with one node per world.
- Jacob's personal umbrella: aggregator mode, listing the PlaneScape node, the JRHood node, the Spore node, the Vectorscape world-prime node.

All four are different deployments of the same substrate. The aggregator can read from all of them in one query.

## What scope does NOT do

- It does not enable cross-node *writes*. A write is always one node.
- It does not enable cross-node *threads*. `related_id` is always within one node. (If you want cross-node references, encode them as tags: `cross-ref:planescape:42`.)
- It does not enable cross-node *foreign keys*. By design — keeping nodes structurally independent is what makes the per-node deletion / export / migration story clean.
- It does not enable cross-node *transactions*. Each node's writes commit on their own; an aggregator query reads a consistent snapshot per node but not across nodes.

These boundaries keep the aggregator simple and the per-node guarantees strong.

## Performance notes

- For an aggregator opening 5–10 nodes, query overhead is negligible. Single-digit ms for `recent(20)` across all of them.
- For 50+ nodes, the UNION ALL query becomes slow. Mitigations described above (chunking, sequential, denormalized cache).
- FTS5 queries scale per-node, then union. A "find FUSE across all nodes" query is N times slower than a single-node search.
- `list_tags(tree=True)` across many nodes returns the union vocabulary; for a single user with related projects, this is informative; for unrelated projects, the union may surface tag-name collisions that prompt rename decisions.

## See also

- ADR-0003 — the decision (the why)
- `00_overview.md` — where this fits in the whole system
- `02_schema_design.md` — the schema the aggregator is unioning over
- `06_mcp_surface.md` — how scope appears in every MCP tool
- `05_multi_tenancy.md` — how SaaS-side scope ties to user ownership
