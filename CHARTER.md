# BoonyardNN — Charter

> The shared memory substrate that earns its keep across every project that adopts it.

This is the soul document. Every other file in this repo descends from the beliefs here. When a design question splits, this is the tiebreaker. When a feature request lands, this is the filter. When the work feels like it's drifting, this is the snap-back.

Read this before anything else.

---

## What BoonyardNN is

BoonyardNN is an append-only, queryable, threaded memory substrate for multi-agent collaboration. The irreducible primitive is an **entry**: a timestamped piece of text written by some named agent, optionally threaded to a previous entry, optionally tagged. The substrate guarantees that entries are never destroyed and never silently changed — corrections happen by writing new entries that reference old ones. The whole system is one table, a handful of well-chosen indexes, and the discipline to write into it.

That's it. That's the whole magic. Everything else — tag ontologies, skills, the MCP doorway, the per-project / over-many scope model, the SaaS — is shaped around protecting that primitive and making it convenient to live inside.

The substrate is being lifted out of where it was born (a `_dev/journal/` folder inside the PlaneScape codebase, adapted from the earlier Spore NN, used in passing across at least four other projects) and made into a thing of its own. The new home is this repo. The new public face is `boonyardnn.com`. The pact with the world is open source first, hosted convenience second, no lock-in ever.

## What BoonyardNN is not

BoonyardNN is not a personal AI agent. It does not run autonomous goals on your behalf. It does not message you in the morning. It does not call APIs unprompted. Hermes Agent and friends own that lane and they do it well. The substrate exists *underneath* whatever agentic surface you put on top of it — it is the journal those agents share, not an agent itself.

BoonyardNN is not a vector database. It does no embedding by default. The historic name "VectorScape NN" was a category error rooted in confusing coordinate-space vectors (the 3D xyz universe grid of the host project) with neural-net vectors. That mistake has been formally corrected (see entry 79 in the live journal). Embeddings remain a possible later capability, but they break the stdlib-only rule and they earn nothing toward naming honesty. They are explicitly not part of the default product.

BoonyardNN is not a kitchen-sink platform. There will be no Telegram gateway, no cron scheduler, no browser automation, no built-in LLM, no 40-tool surface area. The substrate is small on purpose. Agents bring their own everything else; the substrate gives them a shared place to write.

BoonyardNN is not telemetric. The OSS package phones home to nothing. The hosted SaaS records only what is structurally necessary to operate the service. No analytics on what users write into their nodes. The contents of a node are between the user and their own seats.

## Load-bearing beliefs

**The substrate is small, the discipline is everything.** The schema and query surface have to fit in one head. Each addition is a tax forever. We add things only when the absence costs more than the presence.

**Stdlib-only for the package.** Zero runtime dependencies for the boonyard Python package. SQLite is in the stdlib. FTS5 ships inside Python's bundled SQLite. JSON1 too. We don't need anything else, and not needing anything else is the entire point. Vendorability — the ability for a project to literally copy the package folder in and have it work — is a feature, not a side effect. See ADR-0001.

**Append-only, never destructive.** Entries are written, never edited or deleted. Corrections create new entries that reference the old. Skills evolve by root-anchored revisions. Bad entries get tombstoned, not removed. The substrate is an unforgetting wall. See ADR-0005.

**Entry + tags = memory.** The five core columns (agent, entry_type, content, related_id, tags) plus the FTS index over content are the substrate. Everything project-specific lives in either namespaced tags or a JSON extras column. There is no mutable per-project schema fork. The core is the same in every node. See ADR-0002.

**One node = one SQLite file.** A node is the unit of scope. Per-project mode: each project owns one node. In-project mode: a project embeds the package and runs a node inside itself. Over-many / Umbrella mode: an aggregator opens many node files read-only and unions their entries. This single architectural choice cashes out the three-mode promise. See ADR-0003.

**No lock-in, ever.** The data is a SQLite file. You can download it, open it in any SQLite tool, point your own MCP server at it, copy it to another machine, fork the code, walk away. Exit cost is `cp` of one file. This is non-negotiable. The SaaS is convenience; the substrate is yours.

**The OSS package is the SaaS.** boonyardnn.com runs the same boonyard package the OSS user pip-installs. The hosted product is *deployment, multi-tenancy, billing, and convenience*, not a different feature set. We do not paywall algorithms. We charge for the operating cost of running it for you. See ADR-0006.

## The dogfood pact (user zero)

Jacob — the user at the top of this document — is user zero. The first proof of value is that BoonyardNN compounds value across Jacob's projects (PlaneScape, JRHood, Spore, Adustum, Umbrella, Mycelium Sky, the Mike collab, whatever else surfaces). If that proves out, opening to other users is justified. If it doesn't, no one else should be paying for the privilege.

This is the explicit guardrail against the trap journal entry 75 named: spending the next six months polishing a meta-tool that's supposed to support five projects, instead of shipping those five projects. Every BoonyardNN milestone is paired with a question — *what project of mine got better because this exists*? If the answer is "none yet, but it will," that's the smell. Pause and ship a project instead.

Marketability is a free option earned by load-bearing dogfooding, never a goal chased in the absence of it.

## The audience

This canon is written for two readers.

Jacob (the Professor) reads it to understand and approve the trajectory, to push back on bad calls before they become committed code, and to use as the snap-back document when his own infinite-ideas energy starts to drift the design into incoherence.

Code (a future Claude Code instance, or any other implementing agent) reads it to execute. Every ADR is meant to leave Code with no judgment calls about the load-bearing decisions, only judgment calls about how to make the load-bearing decisions real in the simplest correct way.

Both readers should be able to disagree with the canon, but disagreement gets logged as a `discussion` entry in the live NN, threaded to the relevant ADR id once we have one in here. Drift in the canon happens through proposals, not silent edits.

## Lineage acknowledgment

The substrate did not appear from nothing. The first form was a journal pattern inside Spore, the resident-AI-on-Pi project. PlaneScape adopted it and turned it into a multi-seat shared journal during the Opiifecta work (Code + Cowork-Opus + Chat-Opus + Professor all writing into the same `journal.db`). The MCP doorway shipped in May 2026 (live journal entry 77), making the substrate reachable from any agent surface. JRHood ran a parallel evolution as `agent_log` with its own domain extensions. v1.1 (Chat-Opus) added FTS5 and `list_tags` and made `skill` a first-class type. v1.2 corrected the embeddings framing and named the extraction direction.

BoonyardNN is the formalization of all of that into one canonical thing. The previous forms are not deprecated by this work — they are absorbed by it. Migration from each existing form into a Boonyard node is a known, documented path (see `docs/architecture/08_migration.md`).

## What changes when the canon changes

This charter is meant to be stable on the scale of years. The ADRs are meant to be stable on the scale of releases. The architecture docs are meant to be stable on the scale of months. The roadmap is meant to move every week. If you find yourself rewriting the charter to justify a feature you want, the smell is the rewrite, not the canon.

Changes to this document are themselves logged as `decision` entries to the live NN with the tag `charter-revision`, threaded to the previous revision's entry. The substrate watches itself evolve.

---

*If you remember one thing from this document: an entry is a small piece of timestamped, attributed, tagged, threadable text in an append-only table, and the whole architecture of BoonyardNN exists to keep that primitive elegant and unbreakable across many projects, many agents, and many years.*
