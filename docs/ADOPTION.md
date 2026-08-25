# Adopting Boonyard — standing up a node in your project

> Authored by the design seat, 2026-07-18 (Phase 1, M9 era; node entry logged).
> For: anyone standing a node up inside an existing project — a legacy-journal
> retrofit or a green field. This document is deliberately self-contained — a project thread
> handed only this file should be able to stand up a working node cold.

## Vocabulary (so we all say the same thing)

- **The NN** — the lineage and the concept: an append-only, queryable, threaded
  memory substrate for multi-agent collaboration. Spore NN → PlaneScape NN →
  JRHood NN → Boonyard is its family tree.
- **boonyard** — the package. The engine. Stdlib-only Python, one import.
- **A node** — one project's instance: exactly one SQLite file plus one
  `boonyard.toml` profile (ADR-0003). *This is what you are standing up.*
- **The boonscape** — Professor's name for the whole constellation of nodes,
  seen from above. The over-many aggregator (Umbrella mode) is how you see it.

## What you are about to make

One directory in your project:

```
<your-project>/node/          # or _dev/node/, your call — gitignore it
    journal.db                # the node. THE memory. one file.
    boonyard.toml             # the profile: seats, entry types, namespaces
```

That's the entire footprint. Exit cost forever = `cp` of one file.

## Step 1 — Get the package

Two sanctioned routes (arch 04):

**Vendoring (preferred for in-project mode):** copy the package folder in.

```
cp -r <path-to-boonyard-repo>/package/boonyard  <your-project>\_dev\boonyard
```

Zero deps, so this just works on any Python 3.11+. Your project imports it as a
first-party module.

**Editable install (fine for per-project mode):**

```
pip install -e <path-to-boonyard-repo>
```

Either way, verify: `python -m boonyard --version` (or `python -c "import boonyard"`).

## Step 2 — Initialize the node

```
cd <your-project>
boonyard init --name <project-slug>       # e.g. planescape, jrhood, mycelium-sky
```

This creates `node/journal.db` (schema v3: entry table, FTS5, entry_tag, meta,
meta_log) and a starter `boonyard.toml`. **Gitignore `node/` immediately** —
and mind the gotcha that bit us: gitignore does NOT support inline comments;
`node/` goes on its own line.

## Step 3 — Author the profile

Open `node/boonyard.toml` and make it yours. Everything in it is **advisory**
(ADR-0002 soft validation): unknown values warn but insert, always. The profile
teaches; it never gatekeeps.

```toml
[node]
name = "<project-slug>"
schema_version = 3

# Seats are ROLES, not models (wall entry 97 → this canon's convention).
[agents]
code      = "implementing seat"
cowork    = "design seat"
chat      = "consumer-chat seat"
professor = "the human — decides"
system    = "automated entries"

[entry_types]
allowed = [
    "prompt", "implementation", "decision", "discussion", "lint_finding",
    "verification", "vision", "error", "note", "skill", "hotfix", "milestone",
]

[tags.namespaces]
model = "exact model string driving the seat this entry (model:claude-opus-4-8, model:gpt-5, ...)"
# Add your project's own foreign-key namespaces here (ADR-0002 Layer 2), e.g.:
# case  = "JRHood refund case number (case:521-5400610 -> refunds.case_number)"
# track = "Mycelium Sky track id"

[extras]
enabled = false   # flip on only if you need structured JSON per entry
```

## Step 4 — Genesis entry

The node's first memory should be its own birth. From the project's own voice:

```
boonyard --db node/journal.db log code milestone \
  "GENESIS — <project>'s Boonyard node is born. Rolled over from <legacy NN, if any>. ..." \
  --tags "milestone,genesis,model:<your-model-string>"
```

## Step 5 — The conventions that travel (non-negotiable)

These are the canon; they apply in every node identically:

1. **Append-only** (ADR-0005). No deletes, no edits. Corrections are new entries
   referencing old ones (`--related <id>`). The sole mutation is the audited
   `boonyard retag` (reason + actor required).
2. **Seat + model identity** (wall entry 97). `agent` = your seat (role).
   Every AI-seat entry carries a `model:` tag with the exact model string.
   Provider-agnostic: a GPT in the chat seat writes `agent=chat` +
   `model:gpt-5`. `boonyard doctor` softly nags omissions.
3. **Tag discipline** (ADR-0009). Lowercase-hyphen, singular nouns. Pull
   `boonyard tags` (the menu) before tagging; prefer extending over minting;
   the entry_type is auto-added as a tag.
4. **No mixing of the batter bowls** (wall entries 94–95). Your node is about
   YOUR project. Other projects' data never gets imported into it — reference
   it via tags/entries if you must, verbatim-archive only your own lineage.
5. **Sidecar convention, not machinery** (wall entries 88–91). Fluid, editable,
   high-frequency records belong in your project's own rigid-schema DB; join it
   to the node via a tag namespace (JRHood's `case:` is the worked example).
   The node stays append-only memory.

## Step 6 — Legacy NN rollover (if your project has one)

Your old NN (agent_log, journal.db v2, NN.md culture, memory/ folder — whatever
form) is one-of-a-kind, and its rollover is **your project's own bespoke work**
(wall entry 95: no migration tooling ships in the package). Guidance:

- `docs/architecture/08_migration.md` in the BoonyardNN repo is the *guidance*
  document — shapes, spot-checks, cutover discipline. It is not shipped code.
- Write a one-off script in your own repo. Keep the legacy store intact and
  read-only afterward (rename/archive, never delete).
- Curation is allowed: you may roll over everything, or verbatim-archive the
  load-bearing lore with provenance headers + `wall:`-style namespace tags
  (see the Boonyard node's own M9 archive, node entries 6–57, for the worked
  pattern — provenance header + verbatim content + era summaries as related
  entries).
- Your project's CLAUDE.md / NN.md / instructions get updated to point at the
  node and this document (the "convention splice" deferred from Phase 0,
  wall entry 89 — its time is now).

## Step 7 — (Optional) Serve it

Local MCP: `boonyard mcp --db node/journal.db --port <free-port>` — check the
port is actually free first; 8765 may be occupied (ask the vectorscape wall how
we know). For chat-surface access, front it with a cloudflared tunnel on a
subdomain + the bearer key (`BOONYARD_MCP_KEY` env var — key never in argv,
never in git). The Boonyard node's own setup (node entries 3–4) is the worked
example: hidden launcher, Startup shortcut, auth on from day one.

Not every node needs a tunnel. A node used only by Code + local tools is fine
with no server at all — the CLI and Python API are full citizens.

## Step 8 — Register with the boonscape

When your node exists, tell the Boonyard node (an entry tagged with your
project's name), and add your node to the umbrella config when Umbrella stands
up its over-many view:

```
boonyard umbrella add <project-slug> <path-to-your-journal.db>
```

The aggregator opens nodes read-only (`PRAGMA query_only=ON`) and unions with a
`source` field. Your node stays sovereign; Umbrella only ever reads.

## Step 9 — Drop the manual in

Copy `BoonyardNN/docs/BOONYARD.md` — the user's manual (daily ritual,
conventions, full CLI reference) — to your repo root as `BOONYARD.md`. It is
designed to travel; it carries its package-version stamp so you know when to
refresh it. Then your CLAUDE.md only needs the splice below.

## The splice block

Paste (adapted) into your project's CLAUDE.md / project instructions:

```markdown
## Memory: the Boonyard node

This project's memory is a Boonyard node at `node/journal.db`. The manual is
`BOONYARD.md` at the repo root — read it once, then live the daily ritual:
`boonyard --db node/journal.db recent 20` before working; log an entry (seat as
agent, `model:` tag, disciplined tags, `--related` for follow-ups) after every
session. Append-only: corrections are new entries, never edits. The legacy NN
at <old-path>, if present, is archived read-only — consult, never write.
```

## See also

- `CHARTER.md` — why the substrate is shaped this way (read it once, whole).
- ADR-0002 / 0003 / 0005 / 0009 — the four you'll actually feel day-to-day.
- `docs/architecture/03_scope_model.md` — per-project / in-project / over-many.
- `docs/architecture/08_migration.md` — legacy rollover guidance.
- The Boonyard node's entries 6–57 — the archive pattern, worked, in production.
