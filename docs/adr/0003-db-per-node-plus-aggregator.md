# ADR 0003 — One SQLite file per node, read-only aggregator for over-many scope

**Status:** Accepted
**Date:** 2026-05-20
**Deciders:** Jacob (Professor), Cowork-Opus
**Supersedes:** —
**Superseded by:** —

## Context

BoonyardNN promises three usage modes:

- **Per-project:** one node per project. PlaneScape has its node, JRHood has its node, Spore has its node.
- **In-project:** the boonyard package is embedded inside a single project and used as that project's own append-only event log (Vectorscape's player-diff layer).
- **Over-many / Umbrella:** one reader sees across many of the user's nodes at once.

These modes don't just need to coexist — they need to share enough machinery that adopting one doesn't paint a project out of the others. The decision here is the *one foundational architecture choice* that makes the three-mode promise cashable: where does a node live, and how does an aggregator read across many?

The v1.2 design doc named the two viable options:

- **Option A:** Each node is its own SQLite file. The over-many mode is an aggregator that opens many files read-only (SQLite `ATTACH DATABASE`) and unions the results.
- **Option B:** One SQLite file, every entry has a `project_id` column, all queries are scoped on it.

The doc recommended A. This ADR confirms and elaborates.

## Decision

**One SQLite file per node.** The node is the unit of storage, the unit of scope, the unit of ownership in the SaaS, and the unit of backup / export / migration. The path is conventionally `<somewhere>/<node_name>/journal.db` with `boonyard.toml` next to it.

**Aggregator opens many nodes read-only via `ATTACH DATABASE`.** The over-many / Umbrella mode is a separate read path that takes a list of node identifiers, opens each as a read-only attached database, and unions the entries via a generated query of the shape:

```sql
-- For nodes named 'planescape', 'jrhood', 'spore', 'vectorscape':
SELECT 'planescape'  AS source, * FROM planescape.entry
UNION ALL
SELECT 'jrhood'      AS source, * FROM jrhood.entry
UNION ALL
SELECT 'spore'       AS source, * FROM spore.entry
UNION ALL
SELECT 'vectorscape' AS source, * FROM vectorscape.entry
ORDER BY timestamp DESC
LIMIT 50;
```

The aggregator never writes. Writes always go to one specific node.

**A `scope` parameter is added to every reader.** Default: the current node. Explicit list: a set of node names to ATTACH. Special value `all`: every node visible to the caller (in SaaS, all of a user's nodes; in OSS, every node listed in the aggregator's config).

```python
recent(limit=20, scope='current')            # default: this node only
recent(limit=20, scope=['planescape', 'jrhood'])
recent(limit=20, scope='all')
```

The same `scope` shape extends to the MCP layer (see ADR-0008 and architecture 06).

## Consequences

**Positive:**
- Maps 1:1 to the three-mode promise. Per-project = one DB file. In-project = the project owns that one DB file directly. Over-many = aggregator opens many files. No tortured remapping.
- **Isolation by construction.** A bug in one node's tooling can't damage another node. A bad migration applied to JRHood's node can't take down PlaneScape's node. Backup, restore, delete, archive — all operate on one file.
- **Trivial teardown.** `rm /path/to/node/journal.db` deletes one node and nothing else. Compared to the column-scoped option, where deleting a project's entries means a `DELETE WHERE project_id = ...` that has to vacuum and reindex.
- **Aggregator is read-only and stateless.** No write contention, no transaction coordination across nodes. The aggregator can be killed and restarted with no data implications. Multiple aggregators on the same set of nodes don't fight.
- **Backup story is dead simple.** SQLite's online backup API on one file. Or `cp` the file when the WAL is checkpointed. Or rsync. Per-node retention policies don't require row-level work.
- **Export and import is one file.** The "no lock-in" promise (CHARTER) is mechanical: the user downloads the `.db` file and they have everything.
- **Schema migrations apply per-node and are independently versioned.** A node at schema v3 can sit next to a node at schema v4 in the aggregator; the read layer handles the column differences (none, by ADR-0002) or refuses to aggregate non-mutually-compatible versions.

**Negative:**
- An aggregator query that opens 50 attached DBs is heavier than a single-table query. SQLite has a hard limit (default 10) on attached databases per connection; tunable via `SQLITE_LIMIT_ATTACHED` at compile time, or by chunking the query in the aggregator. Acceptable: a single user with 50 active nodes is the wrong support level for a default-config SQLite anyway; the aggregator chunks if needed.
- Cross-node queries need to be regenerated when the set of nodes changes. The aggregator already does this each call; cost is negligible.
- Writes must commit to one node — there is no "write to all nodes" path. This is a feature; cross-node writes are nearly always a smell that the entry belongs at a different level.

**Neutral:**
- The SaaS layer (see ADR-0007) puts each node's file under a per-user directory, which is the natural storage layout for one-file-per-node. No tension with multi-tenancy.

## Alternatives considered

### Option B — One DB + `project_id` column on every entry

Every node lives in the same SQLite file. Every entry has a `project_id` column. Every query is scoped on `WHERE project_id = ?`.

**Why rejected:**
- No isolation by construction. A bug in tooling can write to the wrong project. A bad migration touches all projects. A teardown is a `DELETE`, not a `rm`.
- Every query must remember to scope. Forgetting it is a footgun that leaks data across projects, which in SaaS is a security incident.
- One file grows forever. The substrate has no cap on entry count per project; combining many projects compounds.
- The aggregator-friendly cross-project query is trivial here (`WHERE project_id IN (...)`), but the cost is paid by every single-project query as well.
- Migration of an existing JRHood NN, an existing PlaneScape NN, etc., into a single Boonyard DB requires reconciling autoincrement IDs, related_id references, and the schema variations they came in with. Per-node files migrate independently and don't conflict.

The B model is what you'd build if you started from a SaaS-multi-tenant mindset and forgot the OSS embedded use case. Since BoonyardNN is OSS-first, A wins.

### Option C — Hybrid: one DB per *user*, project as a column

Every user has one SQLite file containing all their nodes' entries, with a `project_id` column inside. Aggregator queries are within-file, no ATTACH needed.

**Why rejected:** Inherits B's isolation problems within a user. Per-project backup, export, and tooling still have to filter on project_id. The OSS user (who doesn't have a "user" boundary) doesn't benefit. Adds a level (user / project / entry) without a paying constituency.

### Option D — One DB per node, but everything in one giant ATTACH always

Same storage as Option A, but the aggregator opens *all* the user's nodes by default instead of being explicit per query.

**Why rejected:** Every query pays the open-many-files cost even when only one node is needed. Defeats the lightweight default. The opt-in `scope` parameter is cleaner.

## Operational notes

**SaaS path layout** (see ADR-0007 for full):
```
/data/users/{user_id}/
    nodes/
        planescape/
            journal.db
            boonyard.toml
            backups/
                journal.db.2026-05-20T00:00:00.bak
        jrhood/
            journal.db
            boonyard.toml
        ...
```

**OSS path layout** (per-project):
```
my_project/
    _dev/boonyard/             # the vendored package, or pip-installed
    journal/                   # this project's node
        journal.db
        boonyard.toml
```

**OSS path layout** (in-project, e.g. Vectorscape):
```
vectorscape/
    server/
        boonyard/              # vendored package
        worlds/
            world-prime/
                journal.db
                boonyard.toml
            world-test/
                journal.db
                boonyard.toml
```

The `boonyard` CLI's `aggregate` command takes either an explicit list of paths or a config file pointing at them:

```bash
boonyard aggregate --node ./planescape --node ./jrhood --recent 20
boonyard aggregate --config umbrella.toml recent 20
boonyard aggregate --config umbrella.toml find "FUSE boot ritual"
```

`umbrella.toml`:
```toml
[nodes]
planescape  = "/home/jacob/Code/PlaneScape/_dev/boonyard/journal.db"
jrhood      = "/home/jacob/JRHood/data/journal.db"
spore       = "/home/jacob/Code/Spore/journal.db"
vectorscape = "/home/jacob/Code/PlaneScape/server/worlds/world-prime/journal.db"
```

## References

- CHARTER.md — "Load-bearing beliefs / One node = one SQLite file"
- glossary.md — `node`, `aggregator`, `scope`, `over-many mode`
- v1.2 design doc, §1 "Routable / scopable" — original recommendation of Option A
- architecture/03_scope_model.md — full elaboration with code patterns
- architecture/05_multi_tenancy.md — how nodes map to users in SaaS
- ADR-0002 — fixed core schema (makes uniform aggregation possible)
- ADR-0007 — multi-tenant storage layout (the SaaS path layout)
- ADR-0008 — MCP routing (how scope param maps to MCP endpoints)
