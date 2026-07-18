# Phase 2 — SaaS MVP for User Zero

> boonyardnn.com goes live. Jacob signs up on it like any future user would. The SaaS-hosted version of his existing PlaneScape / JRHood nodes runs alongside (or replaces) the self-hosted ones. The MVP serves exactly one user, but it does so end-to-end with the actual production code path that other users will eventually hit.

## Goal

Prove the SaaS deployment shape works by running it for user zero (Jacob) only. Sign up, spawn a node, get an MCP URL, point a seat at it, watch entries flow. Multi-tenant code exists but is exercised by exactly one tenant. No billing yet (free for user zero forever; billing is Phase 3).

## Why user-zero-only

Per CHARTER ("dogfood pact") and ADR-0006 ("the OSS package is the SaaS"): the SaaS isn't a different product, it's a different deployment of the same package. Phase 2 validates the deployment shape end-to-end without the additional complexity of multiple users, billing, or support load. If the SaaS works well for one user (Jacob), opening to more is a matter of capacity planning + billing wiring; if it doesn't work well for one user, opening to more is malpractice.

## Deliverables

### 1. The SaaS web layer exists

A Flask (or equivalent, decided at Phase 2 kickoff) application that runs on a DigitalOcean droplet (same shape as JRHood's existing deployment). It is the multi-tenant layer described in `architecture/05_multi_tenancy.md`, sitting on top of the boonyard package described in `architecture/04_distribution.md`.

Structure:

```
boonyardnn.com/
    deploy/                  # systemd / nginx config, deploy scripts (paramiko-based, like JRHood's)
    server/
        app.py               # Flask app entry
        auth.py              # session management, password hashing, OAuth (Phase 3)
        nodes.py             # node CRUD endpoints (REST API)
        mcp_router.py        # MCP path-routing layer (per-node URLs, aggregator URL)
        dashboard/           # Flask blueprint for the web UI
            templates/
            static/
        models.py            # SQLAlchemy-or-similar for users, nodes, api_keys, sessions
                             # (the SaaS may use ORM since ADR-0001 applies only to the package)
        boonyard_adapter.py  # the thin layer between Flask and boonyard.* calls
    requirements.txt         # Flask, gunicorn, bcrypt, etc. (SaaS-side deps; ADR-0006)
    tests/
```

Operates against the same `boonyard` package from Phase 1 — `import boonyard` and call the same functions.

### 2. The web dashboard exists (minimal)

UI sections (all server-rendered HTML; no SPA in Phase 2):

- **Login / signup.**
- **My nodes list.** One row per node: name, entry count, last write time, "manage" link.
- **Per-node view.** Recent entries (paginated). Search box (tags + FTS). Tag tree. API key management.
- **API keys.** List of keys per node, with labels, last-used timestamps, "revoke" button. Generate new key (raw key shown once).
- **Settings.** Email, password change, plan (`free` for now), account deletion.

Style: spartan and functional. No marketing chrome. JRHood's dashboard is the reference for visual register.

### 3. Multi-tenant storage on disk

Per `architecture/05_multi_tenancy.md` and `ADR-0007`:

```
/data/users/{user_id}/
    metadata.json
    api_keys.json
    nodes/
        {node_slug}/
            journal.db
            boonyard.toml
            backups/
    exports/
```

Per-user OS-level permissions (mode 0700 on the user directory).

### 4. Auth — email + password, session-based

- Signup: email + password. bcrypt the password. Send a verification email (Phase 2 uses a simple SMTP send — same SendGrid setup as JRHood's `_send_claim_email`).
- Login: email + password → session cookie.
- API/MCP auth: per-node bearer tokens (ADR-0008). Generate via dashboard; copy once; store hashed.

OAuth providers (GitHub, Google) deferred to Phase 3.

### 5. Per-node MCP endpoints work

`https://mcp.boonyardnn.com/{user_slug}/{node_slug}/sse`

For Jacob:
- `mcp.boonyardnn.com/jacoboon/planescape/sse`
- `mcp.boonyardnn.com/jacoboon/jrhood/sse`
- `mcp.boonyardnn.com/jacoboon/spore/sse` (when Spore migrates in)

Routing: parse user_slug + node_slug → resolve to user_id + node_id → authenticate bearer key → open node DB → run MCP tool → return.

Aggregator endpoint `mcp.boonyardnn.com/jacoboon/_aggregate/sse` works with an aggregator key listing the user's nodes.

### 6. Backups + exports actually run

- Nightly cron (systemd timer) runs SQLite online backup on each node into `nodes/{slug}/backups/`.
- 30-day retention (Free tier; ADR-0007).
- On-demand export from dashboard produces a zip; 7-day retention.

These run for user zero and are observed for a month to confirm they don't grow unbounded, don't corrupt, and the restore path actually works (test-restore exercise once per quarter).

### 7. Migration: user zero brings their nodes in

Jacob's existing nodes (post-Phase-1) are self-hosted on his machine. Phase 2 supports two paths:

- **Option A (canonical):** Jacob uses the dashboard's "Import node" feature, uploads a `.zip` export bundle. The SaaS creates a new node at `users/{jacob}/nodes/{slug}/` with the uploaded `.db` + `.toml`.
- **Option B (parallel):** Jacob's self-hosted nodes continue to run. He creates *new* SaaS nodes for testing and incrementally moves seats over node by node. After comfort builds, the self-hosted ones can be retired.

Recommendation: Option B for the first month. Validate the SaaS for one node (e.g., a fresh `boonyard-test` node Jacob creates from scratch); then migrate PlaneScape; then JRHood. Self-hosted nodes stay live as fallbacks for the full Phase 2 period.

### 8. The cloudflared tunnel pattern

`nn.vectorscape.uk` (the existing PlaneScape NN URL) and `mcp.boonyardnn.com` are both exposed via Cloudflare tunnels (cloudflared) — the same pattern PlaneScape's NN already uses. This avoids needing to open ports on the droplet directly and gives free DDoS protection.

After Phase 2, if Jacob wants `nn.vectorscape.uk/sse` to route to the SaaS-hosted PlaneScape node, that's a Cloudflare config change (CNAME or transform rule); the OSS hosted version remains an alternative.

### 9. Operational tooling

Phase 2 deploys minimum operational visibility:

- **Logs:** structured stdout from Flask → systemd journal → rotated.
- **Health endpoint:** `GET /health` returns 200 OK plus version + uptime.
- **Metrics:** per-route latency, error rate, total writes per minute. Self-hosted Grafana dashboard or just stdout summaries — pick the lighter-weight option for Phase 2.
- **Backup verification:** weekly automated restore-and-verify of a randomly-chosen node into a scratch directory; report success / failure to Jacob.

### 10. Documentation for "future users" (drafted, not yet public)

`boonyardnn.com/docs/` (or a `/docs` subdir of the landing page) — Phase 2 drafts the user-facing docs, marked DRAFT until Phase 3:

- Getting started (signup → spawn node → first MCP call).
- The schema profile (how to customize for your project).
- The CLI (with `--remote` for talking to the SaaS).
- The MCP tools (mirroring `06_mcp_surface.md` in user-readable form).
- Migration from existing NNs.
- Self-hosting alternative.

These docs aren't linked from the landing page until Phase 3; they exist so Jacob can review for "would this be enough for another user to figure it out?"

### 11. Phase 2 marker entry

```
agent: code or jacob
entry_type: implementation
tags: implementation,boonyard,phase-2,milestone,saas
content: BoonyardNN Phase 2 complete. boonyardnn.com is live. User zero (Jacob) is signed up. Nodes: planescape, jrhood [and others as migrated]. MCP endpoints reachable at mcp.boonyardnn.com/jacoboon/{node}/sse. Aggregator at .../_aggregate/sse. <N> days of soak time with zero data loss, all backups verified. Phase 3 (public + billing) is gated on Jacob's review of operational evidence.
```

## Acceptance criteria

Phase 2 is complete when:

1. `boonyardnn.com` resolves to a logged-in dashboard for Jacob, with full per-node management.
2. `mcp.boonyardnn.com/jacoboon/{node}/sse` works for at least one node, returning correct results for `recent`, `log_entry`, and one each of the other tools from `architecture/06_mcp_surface.md`.
3. The aggregator endpoint works across at least two of Jacob's nodes.
4. Nightly backups have run successfully for ≥7 consecutive days; ≥1 successful restore-and-verify has been performed.
5. Jacob has used the SaaS-hosted node from at least one of his seats for ≥1 week with no production incidents.
6. The "self-hosted vs SaaS" decision is *equivalent* in feature surface (everything Jacob can do self-hosted also works against the SaaS-hosted node).
7. The Phase 2 marker entry is logged.

## What Phase 2 does NOT include

- **No public signups.** Signup is gated to Jacob's email only (or a small allowlist if Jacob wants to invite a trusted second seat for testing). Phase 3 opens this.
- **No billing.** Stripe integration is Phase 3. The plan column exists; everyone is `free`.
- **No team / shared nodes.** Single-owner only. Teams are Phase 3.
- **No webhooks.** Phase 3.5+.
- **No marketing.** The landing page from Phase 0 stays the same except for an updated "Status" section reflecting Phase 2 progress.

## Risks

- **Operational complexity vs Phase 1 self-hosted simplicity.** A SaaS is more operational surface than running the package locally. Mitigation: tight scope; "user zero only" means we never have to handle "another user's emergency" during Phase 2.
- **The Flask layer drifts ahead of the package.** Mitigation: enforce the "boonyard_adapter.py is the only file that touches `boonyard.*` calls" rule. Web layer talks to the package via that adapter; no scattered `import boonyard` calls.
- **Backup / restore corner cases.** Mitigation: weekly verification builds confidence; restore drills.
- **Auth + key management UX confusion.** Mitigation: copy the patterns Jacob already understands from JRHood; clear docs in the dashboard.
- **Scope creep into Phase 3 features.** Mitigation: anything related to "more than one user" is a Phase 3 ticket, not a Phase 2 ticket.

## Estimated effort

The Flask layer is the bulk; the package work is already done in Phase 1. Realistic: 3–5 focused sessions for the web layer + dashboard, 1–2 sessions for the auth + key flow, 1 session for ops tooling (backups, health checks). Then a month of soak time. Total wall-clock: ~6–8 weeks from Phase 1 close.

## Then what

When Phase 2 is complete and operational evidence is solid for ≥1 month: Phase 3 — open to the public + add billing.

If Phase 2's operational evidence reveals fundamental SaaS-shape issues: pause; reassess whether the SaaS layer should be simpler (e.g., drop the dashboard for now, keep just MCP + key API), or whether the substrate's positioning should lean more toward "self-host only" with the SaaS as an afterthought.
