# Security Policy

## Reporting a vulnerability

Email **security@boonyard.com**, with "boonyard security" in the subject.

Please don't open a public issue for anything that looks exploitable. An ordinary bug that
happens to be embarrassing belongs in the tracker; something that lets a stranger read or
corrupt data they shouldn't does not.

Useful things to include, roughly in order of usefulness:

- The smallest input or sequence that reproduces it.
- Python version, OS, and whether the node was opened locally or served over MCP.
- What happened, and what you expected instead.
- Whether you think it's remotely reachable, or only reachable by someone who already has
  the node file.

**Don't paste real node contents.** Your entries are yours, and they're probably partly
somebody else's. Reproduce against a fresh throwaway node.

## What to expect back

The honest version: this is a one-person project, maintained at a hobby cadence alongside
several others. There is no security team, no rotation, and no pager.

- **No SLA.** Nobody here can promise a response time and mean it, so this document doesn't
  contain one. If it matters and you've heard nothing, mail again — a second mail isn't rude.
- **A human will reply** before any fix is discussed. No time bound attached to that, per the
  point above.
- **You'll be credited** in the changelog entry for the fix, unless you'd rather not be.
- **There is no bug bounty.** No money, no swag, no points. Better to learn that here than
  after you've spent a weekend on it.

## Coordinated disclosure

Please give the fix a chance to exist before the report does. Ninety days from your first
mail is the outside figure this project asks for, and less is usually fine — most of what
this package does is small enough to fix in an evening.

If you've heard nothing at all, disclose anyway. Silence isn't a veto, and a maintainer who
has gone quiet shouldn't get to sit on a live problem indefinitely.

## What's in scope

The package is stdlib-only, ships no network client, and phones home to nothing
([ADR-0006](docs/adr/0006-oss-core-saas-freemium.md)) — which removes whole categories of
supply-chain and telemetry risk. What remains, and what this project actually worries about:

- **Node isolation.** Anything that lets one node read or write another. The aggregator opens
  many nodes read-only ([ADR-0003](docs/adr/0003-db-per-node-plus-aggregator.md)); a path
  that makes it writable, or that crosses from one node into another, is the
  highest-severity class here.
- **Key material.** Anything that leaks, logs, or makes guessable the MCP server's bearer
  key or a capability URL.
- **Payload escape.** A crafted entry — content, tags, or the JSON `extras` column — that
  escapes its own row: SQL or FTS5 injection, or anything that executes rather than stores.
- **Append-only integrity.** There is no delete path and no update path, by design
  ([ADR-0005](docs/adr/0005-append-only-no-deletes.md)). Anything that silently destroys or
  rewrites history defeats the single promise this project makes.
- **The MCP server's exposed surface**, when a node is served rather than opened locally.

## What's not in scope

- Someone who already has your node file reading it. It's a SQLite file on your disk with no
  at-rest encryption, and it has never claimed otherwise.
- The hosted service at `boonyardnn.com`. It is designed and **not built** — there's nothing
  running to report a vulnerability in.
- Denial of service by deliberately handing the package an enormous input.
- Anything that requires a modified copy of the package.

## Supported versions

Only the latest release on `main` receives fixes. There are no backports to earlier lines.

The major version is the schema version, not a marketing number — a package on `3.x` reads
and writes v3 nodes. A security fix won't change it.
