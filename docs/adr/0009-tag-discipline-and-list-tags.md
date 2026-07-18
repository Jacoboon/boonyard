# ADR 0009 — Tag discipline: lowercase-hyphen, singular nouns, list_tags before write, prefer extend over mint

**Status:** Accepted
**Date:** 2026-05-20
**Deciders:** Jacob (Professor), Cowork-Opus, Chat-Opus (v1.2 author)
**Supersedes:** —
**Superseded by:** —

## Context

Tags are the substrate's primary categorization layer. Done well, they let an aggregator surface "everything tagged `decision`," let a domain query surface "everything about Enformion," and let the skill catalog surface "the FUSE boot ritual" by stable identity. Done poorly, they fork the ontology into incoherent islands (`personality` vs `personalities`, `skill-fuse-boot` vs `fuse-boot-skill` vs `skill_fuse-boot`), making retrieval unreliable and forcing every seat to invent its own private vocabulary.

The live NN already shows both ends of this spectrum. The PlaneScape journal has decent tag hygiene because Cowork-Opus owns it (v1.2 §4 routing); the JRHood NN explicitly embraces a chaotic free-form ontology (`NN.md`: *"There's no canonical tag list to maintain. The ontology is organic — it emerges from what agents actually tag things."*) and uses compound-with-underscores syntax (`sysop_session-start`). The v1.1 verification log demonstrated empirically that a stray plural splits a top-level category (`skill:` vs `skills:` in the tag tree view).

This ADR locks the tag conventions that BoonyardNN canonicalizes — strict enough to keep the ontology coherent across many nodes and many years, flexible enough to absorb both the PlaneScape-style "tagged carefully" and JRHood-style "tagged frequently and freely" cultures.

## Decision

### Naming rules

- **Lowercase only.** `decision`, not `Decision`. Validators warn on mixed case.
- **Hyphen-delimited.** `feature-request`, not `feature_request` or `featureRequest` or `feature.request`. Validators warn on underscores, dots, or camelCase.
- **No spaces.** Spaces in tags are split into multiple tags at write time, with a warning. (The CLI's `--tags` flag splits on comma; spaces inside a tag are an error.)
- **Singular nouns for top-level categories.** `skill`, not `skills`. `decision`, not `decisions`. `book`, not `books`. The validator warns on plural-ending top-level categories whose singular form is also in use anywhere in the node. (See "The plural-fork bug" below for the empirical basis.)
- **Hyphen-hierarchy for sub-categories.** `skill-fuse-boot-ritual`, not a sibling like `fuse-boot-skill`. Sub-categories extend the parent by adding more hyphens. `list_tags(tree=True)` groups by the text before the first hyphen.

### The plural-fork bug

Demonstrated in the v1.1 verification log: a node where someone wrote `skill-foo` 4 times and `skills-system` once produces a `list_tags(tree=True)` output with both a `skill:` top-level category (4 entries) and a `skills:` top-level category (1 entry). The ontology silently forks. A future seat reading the tree thinks there are two distinct namespaces.

The singular-noun rule is the empirical fix. The validator pattern:

```
if tag.startswith(plural_of(known_singular_category) + '-'):
    warn(f"tag '{tag}' uses plural form; singular '{singular}' is already in use in this node")
```

We don't try to enumerate every English plural; we look for the simple `-s` / `-es` suffix on the prefix-before-first-hyphen, compare to existing prefixes, and warn on collision. False positives are tolerable (warning, not error).

### Tag namespaces (colon syntax)

Tag namespaces are colon-delimited, not hyphen-delimited:

- `case:521-5400610` ✓
- `case-521-5400610` ✗ — this would split into the `case` top-level category in the tag tree, polluting it with thousands of leaf nodes.

The colon is the namespace separator; values inside the namespace can themselves contain hyphens (the case number `521-5400610` is a single value). `list_tags(prefix='case:')` enumerates the namespace.

Reserved namespaces are declared in `boonyard.toml` under `[tags.namespaces]` (ADR-0002 §Layer 4). The validator warns on namespace prefixes not declared in the profile.

### The two-part tagging ritual (every write)

Before writing an entry that needs tags, every seat:

1. **Pull the menu.** Call `list_tags()` (CLI: `boonyard tags`; MCP: the `list_tags` tool). For categorical work, `list_tags(tree=True)` shows the ontology grouped. For namespace work, `list_tags(prefix='case:')` shows what's been written under that namespace.

2. **Decide what to USE.** Pick existing tags that apply. Always include the mandatory type tag (matching `entry_type`). Bias *hard* toward reuse. A near-match existing tag almost always beats a fresh exact one — the cost of one extra word of imprecision is small; the cost of an ontology fork is permanent.

3. **Decide what to CREATE.** Only if nothing fits. Prefer **extending** an existing category as a sub-tag (`personality` → `personality-quirks`) over minting a sibling. Add a `TAGS-NEW: <tag> — <why>` line in the entry content so vocabulary growth is auditable.

### The `TAGS-NEW` audit convention

When introducing a new tag, the writing seat adds an audit line in the entry content:

```
TAGS-NEW: skill-fuse-boot-ritual — first skill formalized for the recurring FUSE phantom git-status problem at boot
TAGS-NEW: discipline-vocabulary — reserving a top-level category for entries about substrate conventions
```

This makes vocabulary growth queryable: `search_text("TAGS-NEW:")` finds every entry that introduced a new tag, with its justification. The convention is a discipline (no enforcement), but the substrate makes it cheap by displaying any unprecedented tag (one not previously seen in the node) prominently in the `boonyard doctor` audit output.

### Type-tag mandate

Every entry has, at minimum, the tag matching its `entry_type`. A `decision` entry has at least the `decision` tag; a `skill` entry has at least the `skill` tag. This is enforced by the package's write path (the tag is added automatically if missing). The duplication (`entry_type` column AND `tags` containing that value) is intentional: tag-based queries that span types (e.g. "every entry tagged `discussion` OR `decision`") work uniformly; the column drives the precise filter (per ADR-0004 for skills specifically).

### Tag-vocabulary hygiene as a periodic chore

For active multi-seat nodes, one seat owns the role of periodically reviewing the tag menu (`list_tags(tree=True)`) and proposing merges or normalizations via a `decision` entry. This is a *discipline* assigned to a role, not a substrate feature; in the PlaneScape NN, Cowork-Opus owns this per v1.2 §4 routing. Other nodes can assign as they see fit.

When a merge or rename is approved (e.g. merge `personalities` → `personality`), the implementation uses the `retag` operation (ADR-0005's allowed exception) and logs a single `decision` entry with the rationale, tagged `decision-vocabulary,tag-merge`.

The `boonyard tags rename --from personalities --to personality` CLI command is the operational tool for this.

### Free-form is fine; the discipline costs nothing

Nothing here *requires* a seat to consult the menu before tagging. The validator warns and the substrate captures regardless. Free-form tagging is supported — JRHood's NN.md culture of "if a new tag fits the thought, use it" remains valid; the conventions above are guidelines that compound value when followed, not gates.

The thing that prevents chaos is `list_tags`. A seat that always pulls the menu before tagging will, in practice, reuse hot tags more often than not. The chore is small, the value is large, and the cost of skipping it is paid by everyone who reads the node later.

## Consequences

**Positive:**
- The ontology stays coherent across many nodes and many seats without anyone having to police it.
- `list_tags` provides the menu that makes reuse-first behavior easy.
- The tag-tree view (`list_tags(tree=True)`) surfaces forks immediately, before they entrench.
- Tag namespaces give a structured-reference idiom without polluting the category space.
- The `TAGS-NEW` audit convention makes vocabulary growth a first-class artifact, not invisible drift.
- Free-form is preserved as the default; discipline is added by tooling, not enforcement.
- The retag operation (ADR-0005 exception) lets ontology heal itself without violating append-only.

**Negative:**
- Seats that don't consult `list_tags` before tagging still produce drift. Mitigation: the `boonyard doctor` command flags unprecedented tags and probable forks for review.
- The singular-noun rule has false positives (e.g. `news` is plural-shaped but a valid singular noun in context). Warnings, not errors, accommodate this.
- The colon-vs-hyphen distinction for namespaces is a convention seats have to learn. The CLI and docs reinforce it; new seats picking it up takes one cycle.

**Neutral:**
- Tag conventions are themselves entries in the canon and can evolve. Changes get logged as `decision` entries tagged `decision-vocabulary,charter-revision`.

## Alternatives considered

### Strict-enforce: invalid tags rejected, period

Reject any tag that violates the naming rules. No warnings, no soft validation.

**Why rejected:** Substrate's job is to capture, not gatekeep (CHARTER). Rejecting writes blocks the substrate from doing its primary job (recording what happened). The validator warns are loud enough for disciplined seats to notice and quiet enough for hot-path writes not to fail.

### No conventions; pure free-form

Just let seats tag however. No rules, no validator, no `list_tags`.

**Why rejected:** The empirical evidence from JRHood's NN shows this works *fine* for a single-project single-seat node with a single human keeping it tidy. It does not scale to multi-seat / multi-project / multi-year. The ontology forks, retrieval gets unreliable, and `list_tags(tree=True)` becomes useless. Some discipline is the cheapest version of structure.

### Canonical tag dictionary maintained by the substrate

A central list of allowed tags, with new tags requiring an approval step.

**Why rejected:** Too heavy. Every new project would need to register its tags first, raising the cost of starting a node. Doesn't compose with the substrate-is-small principle. The `list_tags` menu is the same thing, in lighter form, computed from what exists.

### Enforce singular nouns via NLP

Run a lemmatizer over every tag and reject plurals.

**Why rejected:** Brings in an NLP dependency (NLTK or spaCy), violating ADR-0001 (stdlib-only). The simple suffix-based warning catches the common cases; the edge cases (`news`, `species`, `data`) are tolerable as warnings the seat reviews.

## References

- CHARTER.md — "Load-bearing beliefs / Entry + tags = memory"
- glossary.md — `tag`, `tag namespace`, `tag tree`, `list_tags`
- v1.2 design doc, §2 — original Phase 0 tagging ritual (this ADR formalizes and elaborates)
- v1.1 implementation appendix, §0 — the empirical plural-fork bug
- JRHood NN.md, "Tagging System" — the free-form-tagging culture this ADR makes compatible
- ADR-0002 — fixed core + tag namespaces (defines the `:` namespace syntax)
- ADR-0004 — skill as first-class entry_type (uses `skill-<slug>` identity tag)
- ADR-0005 — append-only (the retag exception is the only mutation surface)
- architecture/02_schema_design.md — `entry_tag` companion table that makes equality lookups fast
- architecture/06_mcp_surface.md — `list_tags`, `list_agents`, `list_entry_types` MCP tools
