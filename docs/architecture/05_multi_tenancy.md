# Architecture 05 — Multi-tenancy (users, nodes, teams, ownership)

The SaaS-layer model that wraps the substrate. Strictly speaking, the OSS package has no concept of multi-tenancy — it operates on whatever node file the caller hands it. The multi-tenant model is the web layer (boonyardnn.com) that maps URLs to per-user node files and enforces access control.

This document defines the entities, the access semantics, and the lifecycle operations.

## Entities

### User

```
user_id     UUID, opaque, generated on signup
slug        URL-safe, user-chosen ('jacoboon'); unique across users
email       primary contact / login identifier
plan        'free' | 'pro' | 'team' (Phase 3)
created_at  signup timestamp
status      'active' | 'suspended' | 'deleted'
```

Users are the unit of:

- Authentication (one identity per login).
- Billing (Phase 3; one Stripe customer per user).
- Storage (each user has their own `users/{user_id}/` directory; ADR-0007).
- Default ownership (every node a user creates is owned by that user).

### Node

```
node_id        UUID, opaque
owner_id       FK to user.user_id (single owner; teams handled below)
slug           URL-safe, unique within the owner's namespace
created_at
storage_path   '/data/users/{owner_id}/nodes/{slug}/'
plan_overrides optional per-node overrides (e.g., higher rate limit)
```

A node is the unit of:

- Storage (one directory: `journal.db` + `boonyard.toml` + `backups/`).
- MCP endpoint (one URL: `mcp.boonyardnn.com/{user_slug}/{node_slug}/sse`).
- API key (per-node keys; one node compromise stays isolated; ADR-0008).
- Access grants (users other than the owner can be granted access — see Teams below).
- Backup, restore, export, delete (all per-node operations; ADR-0007).
- Quotas (free tier caps node count per user and entries per node).

### API key

```
key_id          UUID
hashed_secret   sha256 of the actual key string
scope           'node:{node_id}' | 'aggregator:{node_id1,...}'
label           user-set, displayable
created_at
last_used_at    timestamp; for "you have stale keys" hygiene
rate_limit      optional per-key override
revoked_at      nullable; revoked keys retain the row for audit
```

API keys are the unit of:

- Authentication for MCP and REST API requests.
- Per-key rate limiting.
- Audit (which key did what).
- Revocation (one operation, scoped to one key).

A user has many keys; each key targets exactly one node (or one named set of nodes for an aggregator key).

### Team (Phase 3)

```
team_id        UUID
slug           URL-safe, unique across teams
name           displayable
owner_id       FK to user (the team-billing owner)
plan           'team'
created_at
```

Teams are the unit of:

- Shared node ownership (a node owned by a team is accessible to all team members).
- Team-level billing.
- Cross-user collaboration.

A team has members (user-team links with roles: `owner`, `admin`, `member`). Team-owned nodes live at `/data/teams/{team_id}/nodes/{slug}/` (mirror of the per-user layout). A team member's API keys can target team nodes the same way as their personal nodes.

Teams are a Phase 3 feature; pre-Phase-3 the substrate is solo only.

## Authentication

### Web (dashboard) authentication

- Email + password (with `bcrypt`).
- Optional OAuth providers (GitHub, Google) added per Phase 3.
- Sessions are server-side, stored in `system/sessions.db`. Session cookies are HttpOnly, Secure, SameSite=Lax.
- 2FA (TOTP) optional, recommended for paid accounts.

### API / MCP authentication

- Bearer token (the API key) in the `Authorization` header.
- Per-request: parse the key prefix, look up the hash, check scope against the requested path, check rate limit, allow or deny.
- Failures are HTTP 401 (no key / unknown key) or 403 (key valid but not authorized for this path) or 429 (rate-limited).

## Access control rules

For each request to `mcp.boonyardnn.com/{user_slug}/{node_slug}/...` or the corresponding REST API:

1. Resolve `user_slug` to a `user_id`. 404 if no such user.
2. Resolve `node_slug` within that user to a `node_id`. 404 if no such node (don't leak whether the user exists by returning different error codes).
3. Authenticate the bearer key.
4. Check the key's scope: either `node:{this node_id}` exactly, or `aggregator:[...]` containing this node_id (aggregator paths only).
5. Check the key is not revoked.
6. Check the user is `active`.
7. Check rate limits.
8. Allow or deny.

For aggregator endpoints `mcp.boonyardnn.com/{user_slug}/_aggregate/...`:

1. Resolve `user_slug` to `user_id`. 404 if no such user.
2. Authenticate. The key must have scope `aggregator:...`.
3. For each node in the request's `scope` parameter, verify the key's `aggregator:[...]` list includes that node and the node exists and belongs to `user_id` (or to a team the user is a member of, Phase 3).
4. Check rate limits.
5. Allow or deny.

## Lifecycle: signup → first node → first MCP call

1. **User signs up** with email + password (or OAuth).
   - A `user_id` is generated; a `users/{user_id}/` directory is created (mode 0700).
   - `metadata.json` initialized with email, plan=`free`, created_at.
2. **User picks a `slug`.** Default offer is a derived friendly slug; user can pick anything URL-safe and unique. Stored in users.db.
3. **User clicks "Create node."**
   - User enters a `node_slug` (validated URL-safe and unique within their namespace) and optionally chooses a profile template (PlaneScape-shaped, JRHood-shaped, blank).
   - The SaaS calls `boonyard.init_db('/data/users/{user_id}/nodes/{slug}/journal.db', profile=...)`.
   - The node's UUID is generated and stored in `meta`.
   - The dashboard now shows the new node.
4. **User clicks "Generate API key."**
   - A `bnyk_...` key is generated (raw shown once, hash stored).
   - The user copies it and pastes into their seat's MCP config.
5. **User's seat makes its first MCP call.**
   - Request: `POST mcp.boonyardnn.com/{user_slug}/{node_slug}/sse` with `Authorization: Bearer bnyk_...` and an MCP tool call like `recent`.
   - SaaS auth layer verifies key, opens the node, runs the query, returns the result.

## Quotas and rate limits

### Per-user (cumulative across nodes)

| Tier | Total nodes | Total storage |
|---|---|---|
| Free | 3 | 250 MB |
| Pro | unlimited | 50 GB (soft); per-plan limits |
| Team | per-plan |

### Per-node

| Tier | Entries | Storage | Backup retention |
|---|---|---|---|
| Free | 10,000 | 100 MB | 30 days |
| Pro | unlimited | 5 GB (soft per node) | 1 year |

### Per-key (rate limits)

Per ADR-0008. Defaults from there:

| Tier | Writes/min | Reads/min | Burst |
|---|---|---|---|
| Free | 30 | 600 | 10x |
| Pro | 600 | 6000 | 10x |

### Hitting a quota

- Soft-cap on storage: warning displayed in dashboard; user prompted to upgrade or delete a node.
- Hard-cap on entries: writes are rejected with HTTP 429 and an MCP-shaped error. **Existing entries are never deleted.** User can export and delete a node to free quota; existing data is preserved in the export.
- Rate limit hit: HTTP 429 with `Retry-After` header.

## Sharing (Phase 3 — Teams)

A user can grant another user access to one of their nodes:

```
POST /api/v1/nodes/{slug}/grants
{ "grantee_user_slug": "alice", "access": "read" | "write" | "admin" }
```

Grants are recorded in `system/users.db` as `node_grants(node_id, user_id, access_level, granted_at, granted_by)`.

A node can also be transferred to a Team, after which all team members have access per their team role.

Team-owned nodes appear under `mcp.boonyardnn.com/{team_slug}/{node_slug}/sse` (the URL prefix becomes the team slug, with a `~/` prefix to distinguish from user slugs that could collide). The aggregator endpoint can include team-owned nodes in scope as long as the requesting user is a team member with read access.

## Audit

Operations that affect access (key creation, key revocation, grant added, grant removed, plan change) are logged in `system/audit.db` for compliance:

```
audit
    id, timestamp, actor_user_id, action, target_type, target_id, payload
```

The audit log is per-user-readable in the dashboard ("recent activity on your account").

Operations that affect *node content* (entries written, retags) are logged in the node's own `meta_log` (per ADR-0005). The substrate's own audit trail is *inside* the substrate, where it belongs.

## Account deletion

A user can delete their account from the dashboard:

1. Confirm via password + email link.
2. All nodes export bundles are pre-generated and offered for download (7-day retention).
3. After a 7-day grace period (account marked `status='deleted'`, no logins, no API access): all node files are moved to `/data/.tombstoned/{user_id}/{deletion_timestamp}/` and the user's primary directory is deleted.
4. After 30 days total: the tombstoned files are removed.
5. The user_id remains in users.db with `status='deleted'` to prevent slug reuse and to support audit queries; PII (email) is scrubbed at the 30-day mark.

Account deletion is the *only* path that removes user data. Per-node deletion (via the dashboard) deletes that node's directory immediately (with a grace-period prompt). Per-entry deletion does not exist (ADR-0005); the privacy-redact path exists for individual entries as a content-substitution operation.

## Privacy and content policy

- The SaaS never reads entry content for analytics, model training, or any non-operational purpose.
- The SaaS may scan entry content for *operational* purposes (e.g., detecting clear abuse — known-malicious payloads, attempts to use the substrate as malware C2). Such scans are described in the published Acceptable Use Policy and produce only operational alerts, never tagging or content surfaces.
- The SaaS supports per-entry privacy redaction (ADR-0007): content replaced with `[redacted YYYY-MM-DD by user request]` while preserving the entry id and metadata. Redaction is logged in `meta_log` per ADR-0005 exception conventions.
- The SaaS does not respond to third-party requests for user data without lawful process; a published transparency-style summary describes the practices.

## OSS vs SaaS: what multi-tenancy means here

The OSS package has no users, no auth, no rate limits — those are the SaaS layer's job. An OSS user running the package on their laptop is a single-tenant deployment: they are the only user; their nodes belong to nobody but them; there are no quotas.

The Docker self-host deployment may add a thin auth wrapper (basic auth, or a single shared bearer key) for users who want hosted-style ergonomics without using the SaaS — but it doesn't try to implement full multi-tenancy. Full multi-tenancy is the SaaS's value proposition; users who want it should use the SaaS or accept the responsibility of building their own multi-tenant wrapper.

## See also

- ADR-0006 — OSS / SaaS split
- ADR-0007 — multi-tenant storage layout (the filesystem layer this maps onto)
- ADR-0008 — MCP routing (the URL layer)
- `07_freemium.md` — the tier feature matrix in full
- `04_distribution.md` — how this sits in the larger distribution picture
