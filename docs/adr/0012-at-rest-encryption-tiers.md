# ADR 0012 — At-rest encryption: what boonyard.com can truthfully promise, in two tiers

**Status:** ACCEPTED 2026-09-07 — Professor's ruling, verbatim on the umbrella wall (the decision entry threaded to #360): *"Again agreed, T1 at launch."* Tier 1 (§1) is the launch tier; Tier 1.5 (§2) is not taken; Tier 2 (§3) is a roadmap line and not a site promise; the privacy page carries the [TODAY] sentences until Tier 1 is verified live. The droplet order that executes §1 is the Conductor's to cut and it is countersigned without exception — it touches the disk every wall lives on (umbrella #333).
**Date:** 2026-09-07
**Deciders:** Jacob (Professor); drafted by the Conductor (Cowork, model:claude-fable-5-1) from the design handoff (umbrella #351) and the Code seat's map at boonyard #114
**Supersedes:** —
**Superseded by:** —

## Context

Professor, verbatim (boonyard #113): *"People will know that these permanent growing memories are stored on a server. Can we encrypt it somehow?"* and (#118) *"can we say it's even encrypted from us? Is that level of security even possible? Can we encrypt their user folders on our droplet? Am I going overboard?"*

The Code seat's map (boonyard #114) is right on its central point and this ADR keeps it: **encryption is never on or off; it is always against whom.** Four people: (1) whoever gets the disk or a copy of it but not the running server; (2) whoever has root on the running server, the operator included; (3) the operator, who must not be able to read it at all; (4) the user who leaves and wants it gone.

What is already true (boonyard #114, #116, #120): in transit everything is TLS to Cloudflare and tunnelled to the box (Cloudflare sees plaintext at its edge — every site it fronts); per-user and per-node directories 0700; keys stored only as sha256; router and web log no URL and no body; the meter records tool names, never arguments; root by ssh key only; nightly backup bundles are 0600 on the box, restore-proven, **local only — no offsite copy yet** (umbrella #352, #270).

What is NOT true, measured: the droplet's local disk is not encrypted at rest (DigitalOcean's own docs, cited at #114); the box is ext4 **without** the `encrypt` feature, kernel 6.8, `fscrypt` not installed (#116); backup bundles are plaintext copies of every founder's node and would leave the box that way the day rung 4 (#270) lands.

Two findings this draft adds to #114's map, because an ADR that repeats the map without checking it is decoration:

- **A per-user key that lives on the same disk as the data defends against nobody who has the disk.** A leaked droplet snapshot contains `/etc` too. Service-held fscrypt keys therefore do *not* cover person (1) — they cover the *backup-bundle* case only if the bundles are encrypted to a key that is elsewhere, and they give crypto-shredding only for **copies made after the key is destroyed**. Snapshots that already exist keep both the ciphertext and the key. Any privacy sentence about shredding has to say how long a snapshot lives.
- **fscrypt policies apply to empty directories only.** `tune2fs -O encrypt` is online-safe, but the existing `users/` tree cannot be encrypted in place: stop web + router, move the tree aside, create the encrypted directory, copy in, verify, start. A small sitting, but a downtime sitting, and it grows with every founder who signs up before it happens.

The web node browser (boonyard #120) changes nothing under Tier 1 — the server decrypts to serve, the browser is another client — and adds one hard constraint under Tier 2, named in §3.

## Decision

### 1. Tier 1 — "encrypted at rest against a leaked copy" — the launch promise

Three parts, all provider- or file-level, none of which change the package or the schema:

**1a. Backup bundles are encrypted before they exist as files anyone could copy.** `backup_walls.py`'s bundle step pipes through `age` with a **public key whose private half never touches the droplet** — Professor holds it, offline, with a printed copy in the same place as the DOR/IRS papers. Restore-proof runs on the encrypted bundle (decrypt into a scratch dir, verify, discard), so the nightly heartbeat still says VERIFIED and #80's law holds. This is the part that makes rung 4 (#270) safe to build at all. *Defends: person (1), for the copies that leave the box.*

**1b. The data tree moves to a DigitalOcean Volume.** `/var/lib/boonyard` → a 10 GB Volume mounted at the same path (a mount, a copy, an fstab line, one restart window of minutes). DO Volumes are encrypted at rest with keys DO manages (LUKS, AES-256 — #114's cited source), and their snapshots inherit it. *Defends: person (1), for the live disk and for provider-side decommissioning, with zero key management on our side.* Cost: roughly a dollar a month. **One fact to verify before the order is cut, not recalled:** whether the droplet's own daily backup (#319) includes attached Volumes — the DO docs answer it; the ADR does not.

**1c. Account close = export, then removal, on a stated clock.** ADR-0007's teardown (`rm` of the user's directory) after arch 05's grace; backups age out on their retention (30 days Free); Volume snapshots we take are on our clock. The privacy page states the longest of those numbers as "the last copy is gone within N days." *Answers: person (4), honestly — as a retention promise, not a cryptographic one.*

**What Tier 1 does not do, said on the privacy page in one sentence:** it does nothing against root on the running server, and the operator is root. The honest sentence already on `/app/privacy` stays: *a server that can search your entries can technically read them, and so can the person who runs it. We don't.*

### 2. Tier 1.5 — per-user keys (fscrypt) — optional, not recommended for launch

#114's fscrypt path, kept on the record with its true value: **one key per user directory** so that account close can destroy a key instead of trusting an `rm` — the only mechanism that makes "gone" cryptographic rather than procedural. Its costs, stated: the empty-directory migration above; a wrapping key that must live *off* the Volume for the shredding to mean anything against existing snapshots (or a snapshot retention short enough to state); the `fscrypt` tool as a system dependency; a boot-time unlock step before the router and web units start, which, if the wrapping key is truly off-box, means **a reboot waits for a human** — on a one-vCPU box that reboots for every resize.

Recommendation: **do not take this at launch.** Take it if and when a customer asks for cryptographic deletion in writing, or when the cohort is large enough that "we `rm` it" is not a sentence Professor wants to stand behind. It composes with 1a–1c; nothing in Tier 1 has to be undone.

### 3. Tier 2 — "encrypted from us" — the differentiator, as a roadmap line, not a launch promise

The design, pinned here so it is not re-derived later (boonyard #114 person (3); #118 §2):

- Each node gets a random **data key** `K_n`. The node's `journal.db` is stored only as ciphertext under `K_n`. The server holds **no** copy of `K_n` at rest.
- Every bearer key `k_i` for that node yields a wrapping key `HKDF(k_i)`; the server stores `wrap(HKDF(k_i), K_n)` beside the key's sha256. A request carrying a valid bearer unwraps `K_n` in memory, serves, and forgets. Revoking a key deletes its wrap; minting a key requires presenting an existing one (or a web session that holds `K_n`). A **recovery code** shown once at node creation is one more wrap. Lose every key and the recovery code, and the node is ciphertext forever — that sentence goes on the node-creation screen, not in a footnote.
- **The web browser constraint:** a session must hold `K_n` for its duration — derived from the password at sign-in for password users (password change = re-wrap, not re-encrypt), pasted once per session for magic-link users, memory only, never a cookie.
- **The cost nobody has said out loud yet:** SQLite cannot query a ciphertext file. Tier 2 is either SQLCipher (a compiled dependency, not stdlib — allowed in `saas/`, ADR-0001 fences the package, but it is a different `sqlite3` module) or decrypt-the-whole-file-to-tmpfs-per-request (fine at today's sizes — the six walls are 0.08–2.2 MB each, umbrella #352 — and wrong at 100 MB, and it breaks WAL and any concurrent write). And the hosted aggregator (`_aggregate`, ADR-0008; not built — umbrella #335 (d)) needs every node's key at once. Tier 2 is a storage-engine decision, not a feature toggle.
- **It does not need to exist for the promise to be true today:** the self-hosted package is the same code, on the user's disk, with the user's keys — zero-knowledge by construction, free, forever (ADR-0006). The landing page and the privacy page say so; that is the answer to "encrypted from us" until Tier 2 ships.

Recommendation: **roadmap, named, undated, no promise on the site beyond "self-host if you need us unable to read it."** Build it when a paying customer's requirement is written down, or when Professor decides it is the product's edge and worth a storage-engine change.

### 4. The privacy page, by tier

The four true sentences on `/app/privacy` today are correct for **today**. Two sentences change as tiers land — the drafts in `docs/legal/PRIVACY_POLICY_DRAFT.md` carry both versions marked:

| | Today (before any order) | After Tier 1 |
|---|---|---|
| at rest | "The disk your node lives on is not encrypted at rest yet; the directory is readable only by the service." | "Your node lives on an encrypted volume; every backup is encrypted before it is written, with a key that is not on the server." |
| leaving | "Closing your account removes your files; backups age out within 30 days." | same, with the measured number for snapshots |

### Decisions — ruled 2026-09-07

| # | Choice | Decision |
|---|---|---|
| 1 | Tier 1 at launch: 1a + 1b + 1c | **yes** — one droplet sitting, countersigned; before the Discord post if the post can wait a sitting, after it if it cannot (nothing today is *worse* than yesterday, and the bundles do not leave the box yet). Order of operations inside the sitting: 1a (encrypted bundles) first — it is the half of umbrella #339 still open (#359) and the dependency ahead of rung 4 (#270) — then 1b, then 1c's numbers measured and written into the privacy page |
| 2 | Tier 1.5 (fscrypt per-user keys) | **not now** — composes later without undoing anything |
| 3 | Tier 2 as a launch promise | **no** — a roadmap line; self-host is the zero-knowledge answer on the site |
| 4 | The privacy-page wording | **the [TODAY] sentences until Tier 1 is verified live**, then the [AFTER TIER 1] sentences — never the later sentence early |

## Consequences

**Positive:** every promise on the privacy page maps to a mechanism that exists or a sentence that says it does not yet. Rung 4 offsite (#270) becomes safe to build (encrypted bundles). Provider-managed disk encryption costs a dollar and no key ceremony. The Tier 2 design is on the record with its real cost, so nobody sells it as a toggle.

**Negative:** Tier 1 does not defend against the operator, and the page says so — some prospects will read that sentence and self-host instead, which ADR-0006 calls a feature. A Volume is one more thing in the DO panel and one more thing a restore must re-attach — the restore proof has to include the mount, or it proves the wrong thing.

**Neutral:** the `age` private key becomes the single most important secret the company holds; it belongs with the papers, on paper, in two places, and it is never on a wall, in a repo, or in a seat's context (CONDUCTOR.md redlines).

## Alternatives considered

**fscrypt with service-held keys as the launch tier (#114's recommendation, the handoff's Tier 1).** Kept as Tier 1.5. Not chosen for launch because with the key on the same disk it defends against nobody who has the disk; its real value (cryptographic deletion) needs the off-box wrapping key and the reboot cost, and the cohort does not need it yet.

**Full-disk encryption of the droplet's root (LUKS at boot).** Rejected: the same reboot-waits-for-a-human problem as an off-box fscrypt key, for the whole box instead of one tree, and DO does not offer it for droplet root disks (#114's cited source) — it would be a rebuild.

**Application-level encryption with a server-held master key.** Rejected: root reads the key; it defends against nothing Tier 1b does not, and it adds a crypto dependency and a key ceremony for no new person defended.

**Client-side encryption in the MCP connector.** Rejected: the claude.ai connector has no place to hold a key (#114), and a server that cannot read cannot search — which is the whole product.

**Do nothing; rely on 0700 and the honest sentence.** Rejected for launch because the backup bundles are about to leave the box (#270) and a plaintext copy of every founder's memory in a bucket is the one outcome #114 named as worse than no backup.

## References

- boonyard #113, #114 (the map), #116, #118 §2, #120; umbrella #270 (rung 4), #319, #333 (countersign mandatory), #339/#353 (backups closed, encryption owed), #351, #352
- ADR-0005 (deletion is a key or a retention clock, never a row), ADR-0006 (self-host = zero-knowledge, free), ADR-0007 (teardown = `rm`; backups per tier), ADR-0008 (keys sha256 at rest)
- architecture/05_multi_tenancy.md (account deletion, privacy section)
- DigitalOcean: Volumes encryption and snapshot behaviour — the pages #114 cited; the droplet-backup-includes-Volumes question is to be read there before the order
- `Umbrella/DESIGN_HANDOFF_SOFT_LAUNCH_20260907.md` §3 ADR-B
