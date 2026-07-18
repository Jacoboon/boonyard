# Phase 0 — Canon, Conventions, Landing

> Zero code in the package. The substrate is already designed; this phase produces the artifacts the design needs to exist alongside.

## Goal

Lock the canon and make BoonyardNN exist as a *thing* (not just a vibe). A repo with the design canon. A domain name. A landing page. The CLAUDE.md splices into the existing PlaneScape and JRHood projects so they adopt the v1.2 §2 conventions (skill template, tag-ritual additions) even before the package itself is extracted.

This is the phase before any package code is written. It deliberately produces no code in `package/boonyard/` — just docs, markdown, and infra.

## Why Phase 0 has no package code

Per CHARTER ("dogfood pact"), every BoonyardNN milestone is paired with the question "what project of mine got better because this exists?" In Phase 0, the answer is: the *design canon* improves Jacob's other projects via the convention splices, and the *repo + landing page* establishes BoonyardNN as a real referenceable thing — both of which deliver value without needing the package extracted yet.

The deeper reason: extracting code under-designed is worse than extracting code over-designed. The v1.2 reframe spent real effort getting the scope-model question right (Option A vs B). Phase 0 finishes that pattern — every load-bearing decision is in an ADR before code lands.

## Deliverables

### 1. The repo exists

- [x] `C:\Users\Jacob\Code\BoonyardNN\` initialized with the directory structure (`docs/architecture/`, `docs/adr/`, `docs/roadmap/`, `package/boonyard/` placeholder).
- [x] CHARTER.md written.
- [x] glossary.md written.
- [x] 10 ADRs written (0001–0010, all in Accepted status).
- [x] 9 architecture docs written (00–08).
- [x] 4 roadmap docs written (PHASE_0 through PHASE_3) — including this one.
- [x] CLAUDE.md written (Code's execution canon).
- [x] README.md written (the front door).

(The Phase 0 design work *is* this entire file tree. The deliverables for Phase 0 are exactly the files in this repo at the close of the session that produced them.)

### 2. The domain exists

- [ ] `boonyardnn.com` registered (Porkbun / Cloudflare Registrar).
- [ ] DNS pointing at a placeholder static page (a Cloudflare Pages deployment, or Netlify, or even GitHub Pages).
- [ ] HTTPS via Cloudflare's free certificate.

If `boonyardnn.com` is taken, fall back to `boonyard.nn`, `boonyard.dev`, `boonyard.org`, or `getboonyard.com` — final pick is a Phase 0 call by Jacob.

### 3. The landing page exists

A minimal, honest landing page at `boonyardnn.com`. Sections:

- **Hero:** "BoonyardNN — append-only shared memory substrate for multi-agent collaboration." Short tagline. One paragraph.
- **What it is:** the three modes in one paragraph each. Per-project, in-project, over-many.
- **What it isn't:** the anti-goals from CHARTER, briefly.
- **Status:** "Pre-Phase-1. The substrate is designed; the package extraction is next. [GitHub link]" — set honest expectations.
- **Newsletter signup:** "Tell me when it's ready" (single-field email collection; the SaaS doesn't yet exist).
- **Footer:** GitHub repo link, RSS feed of dispatch log entries (eventually), email contact.

No marketing fluff. No "Trusted by" logos. No fake testimonials. The landing page should read like the CHARTER condensed to 600 words.

### 4. Convention splices into existing projects

> **DEFERRED — 2026-07-16, Professor's call (live NN entry 89).** The existing NNs are left alone; they get retrofitted at Phase 1 migration time (PHASE_1.md deliverables 3, 4, 8 already cover the doc updates as part of migration), with Umbrella handling cross-project housekeeping thereafter. This deliverable is no longer a Phase 0 completion criterion.

The v1.2 §2 Phase 0 conventions (the CLAUDE.md block for the Skills section + Tag selection ritual) get spliced into:

- [ ] `PlaneScape/CLAUDE.md` — already has v1.2 §2 ready; needs Cowork-Opus to apply.
- [ ] `JRHood/NN.md` — augment with the canonical tag discipline (ADR-0009) and skill conventions (ADR-0004). Don't touch JRHood's free-form-tagging culture; add the menu-pull-before-write step as a recommendation.
- [ ] `Spore/CLAUDE.md` (if exists) — apply the same v1.2 §2 block.

These splices land in the existing project repos via the projects' own Code/Cowork agents — they are documentation changes, not BoonyardNN code changes.

### 5. The live NN gets a Phase 0 marker entry

Log a `decision` entry in the live NN (nn.vectorscape.uk/sse):

```
agent: opus  (or whichever Opus seat actually writes this)
entry_type: decision
tags: decision,boonyard,charter-revision,phase-0
content: BoonyardNN Phase 0 complete. Repo exists at C:\Users\Jacob\Code\BoonyardNN with CHARTER, glossary, 10 ADRs, 9 architecture docs, 4 roadmap docs, CLAUDE.md, README. Domain boonyardnn.com [registered / pending]. Landing page [live at URL / pending]. Phase 1 (package extraction + dogfood) is gated on Jacob's review of the canon.
```

This is the entry future seats will find when querying "what's the latest on BoonyardNN" — it points at the repo and signals readiness for Phase 1.

### 6. Code is briefed

A handoff document is prepared for the future Claude Code instance (or other implementing agent) that will execute Phase 1. This is the `CLAUDE.md` in this repo plus a Phase 1 execution brief committed under `docs/roadmap/PHASE_1_brief_for_code.md` (drafted at the start of Phase 1, not in Phase 0).

## Acceptance criteria

Phase 0 is complete when:

1. The repo at `C:\Users\Jacob\Code\BoonyardNN\` has the full canon as listed above (already satisfied; Phase 0's primary work product).
2. `boonyardnn.com` (or the chosen domain) resolves to a landing page that accurately reflects the canon.
3. ~~The PlaneScape / JRHood (and Spore, if applicable) CLAUDE.md / NN.md splices are landed.~~ *(Deferred 2026-07-16 per live NN entry 89 — retrofit happens at Phase 1 migration.)*
4. The live NN has a Phase 0 completion marker entry.
5. Jacob has read the CHARTER and at minimum ADRs 0001, 0002, 0003, 0006 — the load-bearing decisions — and approves proceeding to Phase 1, or has logged objections via `discussion` entries in the live NN.

## What Phase 0 does NOT include

- No `boonyard` Python package code (deferred to Phase 1).
- No SaaS infrastructure (deferred to Phase 2).
- No migrations of existing NNs (deferred to Phase 1, when the package can perform them).
- No billing (Phase 3).
- No public sign-ups (Phase 3).

## Estimated effort

Mostly already done (the canon authoring is the bulk of the work). Remaining: ~half a day for the domain + landing page + splices + marker entry.

## Risks

- **Bikeshedding the domain.** If `boonyardnn.com` is taken, the search for an alternate name could absorb hours. Mitigation: pick from the fallback list, defer "perfect name" to Phase 3 marketing pass.
- **Splice drift.** If the v1.2 §2 conventions land in PlaneScape but not JRHood (or vice versa), the substrate's dogfood story is uneven. Mitigation: log a `decision` entry tracking which projects have been spliced, treat as Phase 0 completion criterion.
- **"Just one more ADR."** The canon is meant to be load-bearing-stable. Adding a tenth ADR is a Phase 0 fix; adding an eleventh starts to smell like Phase 0 has become its own project. Apply Project-Six guardrail.

## Then what

When Phase 0 is complete (canon locked, domain live, splices landed): Phase 1 — extract the package and dogfood on PlaneScape + JRHood.
