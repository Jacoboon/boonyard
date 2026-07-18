# ADR 0008 — MCP routing and authentication: per-node endpoints, per-node API keys, scope-aware aggregation

**Status:** Accepted
**Date:** 2026-05-20
**Deciders:** Jacob (Professor), Cowork-Opus
**Supersedes:** —
**Superseded by:** —

## Context

The substrate's primary access path for AI agents is the Model Context Protocol (MCP). The live PlaneScape NN already exposes one node at `nn.vectorscape.uk/sse` (shipped in entry 77). For BoonyardNN, every node in every deployment mode needs an MCP surface, and the multi-tenant SaaS specifically needs:

- A URL shape that identifies which node an MCP call is targeting.
- An authentication mechanism that ties calls to a user and that user's allowed nodes.
- A scope mechanism that lets aggregator queries hit multiple nodes via one endpoint.
- Rate limits at the per-key, per-node, and per-tier levels.
- A single tool surface (same tools, same signatures) regardless of OSS-vs-SaaS deployment.

The OSS deployment also needs an MCP server, but its concerns are different: no auth needed (it's running on the user's machine), one node at a time is the common case, scope param exists but the user is the only "tenant."

This ADR defines the URL shape, the auth model, and the routing semantics. The actual tool definitions live in `architecture/06_mcp_surface.md`.

## Decision

### Tool surface is identical across OSS and SaaS

Every MCP server (single-tenant OSS, multi-tenant SaaS, embedded in-project) exposes the same tool set:

- `log_entry(agent, entry_type, content, related_id?, tags?, extras?)`
- `recent(limit?, agent?, entry_type?, scope?)`
- `by_id(entry_id, scope?)`
- `search_by_tag(tag, limit?, scope?)`
- `search_text(text, limit?, scope?)`
- `get_thread(root_id, scope?)`
- `list_tags(prefix?, tree?, scope?)`
- `list_agents(scope?)`
- `list_entry_types(scope?)`
- `list_skills(limit?, scope?)`
- `latest_skill(slug, scope?)`
- `log_skill_revision(slug, content, ...)` (convenience over log_entry that handles root-anchoring)
- `list_nodes()` (in scope-capable deployments)

Tools take an optional `scope` parameter (see ADR-0003). In single-node deployments, omitting `scope` reads/writes the only node. In multi-node deployments, omitting `scope` defaults to the user's "current" node, declared per API key.

`log_entry` and `log_skill_revision` always target exactly one node (writes); `scope` is interpreted as "which node to write to" when given, otherwise the key's default node.

All other tools accept `scope` as either:
- omitted / `'current'`: the key's default node
- a string: one named node
- a list of strings: those named nodes
- `'all'`: every node the key has read access to

### URL shape

**OSS (single-tenant, local):**

```
http://localhost:8765/sse                      <- single-node default
http://localhost:8765/{node_slug}/sse          <- multi-node aggregator
```

The OSS MCP server can serve multiple node files at once (from a config that lists them). No auth — it's localhost, the user is the only actor.

**SaaS (multi-tenant, hosted at boonyardnn.com):**

```
https://mcp.boonyardnn.com/{user_slug}/{node_slug}/sse
```

- `user_slug` is the user's chosen URL slug (defaults to a UUID prefix; can be customized to e.g. `jacoboon` if available).
- `node_slug` is the node's slug under that user.

A second endpoint pattern for the aggregator (paid tier only):

```
https://mcp.boonyardnn.com/{user_slug}/_aggregate/sse
```

The `_aggregate` endpoint accepts the `scope` parameter on every tool call and routes against multiple node files of the user. `_aggregate` always uses query-only mode for reads (writes targeted via this endpoint are rejected; writes must address a specific node).

### Authentication: per-node API keys, bearer auth

The SaaS issues API keys *per node*, not per user. The reasons:

- An API key compromise leaks one node, not everything.
- A user can give one seat one node's key without granting cross-node access.
- Revoking a single key disables only the affected node.
- The aggregator endpoint requires a separate "aggregator key" that the user explicitly creates and that lists the nodes it can read; this makes the cross-node access a deliberate decision, not an automatic side effect of having any key.

Keys are presented in MCP requests as a bearer token:

```
Authorization: Bearer bnyk_<32-char-base32>
```

Keys are:

- Generated with `secrets.token_hex(32)` (stdlib).
- Stored as `sha256` hashes; the raw key is shown to the user exactly once at creation.
- Prefixed `bnyk_` so they're recognizable in logs and config files.
- Scoped to one node (or, for aggregator keys, a named list of nodes) at creation; the scope can't be widened later (only revoked-and-reissued).
- Optionally given a label (e.g. "Code seat key", "Cowork seat key") for the user's tracking.
- Optionally rate-limit-overridden (paid feature).

### Rate limits

| Tier | Per-key write rate | Per-key read rate | Burst |
|---|---|---|---|
| Free | 30 / minute | 600 / minute | 10x |
| Paid (Pro) | 600 / minute | 6000 / minute | 10x |
| Self-hosted | n/a | n/a | n/a |

Rate-limit responses are HTTP 429 with a `Retry-After` header and an MCP-shaped error body. The free-tier limits exist primarily to protect the SaaS from runaway agent loops, not to throttle reasonable use.

### Read-only mode

The aggregator endpoint (`{user_slug}/_aggregate/sse`) refuses all write tools. Specifically, `log_entry` and `log_skill_revision` return MCP errors of shape:

```
{"error": "aggregator endpoint is read-only; address a specific node to write"}
```

This is enforced at the routing layer, not just convention. The aggregator's connection to each underlying node DB is opened with `PRAGMA query_only=ON`.

### CLI parity

The `boonyard` CLI accepts the same auth model when talking to a remote SaaS endpoint:

```bash
boonyard --remote https://mcp.boonyardnn.com/jacoboon/planescape \
         --key   bnyk_xxxxxxxx \
         recent 20
```

Keys can be stored in `~/.config/boonyard/credentials.toml`:

```toml
[default]
endpoint = "https://mcp.boonyardnn.com/jacoboon/planescape"
key      = "bnyk_xxxxxxxx"

[aggregator]
endpoint = "https://mcp.boonyardnn.com/jacoboon/_aggregate"
key      = "bnyk_yyyyyyyy"
```

```bash
boonyard recent 20              # uses [default]
boonyard --profile aggregator find "FUSE boot ritual"
```

### MCP SSE vs HTTP

The MCP protocol supports both SSE (Server-Sent Events for streaming) and stateless HTTP. The substrate's tools are all small request/response and don't benefit from streaming, but the SSE path is what the AI seats expect today. Both transports are exposed:

```
https://mcp.boonyardnn.com/{user_slug}/{node_slug}/sse    <- SSE (streaming)
https://mcp.boonyardnn.com/{user_slug}/{node_slug}/http   <- stateless HTTP
```

Same auth, same tool surface, same semantics. SSE is the recommended default.

## Consequences

**Positive:**
- URL shape is human-readable and reveals what's happening (`/jacoboon/planescape/sse` is obviously Jacob's PlaneScape node).
- Per-node keys map the security boundary to the storage boundary (a key compromise = one node, isolated by both auth and filesystem permissions per ADR-0007).
- Aggregator keys are deliberate and read-only — cross-node access is an opt-in, not a side effect.
- Same tools everywhere means a seat works against any deployment without code changes; only the endpoint and key change.
- Rate limits at the key level give us a unit to throttle, monitor, and report on.
- The OSS path remains simple (no auth needed locally) while the SaaS gets the security it needs.

**Negative:**
- Users have to manage multiple keys (one per node), or accept the convenience of an aggregator key with broader read access. The dashboard makes key management easy; for power users, the per-node keys are the right default.
- URL slugs need to be reserved-character-safe and unique per user. The signup flow validates this.
- The aggregator endpoint adds complexity to the routing layer. Acceptable; aggregation is one of the substrate's load-bearing capabilities (over-many mode) and deserves first-class support.

**Neutral:**
- MCP's evolving protocol may require updates to the tool definitions over time. Tool surface and routing are decoupled, so protocol changes are localized.
- Webhook support (push notifications on entry write) is a future earned feature, deliberately deferred.

## Alternatives considered

### Single user-level API key, scope param picks the node

Each user has one key; every MCP call includes the node_slug in the scope param.

**Why rejected:** Maps the security boundary to the wrong unit. A compromised key gives access to everything. Revoking the key disables all seats. The per-node-key model is operationally a tiny extra burden and security-wise a substantial win.

### Path-less endpoint, node selected by HTTP header

`https://mcp.boonyardnn.com/sse` with `X-Boonyard-Node: jacoboon/planescape`.

**Why rejected:** Worse UX (the URL no longer reveals what it does). MCP clients vary in their support for arbitrary headers. Path-based routing is the standard pattern and works everywhere.

### OAuth instead of bearer tokens

Full OAuth flow for SaaS auth.

**Why rejected:** Overkill for the seat-to-substrate access pattern, which is single-actor and machine-driven. OAuth shines for delegated user-to-third-party flows. For AI seats reading and writing their own user's data, a simple per-key bearer is the right shape. (OAuth may be added later for *web dashboard* sign-in via Google/GitHub, but not for the MCP layer.)

### Open MCP endpoints, IP allow-list for auth

Considered for the simplest possible model.

**Why rejected:** IP allow-lists are operationally painful (changing IPs, dynamic IPs from agent hosts, etc.) and only marginally easier than bearer tokens. Bearer tokens are the standard.

## References

- CHARTER.md — "Load-bearing beliefs / No lock-in"
- glossary.md — `MCP`, `MCP doorway`, `node`, `scope`
- ADR-0003 — DB-per-node + aggregator (the scope mechanic this exposes)
- ADR-0006 — OSS / SaaS split (this ADR keeps tools identical across)
- ADR-0007 — multi-tenant storage layout (filesystem paths this URL shape mirrors)
- architecture/06_mcp_surface.md — full MCP tool definitions
- architecture/05_multi_tenancy.md — user / node ownership model
