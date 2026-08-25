# BOONYARD.md — this project's memory, and how to use it

> **This file is designed to be copied into any repo that runs a Boonyard node.**
> It is the user's manual: the daily ritual, the conventions, and the full CLI.
> Your project's CLAUDE.md / instructions should point here instead of repeating this.
>
> Snapshot of **boonyard v3.0.0** (schema v3), generated from the package's own
> `--help` output 2026-07-18. When the vendored package is upgraded, refresh this
> file from `BoonyardNN/docs/BOONYARD.md`. Standing up a NEW node? See
> `ADOPTION.md` in the BoonyardNN repo first — this file assumes the node exists.

## What this is

This project's memory is a **Boonyard node**: one append-only SQLite file
(`node/journal.db`) plus one advisory profile (`node/boonyard.toml`). Entries are
timestamped, attributed, tagged, threadable text. Nothing is ever edited or
deleted; corrections are new entries that reference old ones. The node is
readable by any SQLite tool forever — exit cost is `cp` of one file.

## The daily ritual

**Boot (before working):**

```bash
boonyard --db node/journal.db recent 20        # what happened lately
boonyard --db node/journal.db tags             # the tag menu (pull BEFORE tagging)
```

**Close (after every work session):**

```bash
boonyard --db node/journal.db log <seat> <entry_type> "<what happened, one paragraph or many>" \
    --tags "<type-tag auto-added>,<domain-tags>,model:<your-model-string>" \
    --related <id-of-what-you're-continuing>
```

Rules of the ritual: `agent` is your **seat** (a role: `code`, `cowork`, `chat`,
`professor`, `system` — see this node's `boonyard.toml`), not your model. AI
seats always carry a `model:` tag with the exact model string. Corrections and
follow-ups use `--related`. If `boonyard doctor` nags you, it's advisory — the
substrate never rejects a soft-validation miss, but a recurring warning is a
signal to fix your habit or register the new value in the profile.

## The five conventions that travel (canon; identical in every node)

1. **Append-only** (ADR-0005). No deletes, no edits, ever. The sole mutation is
   `boonyard retag` — tags only, audited, reason + actor required.
2. **Seat + model identity.** `agent` = role; `model:` tag = who's driving.
   Provider-agnostic: a GPT in the chat seat is `agent=chat` + `model:gpt-5`.
3. **Tag discipline** (ADR-0009). Lowercase-hyphen, singular nouns. Pull the
   menu first (`boonyard tags`); extend existing tags rather than minting
   siblings; the entry_type is auto-added as a tag.
4. **No mixing of the batter bowls.** This node is about THIS project. Other
   projects' data is referenced (tags, provenance headers), never imported.
5. **Sidecar convention.** Fluid/editable records live in your project's own
   rigid-schema DB, joined to the node by a tag namespace (e.g. `case:12345`
   → `refunds.case_number`). The node stays pure memory.

## CLI reference

Global flags (before the subcommand): `--db <path-to-journal.db>`,
`--profile <path-to-boonyard.toml>`, `--version`. Every command supports `-h`.
In a repo with a vendored package, invoke as `python -m boonyard ...`.

### Writing

| Command | What it does |
|---|---|
| `boonyard log <agent> <entry_type> <content> [--tags a,b,c] [--related ID] [--extras JSON]` | Append one entry. The universal write. Tags are CSV; `--related` threads to a prior entry; `--extras` only if the profile enables extras. |
| `boonyard skill new <slug>` | Start (or revise) a skill — renders the SKILL/WHEN/STEPS/GOTCHAS template, root-anchored per ADR-0004. |
| `boonyard retag <id> <new_tags> --reason "<why>" --actor <who>` | The ONLY mutation. Rewrites one entry's tags, logs a meta_log audit row. Content/agent/type are untouchable. |

### Reading

| Command | What it does |
|---|---|
| `boonyard recent [n] [--agent X] [--type Y]` | Newest entries, optionally filtered. Default 20. |
| `boonyard show <id>` | One entry, full content. |
| `boonyard thread <root_id>` | Root + everything threaded to it (one level). |
| `boonyard tag <tag> [n] [--exact]` | Entries by tag. Default substring match; `--exact` uses the indexed entry_tag equality (preferred for namespaces like `case:...`, `model:...`, `skill-<slug>`). |
| `boonyard find <query> [n]` | Full-text search over content. FTS5 syntax: `fuse AND boot`, `smoke*`, `"exact phrase"`. |

### Discovery / metadata

| Command | What it does |
|---|---|
| `boonyard tags [--prefix X] [--tree]` | The tag menu with usage counts. `--prefix case:` filters; `--tree` groups by category. **Pull this before tagging.** |
| `boonyard agents` | Seats seen in this node, with counts. |
| `boonyard types` | Entry types seen, with counts. |
| `boonyard skills [n]` | The skill catalog (latest revision per slug, deprecation flagged). |
| `boonyard skill latest <slug>` | What a skill says NOW (newest revision). |
| `boonyard info` | Node metadata: name, uuid, schema version, entry count, storage, profile summary. |
| `boonyard doctor` | Self-audit: suspicious id gaps, orphans, soft-validation replay, non-root-anchored skills, missing `model:` tags, unknown seats/types. Advisory, read-only. |

### Maintenance / portability

| Command | What it does |
|---|---|
| `boonyard reindex` | Rebuild FTS + entry_tag + extras indexes from the authoritative entry rows. Non-destructive. |
| `boonyard backup [path]` | Single-file online backup (WAL-safe, doesn't block writers). Default `<db>.bak`. |
| `boonyard export [path]` | Portable zip bundle: journal.db + boonyard.toml + manifest. Default `<db>.export.zip`. |
| `boonyard import <path> [--force]` | Restore a boonyard export bundle (bundles only — not a legacy-NN migration tool). |

### Serving

| Command | What it does |
|---|---|
| `boonyard mcp [--port P] [--host H] [--key KEY]` | Serve this node over MCP (stdlib JSON-RPC/HTTP). No `--key` = open localhost; with a key (or `BOONYARD_MCP_KEY` env var, preferred — keeps it out of argv) = bearer auth enforced. |
| `boonyard mcp --config umbrella.toml` | Serve a READ-ONLY over-many aggregator instead of one node. |

### Over-many (the boonscape view)

| Command | What it does |
|---|---|
| `boonyard umbrella init` | Create an `umbrella.toml`. |
| `boonyard umbrella add <name> <path>` / `remove <name>` / `list` | Manage which nodes the view unions. |
| `boonyard umbrella recent / find / tags [--config X]` | Read across ALL registered nodes, results tagged with their source node. Reads are physically read-only (`query_only=ON`); the aggregator cannot write. |

## The splice (paste into this repo's CLAUDE.md / instructions)

```markdown
## Memory: the Boonyard node

This project's memory is a Boonyard node at `node/journal.db`. The manual is
`BOONYARD.md` at the repo root — read it once, then live the daily ritual:
`boonyard --db node/journal.db recent 20` before working; log an entry (seat as
agent, `model:` tag, disciplined tags, `--related` for follow-ups) after every
session. Append-only; the profile is advisory; `doctor` nags are homework, not
errors.
```

## Where the rest lives

- Standup / rollover of a NEW node: `BoonyardNN/docs/ADOPTION.md`
- Why it's shaped this way: `BoonyardNN/CHARTER.md` + ADRs (esp. 0002/0003/0005/0009)
- The Python API mirrors this CLI 1:1 (`from boonyard import log_entry, recent, ...`)
