# ADR 0006 — OSS core + freemium hosted SaaS; never paywall the algorithm

**Status:** Accepted
**Date:** 2026-05-20
**Deciders:** Jacob (Professor), Cowork-Opus
**Supersedes:** —
**Superseded by:** —

## Context

BoonyardNN has two product surfaces:

1. The **boonyard** Python package — open source, vendorable, stdlib-only, runs anywhere Python runs.
2. **boonyardnn.com** — a hosted multi-tenant service where users sign up, spawn nodes, and get MCP endpoints without running their own infrastructure.

The strategic question is the relationship between the two:

- Are they the same codebase, with the SaaS being a deployment of the OSS package?
- Are they different codebases, with the OSS package being a teaser / demo of the SaaS?
- What is paid, what is free, and what is open?
- Does the OSS package have features the SaaS doesn't, or vice versa?

The CHARTER already locks the high-order answer: *"The OSS package is the SaaS."* This ADR formalizes the licensing, the feature line, and the freemium tier shape — and locks the principle that no algorithmic capability is ever moved behind a paywall.

The dogfood pact (CHARTER) further constrains: this isn't about extracting maximum revenue. It's about user-zero (Jacob) proving the substrate compounds value across his projects, then optionally letting other users pay for the convenience of not running their own server.

## Decision

### License: Apache 2.0 for the OSS package

The boonyard package is licensed under Apache 2.0. This permits:

- Commercial use (including by businesses competing with boonyardnn.com).
- Modification and redistribution (including private forks).
- Patent grant (the patent-defense properties of Apache vs. MIT are worth the slightly heavier license text).

It does not require:

- Source-code sharing of derivatives (the substrate is most useful when embedded; copyleft would block half the use cases).
- Attribution beyond preserving the copyright notice.

MIT was considered and rejected only for the missing patent grant; for a substrate that we want widely embedded in commercial settings, Apache's explicit patent protections are worth the extra paragraphs.

### The OSS package and the SaaS run the same code

The boonyardnn.com web service is a deployment that *imports* the boonyard package. There is no "boonyard pro" private fork. There is no algorithm in the SaaS that isn't in the OSS package. The hosted product's value is *not running it yourself*, not "more features."

```
+----------------------------------------------+
|             boonyardnn.com                   |
|   web layer (auth, billing, dashboard, ...) | <- not in the OSS package
+----------------------------------------------+
|         boonyard package (OSS, Apache 2.0)   | <- same code as `pip install boonyard`
+----------------------------------------------+
|              SQLite files                    |
+----------------------------------------------+
```

The OSS user `pip install boonyard`s and gets exactly the same engine the SaaS runs. The SaaS adds web auth, multi-tenant routing, billing, a dashboard UI, and operational scaffolding (backups, monitoring, support). None of those are *features of BoonyardNN*; they are features of a hosted product.

### What is paid, what is free, what is open

| Layer | Status |
|---|---|
| The boonyard Python package | OSS, Apache 2.0, always free |
| The boonyard CLI | OSS, always free |
| The boonyard MCP server (single-tenant, local) | OSS, always free |
| The schema profile + all extras infrastructure | OSS, always free |
| The aggregator (over-many mode, local) | OSS, always free |
| Hosted account on boonyardnn.com | Free tier exists; see below |
| Hosted MCP endpoint per node | Free tier; rate-limited; see below |
| Hosted aggregator (cross-node Umbrella view) | Paid; the operational cost of running this for users is real |
| Web dashboard UI | Free for owned nodes; team/shared dashboards are paid |
| Billing, support, SLAs | Paid; this *is* what is being sold |

### Freemium tier shape (Phase 3; not before Phase 2 dogfood proves value)

**Free tier (default for any signup):**
- 1 user
- Up to 3 nodes
- Up to 10,000 entries per node
- 1 hosted MCP endpoint per node (rate-limited to a sensible-for-personal-use ceiling)
- Web dashboard, single-node view only
- 30-day backup retention
- No team sharing
- No hosted aggregator (Umbrella view)
- Community support only

**Paid tier (suggested working name: "Boonyard Pro"; final naming deferred):**
- Unlimited nodes
- Unlimited entries per node
- Higher rate limits on MCP endpoints
- Hosted aggregator across all of the user's nodes (Umbrella view)
- Team sharing (multiple users can write to one node, with named-seat attribution)
- 1-year backup retention; on-demand export to S3-compatible storage
- Web dashboard with cross-node search and the Umbrella view
- Email / chat support, response SLAs

**Self-hosted-everything always available** for users who want zero hosted footprint: install the package, run the MCP server yourself, point your seats at it. The OSS path is feature-complete; the SaaS only adds the not-having-to-run-it-yourself bit.

### Principle: never paywall an algorithm

If a capability is implemented in the boonyard package, it is open source and freely available to every OSS user. The SaaS does not gate `list_tags`, `search_text`, `get_thread`, the aggregator, the skill system, or any future package feature. The SaaS charges for:

- The compute and storage of running someone else's nodes for them.
- The convenience of not running the MCP server yourself.
- The operational work (backups, monitoring, security patches).
- The dashboard / UI on top.
- Team-oriented features that require multi-tenant state the OSS package legitimately doesn't have (cross-user permissions, billing-linked rate limits).

This principle has a real failure mode: it limits revenue extraction. Acceptable. The dogfood pact + Project-Six guardrail (CHARTER) means we are explicitly not optimizing for revenue. We are optimizing for substrate adoption; revenue is a free option earned by adoption, not a goal pursued by feature-gating.

### No-telemetry promise for the OSS package

The OSS package phones home to nothing. No update checks, no usage statistics, no version-reporting beacon. A user who pip-installs boonyard and runs the CLI offline produces no outbound network traffic from the package itself.

The SaaS, by virtue of being hosted, sees what its servers see (HTTP requests, MCP tool calls, entry write rates as operational metrics). It does not look inside entry content for analytics. It does not train models on user data. It does not share aggregated content with anyone.

A future "BoonyardNN Insights" dashboard that does cross-node pattern detection for a user *on their own data* could exist as a paid feature; it operates only over the user's own nodes, with the user's consent, and uses no LLM that sends content off-platform without explicit per-call user authorization.

## Consequences

**Positive:**
- The OSS-vs-SaaS line is honest. We are not pretending the OSS package is "the lite version"; it is the engine. Users can switch between self-hosted and SaaS at zero cost.
- License (Apache 2.0) supports the widest adoption pattern, including vendored embedding inside closed-source projects.
- The freemium line aligns with the actual cost structure: free tier costs us almost nothing per user (small SQLite files, low rate limits); paid tier covers users whose use generates real operating cost.
- "Never paywall an algorithm" prevents the slow rot where OSS features quietly stop receiving improvements while their SaaS analogues evolve.
- No-telemetry is a competitive differentiator vs. many SaaS-first agent infrastructure products.

**Negative:**
- Revenue ceiling is lower than it could be with feature-gating. Acceptable per the dogfood pact.
- A user could in principle take the OSS package and stand up a competing hosted service. Welcome. The competitive moat is operational excellence + community, not artificial scarcity.
- The free tier may attract "users" who never pay and impose load. Mitigation: free-tier rate limits, node count cap, entries cap. These cap costs without removing usefulness for solo dev work.

**Neutral:**
- Apache 2.0 contributors must sign or implicitly accept a contributor license agreement. The repo includes a simple `CONTRIBUTING.md` describing the inbound=outbound model (your contributions are licensed under the same terms you received the code under).
- Naming of paid tier ("Boonyard Pro" working name) deferred to Phase 3; market positioning may suggest a different label.

## Alternatives considered

### MIT license

Considered for simplicity. Rejected only for the missing patent grant. For a substrate intended for commercial-embedded use, the explicit patent protections in Apache 2.0 are worth the extra license text.

### AGPL or other copyleft

Rejected. Copyleft requires derivatives to be open-source, which blocks the "vendor inside a closed-source project" use case that is one of the substrate's primary adoption shapes. The cost of a copyleft license (network-effect compatibility issues, blocked embedding) exceeds the value (forced-open derivatives).

### Closed-source SaaS only

The "Notion" / "Linear" model — closed source, hosted only. Rejected because:

- It would betray the substrate's portability promise. A user whose hosted account expires loses access to their data unless we engineer an export — which is exactly the lock-in we promised to never create.
- It would prevent the substrate from being embedded in projects (the in-project mode entirely; the per-project mode for anyone uncomfortable with hosted dependencies).
- It runs against Jacob's stated values around AI-as-non-extractive-infrastructure.

### "Open core" — basic package OSS, advanced features paid in a closed module

Rejected. Every "open core" product gradually moves features from open to closed as the closed side fights for value, eroding trust in the OSS side. The line is messy in principle and worse in practice. Cleaner to keep *everything algorithmic* in OSS and price the SaaS on operational value.

### Charge for the OSS package itself

Rejected on principle and on practicality. The substrate's adoption depends on frictionless install; paid OSS doesn't exist as a sustainable model in this space.

## References

- CHARTER.md — "Load-bearing beliefs / The OSS package is the SaaS"
- glossary.md — `boonyardnn.com`, `SaaS`, `vendoring`
- ADR-0001 — stdlib-only (constrains the package; the SaaS is unconstrained)
- ADR-0007 — multi-tenant storage layout (how the SaaS organizes user data)
- ADR-0008 — MCP routing + auth (how SaaS-hosted MCP endpoints work)
- architecture/04_distribution.md — how the package and the SaaS coexist
- architecture/07_freemium.md — full feature matrix and rate-limit numbers
- roadmap/PHASE_2.md — when the SaaS goes live (user zero only)
- roadmap/PHASE_3.md — when the SaaS opens to the public + billing
