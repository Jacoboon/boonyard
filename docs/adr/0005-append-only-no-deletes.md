# ADR 0005 — Append-only: no deletes, no in-place edits, ever

**Status:** Accepted
**Date:** 2026-05-20
**Deciders:** Jacob (Professor), Cowork-Opus
**Supersedes:** —
**Superseded by:** —

## Context

The substrate's whole value proposition rests on durability. A seat that writes an entry must be able to trust that the entry will still be there, in the same form, the next time the seat (or any other seat) looks. Without that guarantee, every recall becomes provisional — "this is what the substrate said the last time I checked, who knows now" — and the compounding effect of multi-seat shared memory evaporates.

There are two ways the durability can be violated:

- **Hard delete:** an entry that existed is gone. References to its id break. Audit trails dead-end.
- **In-place edit:** an entry that existed has different content now. References still resolve but their semantics shift silently. Other seats' analyses, threads, and skills that referenced this entry are now operating on different ground without any signal that the ground moved.

The substrate must rule out both. This is also exactly the property that lets the aggregator work cheaply (ADR-0003): if entries are immutable, the read layer never has to invalidate cached results based on writes elsewhere.

## Decision

**No DELETE statements against the `entry` table, ever.**
**No UPDATE statements against the `entry` table's `content`, `agent`, `entry_type`, or `related_id` columns, ever.**

The only mutations the substrate accepts are:

- **INSERT** new entries (the universal write path).
- **UPDATE** to `entry.tags` — and only via the package's `retag_entry()` helper, which logs the retag as a `meta` entry. (See "Allowed exception" below.)
- **UPDATE** to the `meta` table (schema_version, node_uuid, etc. — not content).

The package enforces this. There is no public API to delete or content-edit an entry. The `boonyard` CLI has no `delete` or `edit` subcommand. The MCP server exposes no such tools.

### Corrections happen by writing new entries

If a seat realizes a previous entry was wrong, the correction path is:

```python
log_entry(
    agent="cowork-opus",
    entry_type="discussion",
    content="Correcting entry 42: the SignNow webhook signature uses sha256, not sha1 as I originally claimed.",
    related_id=42,
    tags="correction, signnow, original-entry-42"
)
```

The original entry stays. The correction is appended. `get_thread(42)` shows both. A future seat reading the thread sees the lineage: claim → correction. The substrate is unforgetting *and* self-revising.

### Deprecation happens by tombstone

When a skill, decision, or other artifact is obsolete, write a final entry that names it and marks it dead:

```python
log_entry(
    agent="code",
    entry_type="skill",
    content="SKILL fuse-boot-ritual is superseded by skill-fuse-boot-v2 (entry 187). Use that instead.",
    related_id=42,  # root id of the original skill
    tags="skill, skill-fuse-boot-ritual, skill-fuse-boot-ritual-deprecated, tombstone"
)
```

`list_tags(prefix='skill-')` now surfaces both `skill-fuse-boot-ritual` and `skill-fuse-boot-ritual-deprecated`, and the seat sees the deprecation without having to know to look.

### Allowed exception: tag corrections

Tags are the one mutable surface. The reason is operational: tag-vocabulary drift happens (ADR-0009), and merging a misspelled `personalities` into `personality` across hundreds of entries shouldn't require a parallel correction-entry-per-row. The package exposes a `retag` operation that runs `UPDATE entry SET tags = ... WHERE id = ?` and logs a single `meta` entry recording the change:

```python
retag_entry(
    entry_id=42,
    old_tags="discussion,chat-opus,personalities",
    new_tags="discussion,chat-opus,personality",
    reason="merging plural-vs-singular drift; see entry 119 for the ontology decision"
)
```

The `meta` log entry recording the retag is itself append-only. The audit trail of "what was retagged when and why" remains complete; only the live tag string on the row changes. Same applies to bulk retag operations (`boonyard tags rename --from personalities --to personality`) which log one meta entry per row touched.

This exception exists because tags are *index data*, not content. The substrate's durability promise is about content; tags are the navigation layer over content. Making the navigation layer self-healable doesn't violate the promise.

### Schema-level enforcement

The substrate doesn't merely *recommend* append-only; it makes deletion difficult enough to require explicit intent:

- The `entry` table is created with no `ON DELETE CASCADE` from anywhere — no incidental cascading deletes.
- No public Python API or MCP tool issues `DELETE FROM entry`. A user who wants to delete (e.g. before exporting) has to open the SQLite file directly with another tool. This is a feature; the friction is the point.
- The package's database-open path optionally runs `PRAGMA query_only=ON` for read paths (aggregator, reader functions), making writes physically impossible in those contexts.
- The `boonyard doctor` command audits for impossible-deletion-marker artifacts (orphaned `related_id` references, missing `id`s in autoincrement sequence) and reports them as suspicious.

## Consequences

**Positive:**
- The substrate's durability promise is real, not just nominal.
- Aggregation is cheap because entries are immutable — no cache invalidation across nodes.
- Audit trails always trace back to a real entry.
- Append-only enables append-only patterns elsewhere in the system: log-based replication, event sourcing, undo by reverting to a snapshot, all become natural.
- Corrections-as-entries means the *fact that something was corrected* is visible. A silent edit hides that fact.
- The append-only ethos applies fractally: skills version themselves by appending; the canon vocabulary appends; the schema versions append. Everything composes.

**Negative:**
- Storage grows monotonically. Acceptable: text is cheap, SQLite compresses well, and pruning is a future earned phase (per-node archive policy that *moves* old entries to an `entry_archive` table — itself append-only — never deletes).
- Mistakes are visible forever. A seat that writes an embarrassing typo can't take it back, only correct it. Acceptable: the same property is what makes the substrate trustworthy.
- A user who *really* wants to delete an entry (for privacy or legal reasons) has to either drop the whole node or open the SQLite file directly. Acceptable: at the SaaS layer, this is supported with a "redact entry" operation that replaces the content with `[redacted on YYYY-MM-DD by user request]` while preserving the id and metadata; the redaction itself is logged as a meta entry. The substrate proper still doesn't delete; the SaaS layer's policy supports a privacy-redact path. (See architecture 05.)

**Neutral:**
- Backups don't have to capture "the latest version" of anything — every backup of every entry is the same data forever. Cuts incremental-backup complexity.

## Alternatives considered

### Allow deletes, log them in a `tombstones` table

Permits DELETE, but every delete writes a row to a parallel `tombstones(deleted_entry_id, deleted_at, deleted_by, reason)` table.

**Why rejected:** Half-measure. The original content is still gone. The tombstone records *that* something was deleted but not *what*. Threads break (`related_id` points at a non-existent row). The aggregator has to handle "row used to be here, isn't now" specially. All the cost of the design, with most of the property lost.

### Allow in-place edits, log the diff

Permits UPDATE, but every UPDATE writes the diff to a parallel `edits` table.

**Why rejected:** Same shape as above. The semantics shift silently from the perspective of the live `entry` row. Code paths that read `entry.content` get different answers over time. The audit trail exists but you have to know to consult it. The "correction is a new entry" pattern gets the audit trail for free, in the place readers are already looking.

### Soft delete via an `is_deleted` flag

Add `is_deleted BOOLEAN DEFAULT FALSE` to the `entry` table. Readers default to filtering it out.

**Why rejected:** Every read query gets an `AND is_deleted = FALSE` clause forever. Readers that forget it leak deleted rows; readers that include it lose the "show me the deleted" debugging option. Forks the substrate into "real entries" and "shadow entries" — the categorical clarity of "every row is real" goes away. The correction-as-new-entry pattern handles every legitimate "I wish I hadn't written that" case better.

### Permit deletes via a strict admin-only API

Like above but the delete path requires an admin role and explicit cli flags.

**Why rejected:** Reintroduces the temptation. Every delete-permitting design has been used to delete things in haste. The friction of "open the SQLite file in another tool" is exactly the level of intent we want before a deletion happens.

## References

- CHARTER.md — "Load-bearing beliefs / Append-only, never destructive"
- glossary.md — `append-only`, `tombstone`
- ADR-0002 — fixed core schema (mutability of tags is the single exception)
- ADR-0004 — skill revisions as append-only thread (uses this property)
- architecture/01_core_primitive.md — append-only as substrate guarantee
- architecture/05_multi_tenancy.md — SaaS redact-entry policy (preserves immutability while supporting privacy)
