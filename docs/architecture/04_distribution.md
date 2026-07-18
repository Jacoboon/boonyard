# Architecture 04 — Distribution: package + SaaS, four access surfaces, same code

How users get BoonyardNN, and how the same engine drives every flavor of access.

## The four ways to use BoonyardNN

### 1. `pip install boonyard`

```bash
pip install boonyard
boonyard init --name my-project
boonyard mcp --port 8765 &
```

Standard package install. Stdlib-only (ADR-0001), so no transitive deps. Works on any Python 3.11+. The user gets the package, the CLI (`boonyard`), and the MCP server module they can run locally.

### 2. Vendoring

```bash
cd my_project/
git clone https://github.com/jacoboon/boonyard.git _dev/boonyard.tmp
cp -r _dev/boonyard.tmp/package/boonyard _dev/boonyard
rm -rf _dev/boonyard.tmp
```

Or, more frequently:

```bash
# Pin to a release tag for stability
curl -L https://github.com/jacoboon/boonyard/archive/refs/tags/v3.0.0.tar.gz | tar xz
cp -r boonyard-3.0.0/package/boonyard my_project/_dev/boonyard
```

Stdlib-only means this works. The user's project imports `_dev.boonyard.log_entry` like any first-party module. No `pip install` step. No dep conflicts with the host project. This is the in-project mode's preferred install (architecture 03).

### 3. Docker self-host

```bash
docker run -d \
    --name boonyard \
    -v /home/user/boonyard-data:/data \
    -p 8765:8765 \
    boonyardnn/boonyard:latest
```

The same package, plus a minimal web shell (Flask) and a Dockerfile. For users who want hosted-style ergonomics without using the SaaS. The image is built from the OSS repo; runs the same boonyard code; uses the same SQLite-file storage.

This is also the deployment shape the SaaS uses internally — boonyardnn.com is a hardened, multi-tenant, billed wrapper around the same Docker image fundamentals.

### 4. `boonyardnn.com` (SaaS)

```
1. Sign up at boonyardnn.com.
2. Create a node ("planescape").
3. Copy the per-node MCP URL + API key.
4. Point your AI seats / CLI at it.
```

Hosted by us. Multi-tenant. Free tier exists; paid tier for unlimited nodes + Umbrella view. The user runs nothing themselves.

## Why these are four flavors of one product, not four products

The boonyard Python package is the engine. Each of the four delivery shapes above is a different way to get that engine running near where the user is.

| Flavor | Engine | Storage | Auth | Web UI |
|---|---|---|---|---|
| pip install | boonyard package | user's filesystem | none (localhost) | optional (the OSS dashboard) |
| vendored | boonyard package | host project's filesystem | none | none usually |
| Docker self-host | boonyard package + Flask shell | volume-mounted filesystem | optional (configurable) | yes (OSS dashboard) |
| SaaS | boonyard package + multi-tenant web layer | server-side filesystem | mandatory | yes (full dashboard) |

The package is the constant. The wrappers vary. A user can switch between flavors at any time because the data format is the same SQLite file in every flavor — export from SaaS, import into Docker, drop the SQLite file into a vendored project, all roundtrip cleanly.

## The four access surfaces

Each flavor exposes some or all of:

### Python API

```python
from boonyard import (
    init_db, log_entry, log_skill_revision,
    recent, by_id, get_thread,
    search_by_tag, search_text,
    list_tags, list_agents, list_entry_types,
    list_skills, latest_skill,
    aggregator,
)
```

The principal interface for in-project mode and for any custom tooling. Available in every flavor.

### CLI

```bash
boonyard --help
boonyard init [--name X] [--profile <path>]
boonyard log <agent> <entry_type> <content> [--tags X,Y] [--related ID] [--extras JSON]
boonyard recent [N] [--agent X] [--type Y]
boonyard show <id>
boonyard thread <root_id>
boonyard tag <tag> [N]
boonyard find <fts_query> [N]
boonyard tags [--prefix X] [--tree]
boonyard agents
boonyard types
boonyard skills [N]
boonyard skill latest <slug>
boonyard skill new <slug>
boonyard doctor                  # audit; warn about unprecedented tags, missing skills root-anchors, etc.
boonyard reindex                 # rebuild FTS + entry_tag + extras expression indexes
boonyard backup [<path>]
boonyard export [<path>]
boonyard import <path>
boonyard mcp [--port PORT] [--db <path>] [--config <multi-db-config>]
boonyard umbrella init|add|remove|list|recent|find|tags|...
```

Same in pip-installed, vendored (via `python -m boonyard.cli`), Docker (via `docker exec`), and SaaS (via remote `--remote <url> --key <key>` flags).

### MCP server

Long-lived process. Default port 8765 locally; in SaaS, served behind `mcp.boonyardnn.com`. Path-based routing maps URL segments to node files. Same tool definitions across deployments. (Full surface in `06_mcp_surface.md`.)

### REST API (SaaS only)

```
GET    /api/v1/nodes
POST   /api/v1/nodes
GET    /api/v1/nodes/{slug}/entries
POST   /api/v1/nodes/{slug}/entries
GET    /api/v1/nodes/{slug}/entries/{id}
GET    /api/v1/nodes/{slug}/threads/{root_id}
GET    /api/v1/nodes/{slug}/tags
GET    /api/v1/nodes/{slug}/skills
POST   /api/v1/nodes/{slug}/export
POST   /api/v1/nodes/{slug}/import
GET    /api/v1/aggregate/recent?scope=...
GET    /api/v1/aggregate/find?q=...&scope=...
...
```

For the web dashboard, for third-party integrations, for users who prefer HTTP to MCP. Only exists in the SaaS flavor (and in Docker self-host if the user enables it via config). Auth: same bearer keys as MCP.

## How the SaaS reuses the OSS package

Inside `boonyardnn.com`, the entire data layer is:

```python
import boonyard

# routing layer (Flask blueprint)
@app.post("/{user_slug}/{node_slug}/log")
def log(user_slug, node_slug):
    user = authenticate(request)
    if user.slug != user_slug:
        abort(403)
    node = lookup_node(user, node_slug)
    if node is None:
        abort(404)

    # Open the user's node file with the OSS package's connect()
    with boonyard.connect(node.db_path) as conn:
        new_id = boonyard.log_entry(
            agent=request.json["agent"],
            entry_type=request.json["entry_type"],
            content=request.json["content"],
            tags=request.json.get("tags"),
            related_id=request.json.get("related_id"),
            extras=request.json.get("extras"),
            conn=conn,
        )
    return {"id": new_id}
```

The SaaS routing layer is web-framework code. The data layer is *literally* the OSS package. A feature added to `boonyard.log_entry` shows up in the SaaS without any extra work; a bug fixed in the OSS package fixes the SaaS too.

## Versioning and release

- **`boonyard` package:** semantic versioning. Major version = schema version (so package v3 corresponds to schema v3). Minor = additive features. Patch = bug fixes. Release tagging in git, published to PyPI.
- **`boonyardnn/boonyard:latest` Docker image:** built from each tagged release; `:vX.Y.Z` tags for specific versions; `:edge` for HEAD-of-main.
- **`boonyardnn.com` SaaS:** deployed continuously from main after CI passes. The deployed package version is shown in the dashboard footer. The SaaS may run ahead of the latest pip release for a few days while new features bake.

Migration: a v(N)→v(N+1) bump comes with a migration script in `package/boonyard/migrations/v(N)_to_v(N+1).py`. The SaaS runs the migration as part of deployment; OSS users run it via `boonyard migrate`. Migration is idempotent; nodes already on the target version no-op.

## Configuration

The package reads configuration in this order of precedence (highest wins):

1. Direct function arguments (`log_entry(..., db_path='/explicit/path')`).
2. Environment variables (`BOONYARD_DB_PATH`, `BOONYARD_PROFILE_PATH`).
3. Local `boonyard.toml` (the schema profile; also accepts a `[runtime]` section for non-schema settings).
4. User-level config (`~/.config/boonyard/config.toml`).
5. Built-in defaults.

The SaaS layer ignores 3 and 4 entirely — node paths are derived from the URL routing — and uses 1 to inject the right path per request.

## Dependencies of the SaaS web layer (allowed)

Per ADR-0006, the SaaS is allowed external dependencies. The intended stack (deferred to Phase 2 for final selection):

- **Flask** for the web app (small, well-known, similar to the JRHood stack already in production).
- **gunicorn** for the WSGI server.
- **nginx** for TLS termination and reverse-proxy (same as JRHood's deploy).
- **cloudflared** for the public DNS / DDoS protection (same pattern as the live Vectorscape NN at `nn.vectorscape.uk`).
- **stripe** for billing (Phase 3).
- **redis** *only if* per-key rate limiting at scale demands it; otherwise SQLite-based rate counters are sufficient for the initial user volumes.

These belong to the SaaS deployment, not to the package. The package never imports any of them.

## A note on the "this is just SQLite" vibe

If a user reads through the architecture and concludes "this is just SQLite with some Python wrappers and a CLI" — they're right, and that's the point. The substrate's value isn't in being clever about storage; it's in being **disciplined about what the substrate is** and providing a coherent shape (entry + tags + threading + scope + MCP + skills) on top of an extremely well-understood storage engine.

The SaaS's value is similarly not in being clever about hosting; it's in running the obvious-correct thing reliably so users don't have to. The differentiator is the substrate's discipline (CHARTER + ADRs), not novel infrastructure.

## See also

- ADR-0001 — stdlib-only (the constraint that makes vendoring viable)
- ADR-0006 — OSS/SaaS split (the principle these flavors realize)
- ADR-0007 — multi-tenant storage layout (where SaaS files live)
- ADR-0008 — MCP routing (how the surfaces in this doc map to URLs)
- `03_scope_model.md` — how scope works in every flavor
- `06_mcp_surface.md` — the MCP tool definitions
