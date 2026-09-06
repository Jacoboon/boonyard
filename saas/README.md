# boonyardnn — the hosted layer (Phase 2, slice 1)

The SaaS side of the ADR-0006 line. It is not the substrate; it is the door and the
directory around the substrate. Two things, and only two:

- **Provisioner** (`python -m boonyardnn user|node|key|export`) — makes ADR-0007's
  per-user directory, initialises a real node with the package's own `init_db`, mints
  ADR-0008's per-node `bnyk_` key (sha256 at rest, printed once), exports a node.
- **Router** (`python -m boonyardnn serve`) — one `ThreadingHTTPServer`;
  `POST /{user_slug}/{node_slug}[/{key}]` resolves the node directory and hands the
  JSON-RPC body to the package's `MCPServer.handle()`. Same 18 tools as a self-hosted
  node, byte for byte.

Not here yet: signup, dashboard, billing, teams, `_aggregate`, rate limits. The signup
platform and user database are the next slice (Professor, boonyard #109); the rest is Phase 3.

## The one rule

`boonyardnn/adapter.py` is the only module that imports `boonyard`. A test greps for it.

## Run it locally

```bash
pip install -e .            # the package (from the repo root; once)
pip install -e saas/        # this layer
export BOONYARDNN_DATA_ROOT=/path/to/data     # or pass --root on every command
python -m boonyardnn user add jacoboon --email you@example.test
python -m boonyardnn node add jacoboon test-0
python -m boonyardnn key  add jacoboon test-0 --label "code seat"   # prints the key ONCE
python -m boonyardnn serve --host 127.0.0.1 --port 8800
```

`BOONYARDNN_PUBLIC_BASE` (default `http://127.0.0.1:8800`) changes only the URLs
`key add` prints — the header form and the capability-URL form.

## Layout on disk (ADR-0007)

```
{root}/users.json                         slug -> user_id
{root}/users/{user_id}/                   0700
    metadata.json                         user + node records
    api_keys.json                         sha256 hashes only
    nodes/{node_slug}/                    0700: journal.db, boonyard.toml, meter.db, backups/
    exports/export_{ISO8601}.zip
```

## Tests

```bash
python -m unittest discover -s saas/tests -t saas
ruff check saas
```
