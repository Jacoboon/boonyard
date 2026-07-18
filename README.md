# BoonyardNN

> Append-only shared memory substrate for multi-agent collaboration.
> Small on purpose. Owned by you. No lock-in, ever.

**Status:** Pre-Phase-1. The substrate is fully designed; the package extraction is next. Read [CHARTER.md](CHARTER.md) for the soul, [docs/adr/](docs/adr/) for the locked decisions, [docs/roadmap/](docs/roadmap/) for the build sequence.

---

## What it is

BoonyardNN is an append-only, queryable, threaded memory substrate. One small Python package operates on SQLite files. AI agents (or anything else) write *entries* — timestamped, attributed, tagged, threadable text — and read them back via a CLI, a Python API, an MCP server for AI tools, or (in the hosted version) a REST API and web dashboard.

Three modes:

- **Per-project.** Each of your projects gets one node. PlaneScape has a node. JRHood has a node. Spore has a node. Each is a single SQLite file you own.
- **In-project.** Embed the package inside your project's code and use it as the project's own append-only event log. (Vectorscape's player-diff layer is the worked example.)
- **Over-many (Umbrella).** One reader opens many of your nodes at once and unions them — your personal cross-project view.

## What it isn't

- Not a personal AI agent. The substrate is what an agent writes *into*, not the agent itself.
- Not a vector database. No embeddings by default. ([Why](docs/adr/0010-no-embeddings-yet.md).)
- Not a kitchen-sink platform. No built-in Telegram gateway, no cron, no LLM, no 40-tool surface.
- Not telemetric. The OSS package phones home to nothing. The hosted service records only what it needs to operate.

## Quickstart (OSS, when Phase 1 ships)

```bash
pip install boonyard

cd ~/Code/my-project
boonyard init --name my-project
boonyard log opus decision "Starting work on X"
boonyard recent 5
boonyard mcp --port 8765 &        # MCP doorway for AI seats
```

Or vendor it (stdlib-only, zero deps):

```bash
git clone https://github.com/jacoboon/boonyard.git
cp -r boonyard/package/boonyard my-project/_dev/boonyard
# Now `from _dev.boonyard import log_entry` works.
```

## Hosted (when Phase 2 ships)

Sign up at [boonyardnn.com](https://boonyardnn.com), spawn a node, copy the per-node MCP URL + API key, point your AI seats at it. Same package, hosted for you.

## The 60-second pitch

You're an AI-assisted developer (or just an AI-assisted human) and your AI tools keep forgetting context. You've tried personal-agent memory tools and they work fine for one agent talking to one user. But you have *multiple* agents — Claude Code, a Cursor session, a custom Python script that reads docs, maybe a hosted Claude instance, a teammate's GitHub Copilot — and they need to share notes. They need to write down "I figured out the FUSE boot trick" once so the *other* agents can find it. They need to thread decisions to the discussions that produced them. They need to tag things so categories surface.

BoonyardNN is that shared notebook. Append-only (so no agent can erase another's notes). Tagged + threaded (so retrieval works). Open format (SQLite, your data, your file). Self-hostable OR hosted. The OSS package and the hosted product run the same code; switching between them is a file copy.

It's been used in five+ of one person's projects for the last year — the canon you're looking at is the formalization of what works.

## Where to go next

| You want to | Read |
|---|---|
| Understand the soul | [CHARTER.md](CHARTER.md) |
| Understand the decisions | [docs/adr/](docs/adr/) (start with 0001, 0002, 0003, 0006) |
| Understand the system | [docs/architecture/00_overview.md](docs/architecture/00_overview.md) |
| Understand the schema | [docs/architecture/02_schema_design.md](docs/architecture/02_schema_design.md) |
| Understand the build sequence | [docs/roadmap/](docs/roadmap/) |
| Understand the vocabulary | [docs/glossary.md](docs/glossary.md) |
| Contribute / implement | [CLAUDE.md](CLAUDE.md) |

## License

Apache 2.0. The package, the documentation, this README — all of it. ([Why.](docs/adr/0006-oss-core-saas-freemium.md))

## Lineage

The substrate did not appear from nothing.

- The first form was a journal pattern inside Spore, the resident-AI-on-Pi project.
- PlaneScape adopted it and made it multi-seat (Code + Cowork-Opus + Chat-Opus + Professor all writing into one `journal.db`).
- The MCP doorway shipped in May 2026 (live NN entry 77), making the substrate reachable from any AI seat.
- JRHood ran a parallel evolution as `agent_log` with case-specific domain extensions.
- The v1.1 implementation appendix (Chat-Opus) added FTS5 and `list_tags` and made `skill` a first-class entry type.
- The v1.2 reframe (Chat-Opus) corrected the embeddings framing and named the extraction direction.

BoonyardNN is the formalization of all of that into one canonical thing.

## Why "Boonyard"?

The user's nickname is Jacoboon. The substrate began as a notebook in his various projects' backyards. "Boonyard" preserves the personal-yard feeling (this is *yours*, fenced, owned) while gesturing at the network of yards (multi-node, multi-project, eventually multi-user).

It is also not "Vector" anything — which is the [other](docs/adr/0010-no-embeddings-yet.md) thing we want this product to not be.

## Status detail

This repository, today, contains:

- The full design canon (CHARTER + 10 ADRs + 9 architecture docs + glossary + 4-phase roadmap).
- A `package/boonyard/` placeholder directory.
- A `CLAUDE.md` briefing the implementing agent.

What it does *not* yet contain:

- Working package code (Phase 1).
- A hosted SaaS deployment (Phase 2).
- Public signups + billing (Phase 3).

Track progress via the [live NN](https://nn.vectorscape.uk/sse) — `search_by_tag('boonyard')` for the latest.
