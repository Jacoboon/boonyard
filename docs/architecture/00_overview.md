# Architecture 00 — System Overview

The whole BoonyardNN system in one document. Read this first; everything in `01_*` through `08_*` is a deep-dive on a piece of what's described here.

## The 100-foot view

BoonyardNN is an append-only, queryable, threaded memory substrate. The substrate is a small Python package that operates on SQLite files. Around the package sit four access surfaces (Python API, CLI, MCP server, REST API for the SaaS) and two deployment shapes (OSS — run it yourself; SaaS — let boonyardnn.com run it for you). At the center of all of it is the **entry**: one row of tagged, threaded, attributed text in an append-only table.

```
                          +-----------------------------+
                          |   The Entry (irreducible)   |
                          |                             |
                          | agent | entry_type | content|
                          | related_id | tags | extras  |
                          +-------------+---------------+
                                        |
                                        v
                          +-----------------------------+
                          |  Node = one SQLite file +   |
                          |  one boonyard.toml profile  |
                          +-------------+---------------+
                                        |
                  +---------------------+---------------------+
                  |                                           |
                  v                                           v
    +-------------------------+              +----------------------------+
    | OSS deployment:         |              | SaaS deployment:           |
    | the user runs the       |              | boonyardnn.com runs the    |
    | boonyard package        |              | same boonyard package      |
    | on their own machine    |              | on infrastructure for them |
    +-------------------------+              +----------------------------+
                  |                                           |
                  +---------------------+---------------------+
                                        |
                                        v
                          +-----------------------------+
                          |  Access surfaces (any of):  |
                          |    Python API               |
                          |    CLI (boonyard ...)       |
                          |    MCP server (for agents)  |
                          |    REST API (SaaS only)     |
                          +-----------------------------+
                                        |
                                        v
                          +-----------------------------+
                          |  Consumers:                 |
                          |    AI seats (Code, Opus,    |
                          |       Chat, custom agents)  |
                          |    Human users              |
                          |    Other applications       |
                          +-----------------------------+
```

## The three modes

### Per-project mode

Each project owns one node. PlaneScape has a node. JRHood has a node. Spore has a node. Each is its own SQLite file with its own schema profile. The node serves as the project's shared substrate — seats working on that project read/write only that node.

This is the default and most common shape. The substrate's hosted endpoint (in SaaS) maps to one node; the OSS user typically initializes one node per project they want substrate for.

### In-project mode

A project embeds the boonyard package directly in its own codebase and uses the substrate as part of its own runtime. The substrate isn't just for the project's dev journal; it *is* the project's append-only event store.

Vectorscape's player-diff layer is the worked example: every player action in the game writes an entry into a Boonyard node (one node per world, possibly per shard). The substrate's primitives (tagged threaded entries, append-only, FTS5 over content, JSON extras for structured data) happen to be exactly what an event-sourced game state model needs.

This mode showcases that BoonyardNN is more general than "AI agent dev journal" — it is **append-only event-substrate infrastructure** that AI dev journaling is one excellent use case for.

### Over-many / Umbrella mode

A reader opens many nodes at once and unions their entries. Implemented by the aggregator (ADR-0003): one process, multiple SQLite files attached read-only, queries that target the combined view.

For a single user, this is their personal cross-project view: see all my recent entries across PlaneScape, JRHood, Spore, etc., or search for "deploy" across everything I've ever written. For a team (eventual paid feature), the aggregator can be configured to span team-owned nodes too — but only across nodes the user has read access to.

The Umbrella vision from live journal entry 75 (the meta-cognitive layer that reads across all projects to surface cross-project patterns) is a **consumer** of the over-many mode; it is not itself part of BoonyardNN. BoonyardNN provides the data layer; Umbrella reads from it.

## The deployment topology

### OSS, local

```
+--------------------------------------------------------------+
|   user's laptop                                              |
|                                                              |
|   +-----------+    +----------------+    +---------------+   |
|   |  AI seat  |--->|  MCP server    |--->| boonyard pkg  |   |
|   | (Claude,  |    | (boonyard mcp) |    | (Python lib)  |   |
|   |  Cursor,  |    +----------------+    +-------+-------+   |
|   |  custom)  |                                  |           |
|   +-----------+                                  v           |
|                                          +---------------+   |
|   +-----------+                          | journal.db    |   |
|   | terminal  |---> boonyard CLI ------->| boonyard.toml |   |
|   +-----------+                          +---------------+   |
|                                                              |
+--------------------------------------------------------------+
```

The MCP server runs on `localhost:8765` (or wherever the user wants). No auth. Multiple seats can hit it; multiple nodes can be served from one MCP process via path-based routing (`/{node_slug}/sse`).

### OSS, embedded in a project

```
+--------------------------------------------------------------+
|   the host project's runtime                                 |
|                                                              |
|   +------------------+    +--------------------+             |
|   | project code     |--->| boonyard (vendored)|             |
|   | (game server,    |    | imported directly  |             |
|   |  agent runner,   |    +---------+----------+             |
|   |  etc.)           |              |                        |
|   +------------------+              v                        |
|                              +---------------+               |
|                              | journal.db    |               |
|                              | boonyard.toml |               |
|                              +---------------+               |
+--------------------------------------------------------------+
```

No MCP server. No CLI in the loop (for the runtime). The package is just an import. The host project uses `log_entry` and `recent` like any other library call. (The MCP server and CLI are still available for the project's developers to inspect what's happening; they just aren't in the hot path.)

### SaaS, multi-tenant

```
+-------------------------------------------------------------+
|   boonyardnn.com (DigitalOcean droplet, or wherever)        |
|                                                             |
|   +------------+   +-----------------+   +---------------+  |
|   |  AI seat   |-->| mcp.boonyardnn  |-->| boonyard pkg  |  |
|   | (anyone's) |   | .com/$user/$node|   | (same OSS pkg)|  |
|   +------------+   +-----------------+   +-------+-------+  |
|                            ^                     |          |
|   +------------+           |                     v          |
|   |  web user  |-->[dashboard, signup,    +--------------+  |
|   |  (browser) |   billing, key mgmt]     | /data/users/ |  |
|   +------------+        (Flask)           |   $user_id/  |  |
|                            ^              |    nodes/    |  |
|                            |              |     $slug/   |  |
|                            |              |    journal.db|  |
|                            |              |    *.toml    |  |
|                            +-> auth -+    +--------------+  |
+-------------------------------------------------------------+
```

Web layer (Flask or similar — not stdlib because the SaaS is permitted external deps; see ADR-0006) handles auth, signup, dashboard, billing. MCP server is the same path-based router from OSS, deployed behind the auth layer and serving multi-user paths. Storage is one filesystem per user, one directory per node (ADR-0007).

## The access surfaces

All four surfaces (Python API, CLI, MCP, REST) live on top of the same `boonyard` package functions. Adding a feature once (in the package) makes it appear on every surface.

### Python API

```python
from boonyard import log_entry, recent, search_text, get_thread

log_entry(agent="opus", entry_type="decision",
          content="Decided to ...", tags="decision,arc-x")

for e in recent(limit=20, entry_type="decision"):
    print(e["content"])
```

Used by: scripts, applications that embed the substrate (in-project mode), tests, the implementations of the other three surfaces.

### CLI

```bash
boonyard init                     # create the node (in current directory)
boonyard log opus decision "..."  # append an entry
boonyard recent 20                # newest 20
boonyard recent 5 --type skill    # newest 5 skills
boonyard tags --tree              # the tag ontology
boonyard find "FUSE boot"         # FTS5 search
boonyard aggregate --config umbrella.toml recent 20
```

Used by: developers operating the substrate at the shell, ops jobs, scheduled tasks.

### MCP server

Long-lived process exposing tools over MCP-SSE / MCP-HTTP. Authenticated in SaaS, open in OSS-local. The principal access path for AI seats.

Used by: AI agents (Claude Code, Cursor, custom agents) that speak MCP.

### REST API (SaaS only)

```
GET    /api/v1/nodes
POST   /api/v1/nodes/{slug}/entries
GET    /api/v1/nodes/{slug}/entries?limit=20&type=skill
GET    /api/v1/nodes/{slug}/entries/{id}
POST   /api/v1/nodes/{slug}/export
...
```

Used by: the web dashboard, third-party integrations the user wires up, ops tooling.

## The data flow

A single write traverses (in OSS local) — seat → MCP server → boonyard.log.log_entry → SQLite INSERT (with triggers populating `entry_fts` and `entry_tag`).

A single read traverses — seat → MCP server → boonyard.query.<reader> → SQLite SELECT (possibly across multiple ATTACHed nodes in aggregator mode).

In SaaS, the only addition is the web auth layer in front of the MCP server, and the optional cross-node routing into multiple per-user node files.

## What's NOT in the system

- **No queue / pubsub.** Writes are synchronous. Readers don't get push notifications. (Future earned feature: webhooks. Not in v1.)
- **No LLM.** The substrate doesn't generate text or call LLMs. Seats above the substrate may; the substrate just stores what they write.
- **No scheduler.** The substrate doesn't run jobs. Scheduled tasks that *use* the substrate are entirely the host project's concern.
- **No browser automation, no email gateway, no chat bot.** These belong above the substrate. The substrate is event storage with a good MCP face.
- **No telemetry.** OSS package phones home to nothing; SaaS sees operational metrics, never entry contents (ADR-0006).

## Where to read next

- The **entry** primitive: `01_core_primitive.md`
- The **schema** in full DDL: `02_schema_design.md`
- The **scope model** (how aggregation works): `03_scope_model.md`
- The **distribution story** (package + SaaS): `04_distribution.md`
- The **multi-tenancy model** (users, nodes, teams): `05_multi_tenancy.md`
- The **MCP surface** (every tool, full signatures): `06_mcp_surface.md`
- The **freemium tier line**: `07_freemium.md`
- The **migration paths** from existing NNs: `08_migration.md`

For decisions and rationale, see `../adr/`.
For phasing of the build, see `../roadmap/`.
For terms, see `../glossary.md`.
For the soul, see `../../CHARTER.md`.
