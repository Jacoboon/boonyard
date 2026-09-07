"""boonyardnn — the hosted layer for the boonyard substrate (Phase 2, slices 1 and 2).

* a **provisioner** that makes ADR-0007's per-user directory and mints ADR-0008's
  per-node ``bnyk_`` key (sha256 at rest, shown once);
* a **router** that maps ``POST /{user_slug}/{node_slug}[/{key}]`` to that
  directory per request and hands the JSON-RPC body to the package's own
  ``MCPServer.handle()`` — so the tool surface is byte-identical to a self-hosted
  node (ADR-0006: same package, same file);
* **accounts** (``system/users.db``: signup, email verification, magic-link AND
  password sign-in, sessions, the founders counter) and the **web app** at ``/app``
  (signup → verify → dashboard: create node, mint key shown once, revoke, export)
  — Professor's order, boonyard #109/#113/#115; the pages are forms over the
  provisioner;
* a **mailer** with one provider behind one function (AgentMail).

No billing, no ``_aggregate``, no per-key rate limits — Phase 3. ``adapter.py`` is
the only module that imports ``boonyard``.
"""

__version__ = "0.2.0.dev0"
