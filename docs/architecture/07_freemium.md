# Architecture 07 — Freemium tiers (feature matrix, rate limits, the line)

The operational expression of ADR-0006's "never paywall an algorithm" principle. This document is the source of truth for what each tier of boonyardnn.com gets. OSS is omitted from the matrix here because OSS gets everything algorithmic — see ADR-0006.

## The line

Free tier covers personal solo-developer use. Paid tier covers the operational cost of running more nodes / more storage / more compute / more attention for users whose use generates real load. Team tier covers the additional state needed for cross-user collaboration.

The line is operational, not feature-based. We never have a "Pro-only" algorithm; we have "Pro-only" *amounts* of nodes / storage / compute / retention.

## The matrix

| Capability | Free | Pro | Team (Phase 3) |
|---|---|---|---|
| **OSS access (everything in the package)** | yes | yes | yes |
| Nodes | 3 | unlimited | unlimited |
| Entries per node | 10,000 | unlimited (soft) | unlimited (soft) |
| Storage per node | 100 MB | 5 GB soft / per-plan total | per-plan |
| Storage total per user/team | 250 MB | per-plan total | per-plan |
| API key writes / minute | 30 | 600 | per-plan |
| API key reads / minute | 600 | 6,000 | per-plan |
| Burst multiplier | 10× | 10× | 10× |
| MCP endpoints per node | 1 | 1 (multiple keys ok) | 1 (per node) |
| Web dashboard | single-node view | single-node + aggregator (Umbrella) view | + team-shared view |
| Hosted aggregator (Umbrella) | — | yes | yes |
| Cross-node search (Umbrella) | — | yes | yes |
| Cross-team aggregation | — | — | yes |
| Backups | daily | daily + on-demand snapshots | daily + on-demand |
| Backup retention | 30 days | 1 year | 1 year |
| Export (one-off bundle) | yes (manual) | yes (programmatic + manual) | yes |
| Export to user's S3 bucket | — | yes | yes |
| Webhook on entry write | — | yes (Phase 3.5) | yes |
| Team member count | — | — | per-plan |
| Shared node ACLs | — | (single-owner only) | yes (per-user grants) |
| Priority email support | — | yes | yes |
| Chat support / response SLA | — | best-effort | per-plan |
| Self-hosted (OSS or Docker) | yes (no relation to SaaS tier) | yes | yes |

Each row is a number or a yes/no, not a "feature." Pro never gets a tool Free doesn't have; Pro gets more of what Free has.

## Cost recovery math (rough, internal-use)

These numbers inform pricing; they are not user-visible.

| Cost driver | Free user (typical) | Pro user (typical) | Notes |
|---|---|---|---|
| Storage | ~50 MB | ~5 GB | Mostly cold; SQLite + WAL files |
| Backups | ~1.5 GB / 30 days | ~50 GB / 1 year | Compressed; deduped sparingly |
| MCP requests | ~10 / day | ~10,000 / day | One AI seat is steady; agents in CI burst |
| Web dashboard load | ~5 page views / day | ~50 / day | Cheap |
| Support load | ~0 / month | ~1 ticket / quarter | Drives the pricing floor |

Operating cost per Free user is approximately zero. Operating cost per Pro user is bounded; pricing covers it with margin sufficient to fund ongoing development and the Free tier subsidy.

## Quotas: hard vs soft

- **Hard quotas** refuse new writes when hit. The substrate never deletes existing data to make room (ADR-0005). The user can free space by deleting whole nodes (their choice, with prompt) or upgrade. Hard quotas: per-node entry cap (Free), per-user storage cap (Free).
- **Soft quotas** warn but allow. Used for per-node storage on Pro (5 GB soft); intended to surface the "you might want to talk to us about a higher plan" conversation rather than block a productive user mid-stream. Hard cap kicks in only at a higher threshold (10 GB) on Pro, with sales contact in the meantime.

## Rate limits: hard

Always hard. HTTP 429 with `Retry-After`. The intent is not to throttle reasonable use but to protect the SaaS from runaway agent loops (a single AI seat in an infinite write loop is the load profile we're guarding against).

The defaults are deliberately generous for typical AI-seat use (a single human + their handful of AI seats writes nowhere near 30 entries/minute consistently). Hitting them suggests either: a runaway loop (the user wants to know about that), or a legitimately heavy workload (upgrade time).

## Upgrade / downgrade behavior

- **Free → Pro:** instant. Higher limits apply immediately. No data migration. Billing starts with the next cycle.
- **Pro → Free:** at the next billing boundary. If the user's current usage exceeds Free limits, writes are blocked but data is preserved. The user is shown a self-service path to delete nodes or export-then-delete. After 30 days of overrun without resolution, the account is suspended (no writes, no API access, no data loss) until resolved.
- **Free / Pro → Team:** team owners pay for seats; existing user data unaffected.
- **Account deletion:** see `05_multi_tenancy.md`.

## Anti-features (things we deliberately don't gate)

The following are NOT and never will be paywalled — they belong to every tier and to the OSS package:

- The full MCP tool surface (`06_mcp_surface.md`).
- `list_tags`, `search_text`, `search_by_tag`, `get_thread`, `latest_skill`, all readers.
- `audit_doctor` (self-audit; valuable to free users too).
- Schema profile expressiveness (extras, tag namespaces, soft validators).
- The full `boonyard` CLI.
- Manual export (the no-lock-in mechanism — paywalling this would break the substrate's core promise).
- Documentation, schema migrations, support for migrating in from other NNs.

## Anti-patterns (revenue tricks we won't use)

- **"Open-core" feature drift.** We will not move features from OSS to Pro-only over time. ADR-0006.
- **Vendor-lock-in formats.** SQLite is the format, period. We don't introduce a "Boonyard Cloud Format" that requires our tools to read.
- **Captive aggregator data.** The Umbrella view in Pro is a *compute service* over user-owned files. Cancelling Pro stops the service but does not block the user from running the aggregator on the OSS package over their exported nodes.
- **Coercive 2FA-paywalling.** 2FA is free for every tier. (Charging for security features is a cardinal sin in this product class.)
- **Telemetry by default.** OSS has none. SaaS has only operational metrics. The "Insights" feature, if it ever ships, is opt-in per node.

## Final naming

Working names: **Free**, **Pro**, **Team**. Final naming deferred to a Phase 3 marketing pass. Avoid: "Basic" (implies incomplete), "Premium" (overused), anything implying the free tier is a teaser ("Lite," "Hobbyist"). The free tier is meant to be load-bearing for solo dev work indefinitely; the name should reflect that.

## See also

- ADR-0006 — OSS / SaaS split + the "never paywall an algorithm" rule
- ADR-0007 — multi-tenant storage layout (the layer this enforces quotas against)
- ADR-0008 — MCP routing + auth (rate-limit enforcement points)
- `05_multi_tenancy.md` — user / node / team model
- `roadmap/PHASE_3.md` — when billing actually goes live
