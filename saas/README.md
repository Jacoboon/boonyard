# boonyardnn — the hosted layer (Phase 2)

The SaaS side of the ADR-0006 line. It is not the substrate; it is the door, the directory
and the front desk around the substrate.

- **Provisioner** (`python -m boonyardnn user|node|key|export`) — makes ADR-0007's
  per-user directory, initialises a real node with the package's own `init_db`, mints
  ADR-0008's per-node `bnyk_` key (sha256 at rest, printed once), exports a node.
- **Router** (`python -m boonyardnn serve`, loopback 8800) — one `ThreadingHTTPServer`;
  `POST /{user_slug}/{node_slug}[/{key}]` resolves the node directory and hands the
  JSON-RPC body to the package's `MCPServer.handle()`. Same 18 tools as a self-hosted
  node, byte for byte. Public as `https://mcp.boonyard.com`.
- **Accounts + web app** (`python -m boonyardnn serve-web`, loopback 8801) — signup with
  email verification, sign-in by emailed link **or** password (user's choice), sessions,
  and a dashboard that does four things: create a node, mint a key (shown once), revoke a
  key, export a node. The first twenty verified signups are **founders** (a year free);
  `/app/founders.json` is the public counter the landing page reads. Public as
  `https://boonyard.com/app`.
- **Mailer** — one function, one provider behind it: AgentMail over its REST API
  (`urllib`, no SDK). `log` and `none` modes exist for tests and for a box without a key.

- **Node browser** (`/app/nodes/{slug}`) — arch 07's single-node view: recent entries,
  search by text or tag, threads, write an entry from the browser as the human seat,
  retag with a reason (the audited mutation), export, and tombstone a node with a typed
  confirmation. There is no entry edit and no entry delete (ADR-0005): "edit" is a reply
  threaded to the old entry, one click.
- **Limits** — ADR-0008's per-key rate limits (Free 30 writes / 600 reads per minute,
  Pro 600 / 6000, burst 10×; 429 + `Retry-After`) and the Free cap of 10,000 entries per
  node (403 `quota_exceeded`; export or start another node). Founders are Pro for a year.
- **Backups** — `python -m boonyardnn backup-config --base /etc/boonyard/umbrella.toml`
  emits the `[nodes]` table the nightly `backup_walls.py` reads: the six walls plus every
  hosted node, keyed `user__node`, discovered from the registry at run time.

Not here: billing, teams, `_aggregate` (Phase 3).

## The one rule

`boonyardnn/adapter.py` is the only module that imports `boonyard`. A test greps for it.

## Run it locally

```bash
pip install -e .            # the package (from the repo root; once)
pip install -e saas/        # this layer
export BOONYARDNN_DATA_ROOT=/path/to/data     # or pass --root on every command
export BOONYARDNN_MAIL=log                    # captured, not sent (default without a key: none)
python -m boonyardnn serve     --port 8800 &  # the MCP door
python -m boonyardnn serve-web --port 8801    # the app at http://127.0.0.1:8801/app/
```

Open `http://127.0.0.1:8801/app/signup`. In `log` mode the verification link is not
mailed; print one with `python -m boonyardnn account link you@example.test` and open it.

Provisioning by hand still works and is what the app calls underneath:

```bash
python -m boonyardnn user add jacoboon --email you@example.test
python -m boonyardnn node add jacoboon test-0
python -m boonyardnn key  add jacoboon test-0 --label "code seat"   # prints the key ONCE
python -m boonyardnn account import jacoboon --email you@example.test   # give it a login
```

## Environment

| Variable | Meaning | Default |
|---|---|---|
| `BOONYARDNN_DATA_ROOT` | the data root (or `--root`) | none — required |
| `BOONYARDNN_PUBLIC_BASE` | the router's public URL, shown in the dashboard and by `key add` | `http://127.0.0.1:8800` |
| `BOONYARDNN_WEB_BASE` | the app's public URL, used in mailed links | `http://127.0.0.1:8801` |
| `BOONYARDNN_FOUNDER_SEATS` | how many founder seats | `20` |
| `BOONYARDNN_MAIL` | `agentmail` / `log` / `none` | `agentmail` if a key is set, else `none` |
| `AGENTMAIL_API_KEY`, `AGENTMAIL_INBOX`, `AGENTMAIL_REPLY_TO` | the sender | — |
| `BOONYARDNN_MAIL_OUTBOX` | in `log` mode, a JSON-lines file to append to | — |

## Layout on disk (ADR-0007)

```
{root}/users.json                         slug -> user_id
{root}/users/{user_id}/                   0700
    metadata.json                         user + node records
    api_keys.json                         sha256 hashes only
    nodes/{node_slug}/                    0700: journal.db, boonyard.toml, meter.db, backups/
    exports/export_{ISO8601}.zip
{root}/system/users.db                    0600: accounts, tokens (sha256), sessions (sha256),
                                          mail/request rate-limit events. Never an entry.
```

## Tests

```bash
python -m unittest discover -s saas/tests -t saas
ruff check saas
```

`tests/test_web.py` runs the whole path in one test: signup → verification link → dashboard
→ create node → mint key → an MCP call through the router with that key → export → revoke →
401.
