# Phase 3 — Public Open + Billing + Teams

> The SaaS opens to the public. Stripe handles billing. Teams arrive. BoonyardNN goes from "Jacob's substrate" to "a product anyone can use."

## Goal

Open `boonyardnn.com` to public signups. Wire up Stripe billing for the Pro tier. Add Team functionality for shared nodes. Continue dogfooding (user zero is still the primary user; the substrate's value to Jacob is still the lead metric), but now with other users as an additional reality check.

## Gating condition

Phase 3 only proceeds if Phase 2 produced clear evidence that the substrate compounds value for user zero in the SaaS shape, not just in the self-hosted shape. The acceptance criterion is roughly: *Jacob, asked "is the SaaS-hosted BoonyardNN making your work materially better than self-hosted alone?" answers yes with specifics.* If the answer is "they're equivalent," Phase 3 is premature; consider Phase 2.5 (additional SaaS feature work that justifies the hosted convenience tax) first.

## Deliverables

### 1. Public signups enabled

Remove the allowlist gate from signup. Anyone with an email can create an account. Free tier limits (ADR-0007, `architecture/07_freemium.md`) enforced from the first user onward.

Signup flow improvements over Phase 2:

- Email verification (deliverable by Phase 2; required by Phase 3).
- OAuth providers: GitHub, Google (added now; Phase 2 had only email/password).
- CAPTCHA on signup endpoint (to keep bot signups at bay).
- Per-IP rate limiting on signup (to keep abuse at bay).

### 2. Billing (Stripe)

- Stripe Customer per user_id.
- Stripe Subscription for users on Pro tier.
- Webhook endpoint receives subscription events (`invoice.paid`, `customer.subscription.deleted`, etc.) and updates the local `users.plan` accordingly.
- Dashboard "Billing" page: current plan, upgrade button (Stripe Checkout), invoice history, payment method management (via Stripe Customer Portal).
- Failed-payment handling: 7-day grace period (account flagged but writes still allowed), then downgrade to Free; if Free limits exceeded, writes blocked but data preserved (no deletion, per ADR-0005).
- Refund / proration policy: pro-rata refunds for mid-cycle downgrades. Documented in the Terms of Service.

### 3. Teams

- Create team: `POST /teams` with name + slug.
- Add member: invite by email. Recipient accepts; user-team link is created with role (`owner`, `admin`, `member`).
- Team-owned nodes: nodes can be transferred from user-owned to team-owned. Once team-owned, all team members with sufficient role can access; the URL prefix changes from `/{user_slug}/...` to `/~{team_slug}/...` (the `~` distinguishes teams; we don't want a team slug to collide with a user slug).
- Per-node access grants within a team (read / write / admin): persisted in `system/node_grants` table.
- Aggregator across team-owned nodes works for team members.
- Team billing: Stripe Subscription on the team_id; per-seat pricing.

### 4. Dashboard improvements

- **Cross-node search.** With the aggregator working, the dashboard's search box can span all of the user's nodes (Pro feature).
- **Activity feed.** Recent writes across all nodes, sorted timestamp-desc, grouped by node (Pro feature; Free shows single-node feed).
- **Tag explorer.** Visual tree of `list_tags(tree=True)` for one node or aggregated.
- **Skill catalog page.** Per-node skill list with WHEN excerpts; one-click "show all revisions" for any skill.
- **Settings page improvements:** API key labels with last-used-at; bulk-revoke; 2FA enrollment.

### 5. Documentation public + polished

The Phase 2 drafted docs go live at `boonyardnn.com/docs/`:

- Getting started (free signup → first node → first MCP call) — under 5 minutes from zero.
- Conceptual docs (one page each for: the substrate, the three modes, schema profiles, tag namespaces, skills).
- Migration guides (from PlaneScape-style NN, from JRHood-style NN, from generic event log).
- Self-hosting guides (pip install, vendor, Docker).
- API reference (auto-generated from `architecture/06_mcp_surface.md`).
- Tier feature matrix (`architecture/07_freemium.md` made user-friendly).
- FAQ.

### 6. Marketing pass

The landing page from Phase 0 is iterated:

- Honest pitch refined.
- Three modes illustrated with concrete examples (PlaneScape, JRHood, Vectorscape).
- Code samples (vendoring, `pip install`, first `log_entry`).
- "Why no embeddings (yet)" callout (links to ADR-0010 — be transparent about positioning).
- Pricing page (free / pro / team).
- Comparison page vs. other agent-memory products — honest, technical, not adversarial.
- Newsletter list activated (the emails collected in Phase 0 get a "we're open" announcement).
- A brief launch post on relevant communities (HN's Show HN, the Anthropic Discord, etc.) — with explicit framing that this is user-zero-validated, not Series-A-funded, and the substrate's positioning is "small, durable, owned," not "feature-rich cutting-edge."

### 7. Support infrastructure

- Help email: `support@boonyardnn.com`.
- Knowledge base: docs + a FAQ + common-issue articles.
- Status page: `status.boonyardnn.com` shows real-time uptime (custom or a third-party like UptimeRobot).
- Operations runbook: documented in `boonyardnn-private/runbooks/` (private repo for ops); covers common incidents (storage full, backup failure, MCP server crash, abuse-pattern detection).

### 8. Webhooks (Phase 3.5 if scope-trims)

Per-node webhook configuration: "when an entry of type X is written, POST to URL Y."

Optional for Phase 3; if scope balloons, defer to Phase 3.5.

### 9. The Umbrella application (separate project consuming the substrate)

The Umbrella vision (live NN entry 75) — a meta-cognitive layer reading across Jacob's project NNs to surface cross-project patterns — is **not** a BoonyardNN feature. It is a separate project that uses BoonyardNN's aggregator endpoint as its data source.

In Phase 3, Jacob's Umbrella project (built in `C:\Users\Jacob\Code\Umbrella\`) consumes `mcp.boonyardnn.com/jacoboon/_aggregate/sse` and produces its own outputs (weekly digest, cross-project anomaly detection, etc.). This is itself dogfood evidence: the Phase 3 SaaS supports a third-party consumer pattern that other users might also build atop.

### 10. Phase 3 marker entry

```
agent: jacob
entry_type: implementation
tags: implementation,boonyard,phase-3,milestone,public-launch,billing
content: BoonyardNN Phase 3 complete. boonyardnn.com open to public signups. Stripe billing live. Teams supported. <N> users signed up; <M> on Pro. Dogfood evidence: user zero (Jacob) is still using the substrate heavily across <list of projects>; Umbrella consumes the aggregator endpoint successfully. No data-loss incidents. Substrate has earned its keep across the dogfood pact period. Considering Phase 4 (community features, marketplace, etc.) — not committed.
```

## Acceptance criteria

Phase 3 is complete when:

1. Public signup works end-to-end (CAPTCHA, email verification, OAuth providers).
2. Stripe billing works for at least one paid user (Jacob upgrades to Pro himself; or a beta user volunteers).
3. Teams support is verifiable — two test users (Jacob + an invited account) can share a node and both write to it with attribution.
4. The documentation site is live and complete enough that a new user can sign up, spawn a node, and make their first MCP call without help.
5. The Umbrella project (or another consumer of the aggregator) is running successfully.
6. No data-loss incidents; backup verification has continued; status page is green.
7. The Phase 3 marker entry is logged.

## What Phase 3 does NOT include

- **No enterprise SSO** (SAML / SCIM). If demand surfaces, Phase 4.
- **No on-prem deployment offering** (other than the OSS self-host path which has always existed). If a paying customer demands a managed-on-prem deployment, that's a custom engagement, not a product feature.
- **No advanced search features** (semantic / vector). ADR-0010 still governs; if added, optional install.
- **No "Insights" / cross-content analytics.** The substrate doesn't read content for analytics (ADR-0006); Insights, if ever built, is a Phase 4+ feature with explicit per-node opt-in.
- **No agent-detector / auto-tagging** built into the substrate. Per ADR-0004's "v1 is prompted, not autonomous" framing; auto-skill-detection is a deferred earned phase.

## Risks

- **Support load.** First public users will have questions. Mitigation: write good docs; budget time for support; if a user is consuming disproportionate support, communicate honestly.
- **Abuse / spam signups.** Mitigation: CAPTCHA, rate limits, abuse-pattern detection. Be willing to suspend accounts.
- **Billing edge cases.** Stripe handles 99% but local plan-state-sync edge cases happen. Mitigation: idempotent webhook handler; reconciliation job nightly.
- **Public attention triggers Project-Six trap.** If launch creates a "now I have to keep adding features" treadmill that displaces Jacob's primary projects, course-correct. CHARTER's dogfood pact is still in force; revenue and traffic do not override it. If the substrate becomes a job that eats Jacob's calendar instead of compounding his other work, *scale down to maintenance mode*, not up to "venture pace."
- **Competitive responses from other agent-infra players.** Honest positioning (small, owned, durable, no telemetry, no lock-in) is itself the defense; we don't try to out-feature competitors who have different positioning.

## Estimated effort

Substantial. The Stripe integration is well-trodden but real work. The team-sharing model is non-trivial. The dashboard polish for Pro is meaningful work. Marketing pass takes its own time. Realistic: 8–12 focused work sessions plus the launch lead-up.

## Then what

When Phase 3 is complete:

- The substrate has crossed from "Jacob's tool" to "a public product."
- Future work is driven by user feedback (channeled through `decision` entries in the canon — every roadmap change is a logged decision), Jacob's own evolving needs as user zero, and the explicit CHARTER + ADR constraints. There is no "Phase 4" defined in advance because the right next move depends on what the substrate's actual users tell us.
- Candidate Phase 4 directions, none committed: webhooks (Phase 3.5 if not done), team marketplace for shared schema profiles, optional embeddings install, enterprise SSO, hosted Umbrella as a product, integration packs (Slack / Discord / Notion as MCP-on-top consumers).

The substrate, by design, is meant to be stable for years. The CHARTER says so. Phase 4 and beyond should add *less* per phase than Phase 1–3 did, not more. The substrate is small on purpose, and the purpose is for it to stay small.
