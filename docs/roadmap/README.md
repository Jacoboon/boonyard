# Roadmap

The phasing of the build. Each phase has a clear goal, a list of deliverables, acceptance criteria, and an explicit non-goal list.

## Phases

| # | Title | Goal | Status |
|---|---|---|---|
| [0](PHASE_0.md) | Canon, conventions, landing | Lock the design canon; register the domain; splice the v1.2 conventions into existing projects | in progress (this repo *is* most of it) |
| [1](PHASE_1.md) | Package extraction + dogfood | Lift the substrate into the standalone boonyard package; migrate PlaneScape and JRHood onto it | pending Phase 0 |
| [2](PHASE_2.md) | SaaS MVP for user zero | boonyardnn.com goes live for Jacob only; validate the SaaS deployment shape end-to-end | pending Phase 1 |
| [3](PHASE_3.md) | Public open + billing + teams | Open to public signups; Stripe billing; team-shared nodes; documentation polish; marketing pass | pending Phase 2 |

## Phase gating

Phases are sequential, not parallel. Each phase's acceptance criteria gate the next phase's start. CHARTER's dogfood pact is the meta-gate: every phase must produce *evidence* that the substrate compounds value for user zero (Jacob) before the next phase proceeds.

If a phase produces ambiguous or negative dogfood evidence, the protocol is:

1. Pause; do not proceed to the next phase.
2. Log a `discussion` entry in the live NN naming the issue.
3. Decide via `decision` entry: a Phase N.5 refinement, a reversal to a prior phase, or an indefinite hold.
4. Resume only when the evidence is solid.

## Future phases (uncommitted)

Phase 4+ is deliberately undefined. The substrate is meant to be stable on the scale of years (CHARTER); successive phases should add *less*, not more. Candidate directions, none committed:

- Webhooks (Phase 3.5 if not in Phase 3 itself).
- Team marketplace for shared schema profiles.
- Optional embeddings install (`pip install boonyard[semantic]`).
- Enterprise SSO.
- Hosted Umbrella as a product (the meta-cognitive layer; see live NN entry 75).
- Integration packs (Slack, Discord, Notion as MCP-on-top consumers).

The right next move depends on what the substrate's actual users tell us. The roadmap evolves through `decision` entries logged in the live NN.

## Related

- [CHARTER](../../CHARTER.md) — the dogfood pact; the Project-Six guardrail
- [ADRs](../adr/) — the locked design decisions
- [Architecture](../architecture/) — the deep-dives the roadmap brings into existence
- [Glossary](../glossary.md) — locked vocabulary
