# Architecture Decision Records

Each ADR captures one load-bearing decision with its context, the decision itself, the consequences, and the alternatives considered. ADRs are append-only — superseded ones stay, with a forward pointer to the superseder. New ADRs add by number.

## Index

| # | Title | Status |
|---|---|---|
| [0001](0001-stdlib-only.md) | Stdlib-only for the boonyard package | Accepted |
| [0002](0002-fixed-core-plus-tag-namespaces-plus-json-extras.md) | Fixed core schema + tag namespaces + optional JSON extras | Accepted |
| [0003](0003-db-per-node-plus-aggregator.md) | One SQLite file per node, read-only aggregator for over-many scope | Accepted |
| [0004](0004-skill-as-first-class-entry-type.md) | Skill is a first-class entry_type, root-anchored revisions | Accepted |
| [0005](0005-append-only-no-deletes.md) | Append-only: no deletes, no in-place edits, ever | Accepted |
| [0006](0006-oss-core-saas-freemium.md) | OSS core + freemium SaaS; never paywall the algorithm | Accepted |
| [0007](0007-multi-tenant-storage-layout.md) | Multi-tenant storage layout: filesystem-per-user, file-per-node | Accepted |
| [0008](0008-mcp-routing-and-auth.md) | MCP routing and authentication: per-node endpoints + per-node keys | Accepted |
| [0009](0009-tag-discipline-and-list-tags.md) | Tag discipline: lowercase-hyphen, singular nouns, list_tags as menu | Accepted |
| [0010](0010-no-embeddings-yet.md) | No embeddings (yet); if added, optional install only | Accepted |

## Writing a new ADR

1. Pick the next number.
2. Use the structure: Status, Date, Deciders, Context, Decision, Consequences, Alternatives, References.
3. The decision should be one paragraph. The reasoning is everything around it.
4. The "Alternatives considered" section is where the work shows — if there's only one alternative listed, you probably haven't thought about it enough.
5. Add a row to this index.
6. Log the ADR's creation as a `decision` entry in the live NN, tagged `adr,adr-NNNN`.

## Changing an ADR

ADRs are append-only at the decision level. To revise:

- For a small clarification: edit in place, note the date.
- For a reversal or significant change: write a new ADR that supersedes this one. Update both the old ADR's "Superseded by" field and this index.
