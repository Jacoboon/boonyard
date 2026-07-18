# ADR 0004 — Skill is a first-class entry_type, retrieved by type, versioned by root-anchored revision

**Status:** Accepted
**Date:** 2026-05-20
**Deciders:** Jacob (Professor), Cowork-Opus
**Supersedes:** —
**Superseded by:** —

## Context

A skill is a reusable how-to a seat writes after solving something non-obvious, so a future seat retrieves the answer instead of re-deriving it. The motivating example is the FUSE boot ritual on the PlaneScape repo, which according to live journal entry 66 was re-derived **seven times** before anyone formalized the pattern.

Without skills, every non-obvious problem gets solved fresh per session, and the substrate accumulates only *events* (what happened) and *decisions* (what was chosen), not *procedures* (how to do it next time). The v1 NN substrate didn't have skills as a first-class concept; the v1.1 implementation appendix introduced them and the v1.2 reframe locked the conventions.

The v1.1 work has tested two key facts that this ADR locks in:

1. **Retrieval must use `recent(entry_type='skill')`, not `search_by_tag('skill')`.** The tag-search reader is `LIKE %tag%` substring-matching; querying it for `skill` pulls in `skills-system` discussion entries, `skill-deprecated` tombstones, and any other `skill*` mention. The type column is the precise filter; the tag space is the messy categorization layer.

2. **`get_thread` is one level deep.** Tested in v1.1: a chained skill revision lineage `v1 ← v2 ← v3` (each pointing at its immediate predecessor) returns only `{v1, v2}` from `get_thread(v1)` because v3's `related_id` points at v2, not v1. Convention has to compensate.

## Decision

### Skill is a column-level entry_type

`skill` is in the `entry_types.allowed` default list of every schema profile. It is also a tag automatically — every skill entry has both `entry_type = 'skill'` and `tags` containing `skill`.

Retrieval is by type:

```python
recent(entry_type='skill')          # the whole skill catalog
recent(entry_type='skill', limit=5) # newest 5 skills
```

The MCP layer exposes a convenience tool, `list_skills`, that is sugar for `recent(entry_type='skill')` with a higher default limit and a friendlier return shape.

### Content template

```
SKILL: <imperative one-liner — what this lets you do>
WHEN: <the retrieval hook — when to reach for this>
STEPS:
  1. ...
  2. ...
GOTCHAS: <the thing that bit us; the non-obvious failure mode>
SOURCE: <prompt-N / commit / entry id where this was learned>
```

The **WHEN** line is load-bearing. It is the answer to "if I'm in situation X, do I need this skill?" A WHEN that reads "when you need to do X" is useless; a WHEN that reads "before any FUSE-mounted repo operation, especially after a session reboot or working-tree reset" is the kind of hook a future seat will actually match against.

### Mandatory tags

Every skill entry has, at minimum:

- `skill` (the type tag, matching the entry_type)
- `skill-<slug>` (the stable identity tag, shared across all revisions of this skill)
- relevant domain tags (e.g. `fuse`, `boot`, `git`)

The `skill-<slug>` identity tag is the *only* stable identifier of a skill across its revisions. The entry `id` changes with each revision; the slug does not. `list_tags(prefix='skill-')` gives the catalog of all known skill identities.

### Root-anchored revisions

To improve a skill, write a new `skill` entry with `related_id = the_original_skill_entry.id`. **Never** thread to the previous revision.

```
✗ WRONG:
    v1 (root, id=42)
    v2 (id=51, related_id=42)
    v3 (id=63, related_id=51)  ← v3 invisible to get_thread(42)

✓ RIGHT:
    v1 (root, id=42)
    v2 (id=51, related_id=42)
    v3 (id=63, related_id=42)  ← all revisions visible from get_thread(42)
```

`get_thread(root_id)` returns the root plus all entries that point at it, in id order. Newest entry in the thread wins by convention. The Python API and MCP both expose a `latest_skill(slug)` convenience that returns the newest revision of a named skill — sugar over `get_thread`.

### Deprecation by tombstone

Skills are never deleted. When a skill is obsolete, write a final entry tagged `skill-<slug>-deprecated` with content explaining why and pointing at the replacement (if any). The tombstone surfaces in the catalog so future seats know to avoid the original.

### v1 is prompted, not autonomous

A seat writes a skill when it notices one. There is no autonomous skill-extraction loop. Building a "skill-detector" agent that watches entries and proposes skills is a future earned phase; for now, the discipline is human-prompted, and the substrate's job is only to make capture and retrieval cheap. (See architecture 06 for what the MCP surface for this looks like.)

## Consequences

**Positive:**
- The substrate gets a *third* register beyond events (notes/decisions/discussions/implementations) and arcs (sessions/prompts): procedures. Skills compound across sessions in a way nothing else does.
- The retrieval rule is one line of API (`recent(entry_type='skill')`), unambiguous, and immune to the tag-pollution problem.
- Skill identity (`skill-<slug>`) survives across all revisions; the substrate can present "the FUSE boot ritual" as a stable thing even though its content evolves.
- Root-anchored revisions keep `get_thread` one-level-deep (which it already is and probably will stay), so we don't have to ship a recursive-CTE version of `get_thread` to support skill versioning.

**Negative:**
- Convention has to compensate for the one-level `get_thread`. A seat that forgets to root-anchor a revision produces a skill lineage that splits silently. Mitigation: the `boonyard doctor` CLI lists skill threads whose latest revision points at a non-root entry; the MCP `log_skill_revision` tool requires a `root_id` argument and computes the right thread for you.
- Skills don't have a deletion mechanism. Deprecated skills accumulate, surfaced via the tombstone tag. Acceptable; storage is cheap and deprecation lineage is itself valuable.

**Neutral:**
- The skill content template is convention, not enforced by the substrate. A `boonyard skill new` CLI command renders the template; `boonyard skill lint <id>` warns if a skill entry doesn't conform. Validation stays soft (substrate captures, validators warn).

## Alternatives considered

### Make skill a separate table, not an entry_type

A `skills` table with its own schema: `slug`, `latest_revision_content`, `created_at`, `updated_at`.

**Why rejected:** Loses append-only semantics for skills specifically. Loses the unified `entry` query surface (`recent` doesn't see skills any more; the MCP layer has to wrap two tables). The whole point of "one substrate, many uses" is undermined when one use gets its own table. The first-class-entry_type pattern keeps skills inside the substrate and proves the substrate generalizes.

### Retrieve skills via tag, not by entry_type

`search_by_tag('skill')` returns the skill catalog.

**Why rejected:** The v1.1 verification log demonstrated the pollution: `search_by_tag('skill')` returned a `skills-system` *discussion* entry and a `skill-deprecated` *tombstone* alongside the actual skills. The type column is the right filter; tags are for categories on top of that. (Locked in this ADR; documented in `architecture/06_mcp_surface.md`.)

### Allow editing skill content in place (mutable)

When a skill improves, update the existing row's `content` column.

**Why rejected:** Breaks ADR-0005 (append-only). Loses the audit trail of how the skill evolved. The whole skill-revisions-as-entries pattern is a load-bearing demonstration of why append-only is right.

### Thread revisions to the immediate predecessor, fix `get_thread` to be recursive

Make `get_thread` recursive via a CTE so chained revisions work without root-anchoring.

**Why rejected:** Adds complexity to a core reader that is otherwise one line of SQL. The root-anchoring convention is cheap (one rule to remember) and the recursive CTE has subtle performance implications on deep threads. The convention costs nothing; the implementation change has a maintenance tail. *Not* a closed door — if a future arc needs general-purpose deep threading for something other than skills, we revisit. For now, convention is enough.

## Worked example: the FUSE boot ritual skill (the proof-by-existence)

```
agent: code
entry_type: skill
tags: skill, skill-fuse-boot-ritual, fuse, boot, git, prompt-39

content:
SKILL: Detect FUSE-mount phantom git-status corruption at session boot
       and recover without nuking the working tree.

WHEN: At session boot, especially after any cross-session restart, if
      `git status` reports the working tree as gutted, files as deleted,
      or unstaged changes that don't match what was on disk last session.
      Always check this before reacting to any git-status "deleted" claim.

STEPS:
  1. Take a screenshot or text dump of the suspect git status output.
  2. Run `ls` on the directories that git claims are empty. If the files
     are present, the git output is phantom — proceed.
  3. Run `git stash` to confirm there are no actual unstaged changes.
     If stash is a no-op, the corruption is purely in git's worldview.
  4. Disambiguate with `cat .git/HEAD` and `git log -1 --stat`. If both
     succeed and reference real commits, the repo is intact.
  5. Issue `git status` a second time. The phantom usually clears.
     If it persists, restart the shell session; do NOT `git checkout .`
     or any destructive recovery — that's how the previous incidents
     destroyed actual work.

GOTCHAS:
  - The phantom manifests in at least three forms (whole-tree, single-file,
    untracked-only); pattern-match on "files I just edited claim to be
    deleted" rather than on a specific git error string.
  - DO NOT trust the first git-status reading at session boot. Treat it
    as a probe, not a fact.

SOURCE: prompt-39 + earlier seven re-derivations; first formalized
        2026-05-11 (entry 66 banked the pattern).
```

This is the kind of skill the substrate exists to retain. Saved once; retrieved by every future Code seat with `recent(entry_type='skill')`; identity-stable across revisions via `skill-fuse-boot-ritual`.

## References

- CHARTER.md — entries-as-memory + the dogfood pact
- glossary.md — `skill`, `root-anchored revision`, `tombstone`
- v1.1 implementation appendix, §0.3 + §0.4 + §1a — original retrieval correction and root-anchoring correction
- v1.2 design doc, §2 — the Phase 0 skill conventions block
- architecture/06_mcp_surface.md — `list_skills`, `log_skill_revision`, `latest_skill` tool signatures
- ADR-0005 — append-only (why edits are forbidden)
- ADR-0009 — tag discipline (how `skill-<slug>` slots into the namespace rules)
