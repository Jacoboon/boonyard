# ADR 0013 — Derived views: ghosts, arcs, heat, and the panel — derived, never declared

**Status:** ACCEPTED 2026-09-07 — Professor's ruling, verbatim on the umbrella wall (the decision entry threaded to #360): *"I'll go with your recommendations."* Build order heat → ghosts → arcs → panel; read heat on by default with a per-node opt-out and a privacy-page sentence; the arc label rule as written; the six legacy walls are the acceptance test. Owed since umbrella #338; Code implements.
**Date:** 2026-09-07
**Deciders:** Jacob (Professor); drafted by the Conductor (Cowork, model:claude-fable-5-1) from `Umbrella/CODE_MEMO_PHASE2_BACKBONE_AND_NEXT_V_20260906.md` §3–§5 and umbrella #229, #240, #324, #338
**Supersedes:** —
**Superseded by:** —

## Context

Professor's words (umbrella #337): *"When I say 'the NNs need to be smarter' I mean the arc_map and other things we've discussed … some sort of other type of organizational map or other structured sorting mechanism … time table data … a usage stat map, even down to the per entry granularity."* His earlier framing: the node *"lacks a table of contents"* (boonyard #64); a compiler *"so an entire node can be observed at a glance"* against *"thoughts and todos buried and lost under thousands of entries"* (umbrella #56); the arc map is *"a victim, not a failure"* — starved of tags, not broken (#240); it is a **Boonyard capability**, not an Umbrella script (#324).

The record (memo §3, eight rows, each with an id): the **panel** (#30; `panel_pull.py`; dark since the cutover, #325) · the **arc map** (boonyard #64, umbrella #56; `arc_map.py`; #229: five arcs unchanged since July, 421 orphans, the `arc:` convention dead in practice; dark since the cutover) · the **orphan sweep** (#56; half-shipped as `upcoming_dates(prefix="open")`, #234: 421 → 16 → 5 for the *dated* half) · the **register** (`upcoming_dates`, shipped 3.2.0, boonyard #77) · the **meter** (`read_stats`, shipped 3.2.0, boonyard #82 — node granularity, arguments never recorded) · the **intake mouth** (#61, parked) · the **hook** (#228, not built) · his framing (#317, #324). Not found anywhere: any other "organizational map."

The one new idea (memo §4): **per-entry read heat** — a sidecar recording the entry ids a read *returned*, never the query. It redefines a ghost from "an entry nobody tagged" to "an entry nobody has read," which is #229's *instrument with no reader* made measurable per row.

The finding that decides the shape (#229, memo §5): **arcs by declaration failed** — tagging by exhortation fails, 8-for-8 on rule-shaped remedies (#228) — so **arcs by derivation** (`related_id` chains and time, no discipline required) is the only design that survives contact with real seats. Umbrella #338 accepted the memo on every point and named the Code seat's ordering as the standing recommendation: orphan sweep with read heat first, arc map second.

Constraints from the canon: the `entry` table does not change (ADR-0002 fixed core; ADR-0005 append-only); views are minor versions (3.3, 3.4 …), never v4 (memo §1c); nothing reads content for anything but the user's own request (ADR-0006, arch 05); the tool surface is identical OSS and hosted (ADR-0008) — a derived view that ships is a package tool, free to every self-hoster, or it does not ship (ADR-0006).

## Decision

### 1. The principle: derived, never declared

A view is a **query over tables that already exist** (`entry`, `meta`, the read-stats sidecar, and one new sidecar column). It asks no seat to tag anything, thread anything, or remember a convention. Where a convention exists (`arc:`, `open:`, `killdate:`), the view may *read* it as a label; membership is never decided by it. A view that needs discipline to be true is not a view; it is a rule, and rules are 0-for-8 here.

### 2. The four views, in build order

**2a. Read heat (the prerequisite sidecar; 3.3.0).** The meter (boonyard #82) gains a second table: `read_hit(ts, tool, entry_id)` — one row per entry id a read tool **returned** (`recent`, `by_id`, `search_text`, `search_by_tag`, `get_thread`, `upcoming_dates`). Never the query text, never the arguments, never the caller (per-node keys cannot say who; they say whether — memo §4). Aggregated by `read_stats` as before, plus a new `entry_heat(entry_id) → {reads, last_read}` and a `heat` column wherever an entry is listed. Retention: rows older than 180 days roll up to counts. Entry ids are not content; this is operational metadata and it is **stated on the privacy page** (a new class of stored metadata is a privacy-page sentence, not a footnote).

**2b. Ghosts (the orphan sweep, derived; 3.3.0).** `ghosts(limit?, older_than_days?, scope?)` returns root entries (no `related_id`) that have **no children** and **no reads** in the window, ranked coldest-first, with their age and tags. The dated half stays where it is (`upcoming_dates(prefix="open")`, #234); `ghosts` is the *undated* half #234 left open. One tool, CLI parity (`boonyard ghosts`), no tags required — this is the Code seat's recommendation and #338's, kept.

**2c. Arcs (the table of contents, derived; 3.4.0).** An **arc** is a connected component of the `related_id` graph, computed, not declared: root = the oldest entry in the component; members = every entry reachable by `related_id` in either direction (chains, not one level — `get_thread` stays one level per ADR-0004; `arcs` walks). Per arc: root id, first and last timestamp, member count, **tag snowball** (union of member tags, weighted by count), total heat, and a **label** — the `arc:` tag if any member carries one, else the root's first line. `arcs(limit?, since?, scope?)` lists arcs by last-touched; `arc(root_id)` returns one with its members in time order. This is #56's compiler and #64's table of contents, with the `arc:` convention demoted from membership rule to optional name — which is exactly what #240 asked for: the map stops starving.

**2d. The panel (composite; 3.5.0).** `status(scope?)` — one call that returns what `panel_pull.py` used to hand-build (#30): per-node counts and newest id, the last backup heartbeat, both registers, the top ghosts, the hottest arcs, reads-vs-writes. `boonscape_state.json` becomes the output of one tool run, not a script over museum files (#325). The Umbrella cross-node view in the dashboard (arch 07, Pro) is this tool rendered.

### 3. Where it lives

Package tools first (ADR-0006, ADR-0008: the surface is identical everywhere); the hosted node browser (boonyard #120) renders them — a "ghosts" tab and an "arcs" tab are the natural home the handoff named. Umbrella's `arc_map.py` and `panel_pull.py` are retired the day 2c and 2d ship (a tombstone entry each, ADR-0005's pattern), not before.

### 4. What this ADR does not decide

The intake mouth (#61) and the hook (#228) are *consumers* of these views and stay parked on their own rows. A chronology/timeline view beyond `arcs` (memo §3 row 4) is not designed here; if `arcs` in time order is not it, that is a discussion entry when he says so.

### Decisions — ruled 2026-09-07 (*"I'll go with your recommendations"*)

| # | Choice | Decision |
|---|---|---|
| 1 | Build order | **heat → ghosts → arcs → panel**, one minor version each; heat and ghosts together in one Code sitting |
| 2 | Read heat default | **on**, for every node, stated on the privacy page; a per-node `[meter] heat = false` in `boonyard.toml` for anyone who wants it off |
| 3 | The arc label rule | **`arc:` tag if present, else the root's first line** |
| 4 | Whether the six legacy walls get a run of 2b/2c as the acceptance test | **yes** — the umbrella wall's 421 orphans (#229) are the benchmark; a `ghosts` run that returns the five #234 left is the proof it works |

### Adjacent, same sitting, not a derived view — the `instructions` surface (Professor, 2026-09-07)

Raised the day this ADR was accepted and routed beside it because it rides the same minor version: *"an 'instructions' command that every node will serve the same … like a help or readme … one static command away … each node gets a zero or one entry for this, with tags like 'readme' 'instructions' 'agents'."* Two halves, neither a schema change: (a) the MCP `initialize` result gains the spec's optional `instructions` string — the package's own readme (the 18 tools, the read law, the write conventions, the register prefixes), static per version, free to every self-hoster, zero commands away when the client injects it; (b) a per-node readme as a **skill with the reserved slug `readme`** (ADR-0004's root-anchored revisions give exactly the zero-or-one lineage he described; `latest_skill("readme")` already returns it), plus a sugar tool `instructions(scope?)` returning (a) + the node's `readme` if present. Recorded here as adjacent scope; the decision entry is on the boonyard wall.

## Consequences

**Positive:** the arc map comes back to life without anyone tagging anything, which is the only way it was ever going to. Ghosts become measurable by the one signal that cannot be faked — nobody read it. The panel stops being a script over dead files. Every self-hoster gets all of it (ADR-0006).

**Negative:** one more sidecar table and a write on every read path — bounded (one row per returned id), but a `recent(50)` writes fifty rows; the 180-day roll-up is not optional. Component-walking over `related_id` is a graph traversal on every `arcs` call; cache it per node keyed on newest id.

**Neutral:** the `arc:` namespace survives as a naming convention with zero obligation, which is what a convention should have been. ADR-0009's tag discipline is unaffected.

## Alternatives considered

**Fix the `arc:` convention with better exhortation (a boot-doc rule, a lint).** Rejected: #228's audit — rules 0-for-8, machinery 2-for-2. #229 said it; #240 confirmed the map was the victim of exactly this.

**A declared `arc` column on `entry`.** Rejected: ADR-0002's fixed core; ADR-0005; and it is declaration again with a schema change on top.

**Embeddings / topic clustering for arcs.** Rejected: ADR-0010 (no embeddings yet; optional install if ever). `related_id` is the structure seats already produce for free.

**Ship the panel first (it is the thing Professor sees).** Rejected: the panel is a composite of the other three; built first it is `panel_pull.py` again. Eyes before the dashboard of eyes.

**Per-entry heat with caller attribution.** Rejected: per-node keys make callers indistinguishable by design (boonyard #82; ADR-0008), and recording who read what is the one thing the meter promised never to do.

## References

- umbrella #30, #56, #61, #228, #229, #234, #240, #317, #324, #325, #337, #338; boonyard #64, #77, #82
- `Umbrella/CODE_MEMO_PHASE2_BACKBONE_AND_NEXT_V_20260906.md` §3–§5 (the eight rows with ids; the read-heat idea)
- ADR-0002, ADR-0004, ADR-0005, ADR-0006, ADR-0008, ADR-0009, ADR-0010
- `Umbrella/scripts/arc_map.py`, `panel_pull.py` (the prototypes this retires)
