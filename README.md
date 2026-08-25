# BoonyardNN

> Append-only shared memory substrate for multi-agent collaboration.
> Small on purpose. Owned by you. No lock-in, ever.

**Status:** Phase 1 shipped. The `boonyard` package works — v3.1.0, zero runtime
dependencies, 277 tests, 98% coverage — and has been running six live nodes in daily
production use since 2026-07-18. The hosted service (`boonyardnn.com`) is designed and **not
built**; see [Status detail](#status-detail).

Read [CHARTER.md](CHARTER.md) for the soul, [docs/adr/](docs/adr/) for the locked decisions,
[docs/roadmap/](docs/roadmap/) for the build sequence.

---

## What it is

BoonyardNN is an append-only, queryable, threaded memory substrate. One small Python package
operates on SQLite files. AI agents (or anything else) write *entries* — timestamped,
attributed, tagged, threadable text — and read them back via a CLI, a Python API, or an MCP
server for AI tools.

Three modes:

- **Per-project.** Each of your projects gets one node. A single SQLite file you own.
- **In-project.** Embed the package inside your project's code and use it as that project's
  own append-only event log.
- **Over-many (Umbrella).** One reader opens many of your nodes at once, read-only, and
  unions them with source tagging — your personal cross-project view.

## What it isn't

- Not a personal AI agent. The substrate is what an agent writes *into*, not the agent itself.
- Not a vector database. No embeddings by default. ([Why](docs/adr/0010-no-embeddings-yet.md).)
- Not a kitchen-sink platform. No built-in Telegram gateway, no cron, no LLM, no 40-tool surface.
- Not telemetric. The package phones home to nothing.

## Quickstart

The package is not yet on PyPI. Both install paths below work today:

```bash
# Install from source
git clone https://github.com/Jacoboon/boonyard.git
cd boonyard && pip install -e package/

cd ~/Code/my-project
boonyard init --name my-project
boonyard log opus decision "Starting work on X"
boonyard recent 5
boonyard mcp --port 8765 &        # MCP doorway for AI seats
```

Or vendor it — stdlib-only, zero deps, so copying the folder in is a supported path, not a
hack:

```bash
git clone https://github.com/Jacoboon/boonyard.git
cp -r boonyard/package/boonyard my-project/_dev/boonyard
# Now `from _dev.boonyard import log_entry` works.
```

Point an AI seat at a node by running `boonyard mcp` and giving the seat the URL plus the
bearer key. The key may be sent as an `Authorization: Bearer` header, or as the leading path
segment for clients whose connector dialogs have no header field
([ADR-0008](docs/adr/0008-mcp-routing-and-auth.md)).

Then read [docs/BOONYARD.md](docs/BOONYARD.md) — the travel manual, with the daily ritual and
the full CLI reference — and [docs/ADOPTION.md](docs/ADOPTION.md) if you are standing a node
up inside an existing project.

## The 60-second pitch

You're an AI-assisted developer (or just an AI-assisted human) and your AI tools keep
forgetting context. You've tried personal-agent memory tools and they work fine for one agent
talking to one user. But you have *multiple* agents — a Claude Code session, a Cursor session,
a custom Python script that reads docs, maybe a hosted chat instance, a teammate's Copilot —
and they need to share notes. They need to write down "I figured out the FUSE boot trick"
once so the *other* agents can find it. They need to thread decisions to the discussions that
produced them. They need to tag things so categories surface.

BoonyardNN is that shared notebook. Append-only (so no agent can erase another's notes).
Tagged and threaded (so retrieval works). Open format (SQLite, your data, your file).
Self-hostable. The design for a hosted version exists and runs the same package; switching
between them would be a file copy.

## Does it actually work?

One user, so read this as an existence proof and not a benchmark. Measured 2026-08-22 (UTC),
from `node_info` on each live node:

| Node | Born | Entries | Last write |
|---|---|---|---|
| mycelium-sky | 2026-07-18 | 402 | 2026-08-21 |
| umbrella | 2026-07-18 | 201 | 2026-08-20 |
| jrhood | 2026-07-19 | 198 | 2026-08-21 |
| tea-guru | 2026-07-19 | 128 | 2026-08-22 |
| boonyard *(this repo's own node)* | 2026-07-18 | 76 | 2026-08-22 |
| mindstorm | 2026-07-18 | 28 | 2026-08-15 |
| **total** | **35 days** | **1,033** | **~6.6 MB** |

Roughly thirty entries a day across six projects, written by a mix of human and AI seats
through local CLI calls and remote MCP connectors, with no data-loss incident on the record.

The property that turned out to matter most was not retrieval speed or tag ergonomics. It was
that **an append-only record is checkable**. Several times a seat asserted something, another
seat searched the wall, and the assertion died — including cases where the wrong number had
already been used to plan real work. A memory you can only add to is a memory you can argue
with. That is the whole thesis, and it is the part that would not survive a mutable store.

## Where to go next

| You want to | Read |
|---|---|
| Understand the soul | [CHARTER.md](CHARTER.md) |
| Understand the decisions | [docs/adr/](docs/adr/) (start with 0001, 0002, 0003, 0006) |
| Understand the system | [docs/architecture/00_overview.md](docs/architecture/00_overview.md) |
| Understand the schema | [docs/architecture/02_schema_design.md](docs/architecture/02_schema_design.md) |
| Use it day to day | [docs/BOONYARD.md](docs/BOONYARD.md) |
| Adopt it in an existing project | [docs/ADOPTION.md](docs/ADOPTION.md) |
| Understand the build sequence | [docs/roadmap/](docs/roadmap/) |
| Understand the vocabulary | [docs/glossary.md](docs/glossary.md) |
| Contribute | [CONTRIBUTING.md](CONTRIBUTING.md), then [CLAUDE.md](CLAUDE.md) |
| See what changed | [CHANGELOG.md](CHANGELOG.md) |

## License

Apache 2.0 — the package, the documentation, this README, all of it.
([Why.](docs/adr/0006-oss-core-saas-freemium.md))

## Lineage

The substrate did not appear from nothing.

- The first form was a journal pattern inside Spore, a resident-AI-on-Pi project.
- PlaneScape adopted it and made it multi-seat (four agents plus the human writing into one
  `journal.db`).
- The MCP doorway shipped in May 2026, making the substrate reachable from any AI seat.
- JRHood ran a parallel evolution as `agent_log` with case-specific domain extensions.
- A v1.1 implementation pass added FTS5 and `list_tags` and made `skill` a first-class entry
  type.
- A v1.2 reframe corrected the embeddings framing and named the extraction direction.

BoonyardNN is the formalization of all of that into one canonical thing.

## Why "Boonyard"?

The author's nickname is Jacoboon. The substrate began as a notebook in his various projects'
backyards. "Boonyard" preserves the personal-yard feeling — this is *yours*, fenced, owned —
while gesturing at the network of yards (multi-node, multi-project, eventually multi-user).
The word was a place inside a game this same codebase's ancestor once hosted; the memory
layer took the name of somewhere its own entries used to describe.

It is also not "Vector" anything — which is the [other](docs/adr/0010-no-embeddings-yet.md)
thing this product wants to not be.

## Status detail

**Shipped and working:**

- The `boonyard` package — `package/boonyard/`, v3.1.0, stdlib only, 277 tests, 98% coverage.
- Schema v3: closed 8-column `entry` table, FTS5 full-text index, `entry_tag` companion,
  `meta` + `meta_log`.
- The CLI (22 commands), the Python API, backups, export/import bundles.
- The over-many aggregator (read-only union across nodes, source-tagged).
- The MCP server — 16 tools, bearer-key or capability-URL auth, streamable-HTTP compatible.
- The full design canon: CHARTER, 10 ADRs, 9 architecture docs, glossary, 4-phase roadmap,
  adoption kit, travel manual.

**Designed, not built:**

- The hosted service at `boonyardnn.com` — [PHASE_2](docs/roadmap/PHASE_2.md) (single-tenant
  MVP) and [PHASE_3](docs/roadmap/PHASE_3.md) (public signups, billing, teams). The storage
  layout ([ADR-0007](docs/adr/0007-multi-tenant-storage-layout.md)) and the freemium line
  ([ADR-0006](docs/adr/0006-oss-core-saas-freemium.md)) are locked; no server code exists.
  There is no signup, no waitlist, and no date. The self-hosted path is the only path today,
  and it is feature-complete.
- Writable multi-node routing — one connector fronting N nodes, with cross-node writes gated
  by per-node seat registration. Requirement captured; ADR unwritten.

**Known open items** are listed in [CHANGELOG.md](CHANGELOG.md) under *Known open items* —
including two real defects in the aggregator worth knowing before you register a node with a
hyphen in its name or a node from an older schema.

**Tracking the work:** this project journals to its own node, in this repo at `node/`
(gitignored — the data is a live artifact and never goes in git). The git history and the
CHANGELOG are the public record.
