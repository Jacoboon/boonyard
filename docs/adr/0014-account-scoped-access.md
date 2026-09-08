# ADR 0014 — Account-scoped access: one endpoint, every node

**Status:** ACCEPTED 2026-09-07 — Professor: *"All recs - approved."* (umbrella #397). All four decisions below carry their recommendation: take it · the account endpoint is the default door in docs and dashboard, per-node documented as the sharing tool · rate limits per account for account keys · **build it BEFORE the wall migration**, prove it on throwaway nodes, then migrate the six walls onto it. **Extends ADR-0008; does not supersede it.** Per-node endpoints and per-node keys remain first-class and unchanged.
**Date:** 2026-09-07
**Deciders:** Jacob (Professor); drafted by the Conductor (Cowork, model:claude-opus-5) from his proposal at umbrella #394
**Supersedes:** —
**Superseded by:** —

## Context

Professor, verbatim (umbrella #394): *"Asking people to configure a new connector for each node is silly… Connect the 'Boonyard NN' connector. It auths to their boonyard.com account and shows the available nodes. Each call, both read and write, have to specify which node. So — my BoonyardNN connector that I setup with my auth keys will serve 100 NNs if that's what I have in my account."*

Today a user with N nodes configures N connectors. That is an artifact of how the substrate grew — one wall at a time, each with its own tunnel and its own key — not a decision anyone made on a user's behalf. It scales badly in the exact place a memory product wants to grow: a person whose second, third and tenth node are the whole point of the thing.

**Half of this is already canon and the other half is already forbidden, in the same document.** ADR-0008 at the tool level: *"`log_entry` and `log_skill_revision` always target exactly one node (writes); `scope` is interpreted as 'which node to write to' when given, otherwise the key's default node."* Every one of the twenty tools already carries `scope`. ADR-0008 at the endpoint level: the `_aggregate` endpoint *"refuses all write tools"*, enforced with `PRAGMA query_only = ON` at every connection.

Three facts measured in the code before writing this (2026-09-07):

- `package/boonyard/aggregator.py` — the `Aggregator` opens each node with `query_only = ON` (L106, L147) and stamps every returned row with `source`, the node it came from (L188/199/209/216/235). Read-only is a property **of this class**, not of any URL.
- `package/boonyard/mcp.py` — `MCPServer` is constructed with either `db_path` (one node, writable) **or** `aggregator` (many nodes, read-only): L246–254, `_read_only = aggregator is not None`, `_call_aggregator` L506.
- `saas/boonyardnn/router.py` — `Router.parse_path` (L134–152) accepts two or three path parts, `/{user}/{node}[/key]`; `saas/boonyardnn/registry.py` L142 stores a key's scope as the plain string `'node:{node_id}'`, minted at L462.

The decisive observation: **a per-user endpoint and the read-only aggregator are different objects, and conflating them is what has made this look impossible.** A door that serves many nodes does not have to union them to serve a write; it opens exactly one node writable, precisely as `/{user}/{node}` does today. The union is only needed for reads that span nodes.

## Decision

### 1. A third endpoint form

```
https://mcp.boonyard.com/{user_slug}                     <- NEW: the account endpoint
https://mcp.boonyard.com/{user_slug}/{node_slug}         <- unchanged (ADR-0008)
https://mcp.boonyard.com/{user_slug}/_aggregate          <- unchanged; subsumed in practice
```

The account endpoint dispatches **per call, not per endpoint**: a call naming a node is served by a single-node `MCPServer` opened on that node's file; a read naming no node, or several, is served by an `Aggregator` over the nodes the key reaches. `_aggregate`'s read-only guarantee is untouched, because nothing about the `Aggregator` class changes.

### 2. A third key scope

`user:{user_id}`, alongside `node:{node_id}` and ADR-0008's `aggregator:{node_ids}`. Same storage: `secrets.token_hex(32)`, `bnyk_` prefix, sha256 at rest, raw shown once, revocable, labelled.

**Per-node keys remain first-class and are not deprecated.** They are the right primitive whenever a *different actor* holds the key: a collaborator given one node, a CI job, a narrow-scope agent, a shared node in a future Team. The account key is the right primitive when one person holds all of them — which is the common case, and the case the product currently serves worst.

### 3. The tool list is served per endpoint, and that is what makes this safe

`tools/list` is answered per connection, so the same server advertises **different schemas at different doors**:

- At `/{user}` — every write tool (`log_entry`, `log_skill_revision`) declares `node` as a **required** parameter. Read tools keep `scope`.
- At `/{user}/{node}` — no `node` parameter is advertised at all; the path fixes it, exactly as today.

The model therefore sees precisely the right shape at whichever door it is connected to, and the mitigation below is structural rather than conventional.

### 4. No default node for writes on the account endpoint

ADR-0008 allowed a key's default node for writes. **At the account endpoint there is no default.** A write must name its node. The failure this buys back is real and would otherwise be routine: with one door, a seat can file a JR Hood entry onto the Mycelium wall — impossible today, because the connector *is* the node. Requiring the argument makes a misfile a *wrong* value rather than a *forgotten* one, and `list_nodes` plus the `instructions` readme put the right values one call away.

### 5. Reads

`scope` keeps its ADR-0008 meaning — omitted, a name, a list, or `'all'`. At the account endpoint, omitted means **all nodes the key reaches**. Every row carries `source` as it already does.

### 6. Discovery

`list_nodes` is the "shows the available nodes" surface and **already ships** — it returned six through the aggregate door on 2026-09-07 (boonyard #145). At the account endpoint it lists the nodes the presented key can reach, with entry counts and last-write times.

### 7. Limits and quotas

Rate limits attach to the **account** for account-scoped keys, so minting more keys cannot multiply a tier's ceiling. Per-node keys keep the per-key accounting of ADR-0008's table. Tier resolution is ADR-0011 §1's `effective_tier()` — the one authority, unchanged.

### 8. Revocation, stated at mint time

Revoking an account key cuts access to **every** node at once. That is a feature (one button when a laptop is lost) and a risk (one button when a finger slips). The dashboard says so where the key is minted, not in a doc nobody opens.

### 9. Cross-presentation

An account key presented at `/{user}/{node}` works — it is a superset. A node key presented at `/{user}` is **refused**: it cannot name nodes it has no scope for, and silently degrading it to one node would teach the wrong model of the door.

### 10. Composition with Teams (PHASE_3 §3), noted not decided

A future team endpoint `/~{team_slug}` follows this shape exactly, with scope `team:{team_id}`. Nothing here forecloses it and nothing here builds it.

### Decisions — ruled 2026-09-07

| # | Choice | Decision (Professor, 2026-09-07) |
|---|---|---|
| 1 | Take it at all | **YES** |
| 2 | Which door the docs and dashboard present as default | **the account endpoint**; per-node keys documented as the sharing/narrow-scope tool |
| 3 | Rate limits per account for account keys (§7) | **YES** |
| 4 | Build before or after the wall migration | **BEFORE** — build, prove on throwaway nodes, then migrate the six walls onto it, so Professor points ONE connector ONCE (umbrella #394) |

## Consequences

**Positive:** one connector per person instead of one per node — the onboarding story becomes "connect one thing, see all your memory." Every tutorial gets shorter (umbrella #388). The Free tier's three nodes feel like one product rather than three chores. The wall migration lands on its final target instead of a waypoint. `_aggregate` is subsumed: cross-node reads are native at the account door.

**Negative:** the blast radius of one leaked key grows from one node to every node in the account — accepted deliberately, mitigated by keeping per-node keys first-class (§2) and by saying it at mint time (§8). The wrong-node write becomes possible where it was previously impossible — bought back structurally by §3 and §4, not by a warning. Rate-limit accounting changes unit for one key class (§7).

**Neutral:** the six live walls do not appear at the account endpoint until they are in the registry — i.e. until the migration. That is a feature of the build-first order: the door is built and proven on throwaway nodes, and the walls appear through it automatically the moment they move.

## Alternatives considered

**Keep per-node endpoints only (status quo).** Rejected: it does not scale past a handful of nodes, and it asks the user to do setup work that exists only because of how the system grew.

**Make `_aggregate` writable.** Rejected, and it is the tempting wrong answer: it would break the `Aggregator`'s `query_only` guarantee, which ADR-0003 leans on for cheap aggregation and which is a real safety property. The account endpoint gets the same result without touching it, by dispatching writes to a single-node server.

**A default node for writes at the account endpoint.** Rejected — see §4. A silent misfile into the wrong memory is worse than an error, because append-only means it cannot be taken back, only corrected.

**OAuth per connector.** Rejected for the same reason ADR-0008 rejected it: overkill for a machine-driven, single-actor access pattern. A bearer key the user mints and revokes is the right shape.

**Per-node keys deprecated in favour of account keys.** Rejected: sharing one node with one person is a real use case that per-node keys serve exactly, and Teams will need them.

## References

- ADR-0003 (db-per-node + aggregator; the `scope` mechanic), ADR-0008 (routing, per-node keys, `_aggregate` read-only — extended here), ADR-0011 §1 (`effective_tier`, the one authority for tier)
- architecture/05 (access-control rules), architecture/06 (the MCP tool surface), roadmap/PHASE_3 §3 (Teams), §9 (the Umbrella app as an aggregator consumer)
- Walls: umbrella #375 (the three shapes; this is option (c)), #386 (the flat aggregate door), #394 (Professor's proposal and the reorder); boonyard #145 (`list_nodes` → six through one door, measured)
