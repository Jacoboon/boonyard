"""boonyardnn — the hosted layer for the boonyard substrate (Phase 2, slice 1).

Two things, and only two (umbrella #334 ¶4, #335):

* a **provisioner** that makes ADR-0007's per-user directory and mints ADR-0008's
  per-node ``bnyk_`` key (sha256 at rest, shown once);
* a **router** that maps ``POST /{user_slug}/{node_slug}[/{key}]`` to that
  directory per request and hands the JSON-RPC body to the package's own
  ``MCPServer.handle()`` — so the tool surface is byte-identical to a self-hosted
  node (ADR-0006: same package, same file).

No signup, no dashboard, no billing, no ``_aggregate``, no rate limits — those are
slice 2 and Phase 3. ``adapter.py`` is the only module that imports ``boonyard``.
"""

__version__ = "0.1.0.dev0"
