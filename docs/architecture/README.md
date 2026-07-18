# Architecture

The operational deep-dives. Each document elaborates one piece of the system into the detail Code needs to implement, and Jacob needs to evaluate. Read `00_overview.md` first; the rest can be read in any order.

## Index

| # | Document | What it covers |
|---|---|---|
| [00](00_overview.md) | System overview | The whole system in one document. Three modes, four access surfaces, the deployment topology |
| [01](01_core_primitive.md) | The entry | What an entry is, what each field does, what the substrate guarantees, what it is not |
| [02](02_schema_design.md) | Schema design | Full DDL, triggers, query patterns, expression indexes, validators |
| [03](03_scope_model.md) | The scope model | Per-project, in-project, over-many — with code examples and aggregator mechanics |
| [04](04_distribution.md) | Distribution | pip install / vendor / Docker / SaaS — same engine, four flavors |
| [05](05_multi_tenancy.md) | Multi-tenancy | Users, nodes, teams, API keys, access control, account lifecycle |
| [06](06_mcp_surface.md) | MCP surface | Every MCP tool, every signature, error model, what doesn't exist and why |
| [07](07_freemium.md) | Freemium tiers | Free / Pro / Team feature matrix, rate limits, the "never paywall an algorithm" rule applied |
| [08](08_migration.md) | Migration paths | How PlaneScape, JRHood, Spore, Vectorscape adopt BoonyardNN |

## Related

- [ADRs](../adr/) — the decisions these docs elaborate
- [Roadmap](../roadmap/) — phasing of the build
- [Glossary](../glossary.md) — locked vocabulary
- [CHARTER](../../CHARTER.md) — the soul
