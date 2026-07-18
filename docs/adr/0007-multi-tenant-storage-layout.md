# ADR 0007 — Multi-tenant storage layout: filesystem-per-user, file-per-node

**Status:** Accepted
**Date:** 2026-05-20
**Deciders:** Jacob (Professor), Cowork-Opus
**Supersedes:** —
**Superseded by:** —

## Context

The hosted SaaS at boonyardnn.com needs to store many users' many nodes. ADR-0003 already locks the one-SQLite-file-per-node decision; this ADR fills in the multi-tenant layer that wraps it: where on disk things go, how users are isolated, how backups happen, how exports work, and how the no-lock-in promise is mechanically delivered.

The constraints:

- **Isolation:** A bug in user A's tooling, a corrupt schema profile, or a malicious entry payload from user A must not be able to reach user B's data.
- **Mechanical export:** A user requesting their data gets the SQLite files. That's the whole format. Nothing proprietary. No required tool to read them.
- **Cheap teardown:** A user deleting their account, or one of their nodes, results in `rm` of a known path, not a multi-table cascade.
- **Operational sanity:** Backups, integrity checks, and storage accounting work on the same units the user thinks in.
- **Scale realism:** Should handle Jacob-as-user-zero plus a few dozen Phase-3 users on one droplet without engineering heroics. Need not handle 10⁶ users on day one.

The SaaS layer is allowed external dependencies (ADR-0006); none of the constraints above need anything beyond stdlib + the OS filesystem + SQLite + a basic web framework.

## Decision

### Filesystem layout

```
/data/
    users/
        {user_id}/                     <- one directory per user
            metadata.json              <- email, plan tier, created_at, settings
            api_keys.json              <- per-key (id, hash, scopes, created_at, last_used_at)
            nodes/
                {node_slug}/           <- one directory per node, one node per directory
                    journal.db         <- the SQLite file (ADR-0003)
                    boonyard.toml      <- the schema profile (ADR-0002)
                    backups/
                        journal.db.{ISO8601}.bak
                        ...
            exports/                   <- on-demand export bundles ready for download
                export_{ISO8601}.zip
                ...
        ...
    system/
        users.db                       <- minimal lookup: email -> user_id, billing state
        sessions.db                    <- auth session tokens
```

- `user_id`: opaque UUID, never derived from email or other PII.
- `node_slug`: user-chosen, URL-safe (`[a-z0-9-]+`), unique within the user's namespace. e.g. `planescape`, `jrhood`, `vectorscape-world-1`.
- Backups are SQLite online-API backups (atomic, consistent without quiescing writes) named with their UTC timestamp.
- `exports/` holds user-requested export bundles; these are zip archives containing the node's `journal.db` + `boonyard.toml` + a README pointing at the OSS package; expire after 7 days.

### Isolation by directory permissions

Each `users/{user_id}/` directory is owned by a per-user OS uid (or a per-user POSIX group, depending on deployment model) and has mode `0700`. The web service runs as a single process but performs reads/writes inside `users/{user_id}/` only after authenticating the request to that user_id. Tools that need cross-user access (admin operations) run from a separate admin service with explicit elevation.

This means: even if a code-path bug allows path traversal, the OS-level permissions prevent the bug from materializing into a data leak. Belt + suspenders.

### One node = one directory

`users/{user_id}/nodes/{node_slug}/` is the atom of node-level operations:

- **Backup:** SQLite online backup of `journal.db` into `backups/`, retention per tier.
- **Restore:** swap `journal.db` with a chosen backup (the old `journal.db` becomes a one-off backup automatically).
- **Export:** zip the directory; serve from `exports/`.
- **Import:** user uploads a `.zip` or `.db` + `.toml` pair; we copy into a new `nodes/{slug}/` directory after schema-validation.
- **Delete:** `rm -rf users/{user_id}/nodes/{node_slug}/`. One operation, no cascading row deletes anywhere.

### Account / billing data is separate

The `system/users.db` and `system/sessions.db` files hold only the operational state of the SaaS (email-to-user_id mapping, plan tier, billing references, active session tokens). They never contain entries or any data the user wrote. Compromise of these files leaks user *accounts*, not user *content*.

Billing-provider integration (Stripe, etc.) stores Stripe customer IDs and subscription IDs in `system/users.db`; payment instruments themselves never touch our infrastructure.

### Storage budget per tier

| Tier | Nodes | Storage per node (soft) | Total per user (hard) |
|---|---|---|---|
| Free | 3 | 100 MB | 250 MB |
| Paid | unlimited | 5 GB | per-plan total |
| Self-hosted | n/a | n/a | n/a |

Storage is monitored at the directory level (per-user `du`-equivalent), not per-entry. Soft limits warn; hard limits refuse new INSERTs but never delete existing data (per ADR-0005's no-delete principle — the user keeps everything they wrote, even after going over quota; new writes block until they either upgrade or export-and-delete-a-node themselves).

### Backup policy

| Tier | Per-node backup cadence | Retention |
|---|---|---|
| Free | Daily | 30 days |
| Paid | Daily; on-demand snapshots | 1 year |
| Paid w/ export | Above + on-demand export to user's S3-compatible bucket | indefinite (user-owned) |

Backups are SQLite online-API backups (consistent without quiescing writes). The backup process runs in a separate cron / scheduled task, writes into the node's own `backups/` directory, and prunes old backups according to the retention policy. Backups are themselves never deleted before their retention window expires — the no-delete principle propagates.

### Export path (the no-lock-in mechanism)

Every user can, at any time:

1. From the web dashboard: "Export Node X" → produces `exports/export_{ISO8601}.zip` containing `journal.db` + `boonyard.toml` + a README pointing at the OSS package + a short shell script to verify integrity.
2. From the SaaS REST API: `GET /api/nodes/{slug}/export` returns a fresh export bundle as the response body.
3. From the SaaS REST API: `POST /api/nodes/{slug}/export-to-s3` with the user's bucket credentials runs an offsite copy.

The export is the same file the SaaS itself runs against. There is no proprietary intermediate format. There is nothing in the OSS package the user needs to do anything different.

### Privacy redaction (the privacy escape valve atop ADR-0005)

Per ADR-0005, the substrate doesn't delete entries. The SaaS layer adds one operation on top: **redact**. Replaces the content of a single entry with `[redacted YYYY-MM-DD by user request, original entry preserved at <export id>]` and logs the redaction as a meta entry. The original content is preserved in an offsite backup the user can request access to via a slower out-of-band process; the live node no longer shows the redacted content.

This satisfies privacy requests (including, if applicable, GDPR right-to-erasure for personal data inadvertently logged) without violating the substrate's structural promise — the substrate still has an entry with the same id; the SaaS policy substituted the content.

## Consequences

**Positive:**
- Each user's data is in one directory, fully isolated, exportable with `tar`, deletable with `rm`.
- The substrate proper (the boonyard package) has no concept of multi-tenancy; the multi-tenant layer is the filesystem + the web layer. The package stays simple.
- Backups are file-level and trivial to operate. Restore is a file copy.
- The no-lock-in promise is mechanical: export is literally `zip -r` of the node directory.
- Per-user OS-level permissions add a defense layer beneath the web auth layer.
- Storage accounting is `du`. Quotas are checked against directory sizes, no per-row math.
- Privacy redaction satisfies real-world requirements without breaking the substrate's append-only guarantee.

**Negative:**
- Scaling to millions of nodes per server requires sharding the `/data/users/` tree (e.g. by `users/{first-two-of-uuid}/{user_id}/`). Fine; deferred until volume justifies.
- Backups consume disk; tier quotas account for live data only, with backup storage being our operational cost (factored into pricing).
- SQLite per-node means no cross-node transactional consistency. We never want that; consistency is per-node. Mentioned for completeness.
- Per-user OS uids require either OS-level account creation per signup (heavy) or a single-process model with strict in-process per-request user binding (lighter; chosen). The OS-permission defense becomes per-directory, not per-process. Sufficient for the threat model; revisited if it isn't.

**Neutral:**
- Filesystem paths must be reserved-character-safe. `node_slug` validation ensures.
- Cross-user features (team sharing in paid tier, eventually) require explicit per-team data layout — a future refinement; the team's nodes go under `teams/{team_id}/nodes/...` with per-user access bindings tracked in `system/`. Not Phase 2 work; documented when needed.

## Alternatives considered

### One big SQLite file with `user_id` and `node_id` columns

Same shape as ADR-0003 Option B, scaled to the SaaS. Rejected for the same reasons (no isolation, monotonic growth, footgun query scoping), with the additional SaaS-specific concern that one corruption event affects all users.

### Postgres for the SaaS instead of SQLite

Considered. Rejected because:

- The substrate is *defined* by SQLite — the file *is* the data, with all the export / vendor / portability properties that creates. Switching the SaaS to Postgres means the substrate-in-production diverges from the substrate-in-package, breaking the "same code" promise of ADR-0006.
- Postgres adds operational complexity (a service to run, secrets to manage, backup strategy that's not just `cp`) for benefits (transactional cross-table, MVCC under heavy write contention) we don't need at the scope where one user owns one node and writes are serial.
- A user who wants to migrate from SaaS to self-hosted gets `journal.db` files; if the SaaS used Postgres, the export path requires a converter, and converters are where data corruption happens.

If Phase 3+ ever has a scale problem SQLite genuinely can't solve, the answer is sharding (multiple SQLite files), not switching engines. Even then, the per-node file remains the user-visible unit.

### Object storage (S3) for node files

Rejected. SQLite over network filesystems is well-known to be unreliable. The local filesystem is the right place for a SQLite file. Backups *go to* object storage; live files don't live there.

### A single shared "tag dictionary" table across all nodes

Considered briefly for the SaaS, to support "see every tag every user has ever used." Rejected immediately on privacy grounds — what users tag their entries is their content. No cross-user view of any content data, ever.

## References

- CHARTER.md — "Load-bearing beliefs / No lock-in, ever"
- glossary.md — `node`, `boonyardnn.com`, `vendoring`
- ADR-0003 — DB-per-node decision (the foundation this builds on)
- ADR-0005 — append-only (the redact-vs-delete distinction)
- ADR-0006 — OSS/SaaS split (the "same code" property this preserves)
- ADR-0008 — MCP routing (how URL paths map to this filesystem layout)
- architecture/05_multi_tenancy.md — user / node / team model
- architecture/07_freemium.md — tier quotas and feature line
