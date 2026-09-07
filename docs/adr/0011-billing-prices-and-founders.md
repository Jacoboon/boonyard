# ADR 0011 — Billing, prices, and the founder→paid transition

**Status:** ACCEPTED 2026-09-07 — Professor's rulings, verbatim on the umbrella wall (the decision entry threaded to #360): *"Those prices are reasonable to me 8/80"* · *"Agreed — Founders get half-off after the first year"* · *"teams can wait"* · *"I agree with your proposed refund policy."* Drafted the same day as PROPOSED; the recommendations below are now the decisions, and the tables say so.
**Date:** 2026-09-07
**Deciders:** Jacob (Professor); drafted by the Conductor (Cowork, model:claude-fable-5-1) from the design handoff `Umbrella/DESIGN_HANDOFF_SOFT_LAUNCH_20260907.md` (umbrella #351)
**Supersedes:** —
**Superseded by:** —

## Context

boonyard.com is live and accepting signups (umbrella #348, boonyard #116). The first twenty verified accounts become founders automatically — `plan=founder`, `founder_until` = +365 days (boonyard #113: *"The first 20 — Show a live number on the site"*; #109: *"THEY GET FREE OR DISCOUNTED SERVICE FOR A YEAR"*). Seat 21 lands on Free automatically (boonyard #118 §3). Nothing is billed; nothing can be. Professor's word: *"Stripe can wait (for now)"* (umbrella #351) — so this ADR settles the **shape** of billing so that seat 21 has somewhere to go and day 366 has an answer, while the Stripe integration itself stays parked until he says otherwise.

What the canon already fixes, and this ADR does not reopen:

- **Never paywall an algorithm** (ADR-0006). Pro gets *more of what Free has* — nodes, entries, rate, retention — plus the hosted aggregator and support. Never a tool Free lacks.
- **Export is always free**, on every tier, in every account state including suspended (ADR-0006; arch 07 anti-features).
- **No data loss on downgrade** (ADR-0005; arch 07 upgrade/downgrade). Writes block; data stays; the user exports or upgrades.
- **The matrix** — Free 3 nodes / 10k entries per node / 30 writes-per-minute per key / 30-day retention; Pro unlimited nodes / unlimited (soft) entries / 600 writes-per-minute / 1-year retention / hosted aggregator (arch 07; ADR-0007; ADR-0008). Limits exist; prices do not. That gap is this ADR.
- **Stripe** as the billing provider; a Stripe Customer per user; Subscription for Pro; Checkout for upgrade; Customer Portal for cancel/card changes; webhook flips `plan`; nightly reconciliation (PHASE_3 §2; boonyard #118 §4). Instruments never touch us; `users.db` holds only Stripe ids (ADR-0007).

What is true in the code today (boonyard #116, #120), and this ADR builds on rather than redesigns: `account.plan ∈ {free, founder, owner}`; `founder_no`, `founder_until`; node cap 3 on Free, none on founder/owner; the Free 10k-entry cap and ADR-0008's rate table enforced in the router; the account's plan mirrored into the registry; columns `stripe_customer_id`, `stripe_subscription_id`, `plan_until` reserved and empty.

One more input from another project on this stack, because it is the same bug waiting to happen: JR Hood's fee rule (jrhood #174) — **the rate a client pays was agreed once, in a document they signed; software reads it, software never re-derives it**, and one module is the only authority. Six readers consulted the wrong row there and it only stayed hidden because the default happened to match. This ADR gives billing the same shape from day one: one entitlement function, one authority.

## Decision

### 1. Plans and entitlements are two different things

`plan` is what the account *is*; the **entitlement** is what the account *gets right now*. One function resolves the second from the first, and every reader — router, web, rate limiter, registry mirror, dashboard — calls it. Nothing else computes a tier.

```
effective_tier(account, now) -> "free" | "pro"
    owner                                   -> pro   (user zero; never billed)
    founder  and now <  founder_until       -> pro
    founder  and now >= founder_until       -> pro if a live subscription, else free
    free/pro and plan_until is not None
             and now <  plan_until          -> pro
    otherwise                               -> free
```

`plan` keeps its current values and gains one: `{free, pro, founder, owner}`. `founder` is never overwritten by a subscription — a founder who subscribes on day 366 stays `plan=founder` with a live `stripe_subscription_id`; the badge is identity, the subscription is entitlement. `founder_no` is permanent.

The two tiers the product actually sells are **Free** and **Pro**. "Founder" is a status that yields Pro entitlement for a year and a price after it; it is not a third tier and never gets its own limits row.

### 2. Prices — the recommendation, and the choice that is his

Nobody but Professor sets a price. The ADR's job is to make the choice concrete.

Facts that bound it: the box is DigitalOcean's 1 vCPU / 961 MB droplet (boonyard #118) — the whole service costs single digits of dollars a month today; per arch 07 a Free user costs approximately nothing and a Pro user is bounded (storage, backups, requests) with support the real floor. The CHARTER's dogfood pact says revenue is a free option earned by adoption, not a goal pursued by gating. No market survey was done for this draft — `NN: searched "competitor OR pricing survey" — no hit` on either wall — and if he wants one before ruling, it is one search, not a sitting.

| Option | Monthly | Annual | Reads as | Cost |
|---|---|---|---|---|
| A — the floor | $5 | $50 | "a coffee"; a one-click yes | Hard to raise later; leaves no room under a Team price |
| **B — recommended** | **$8** | **$80** (two months free) | indie-infra standard; still a one-click yes for the Discord crowd | Room for Team at ~$15–20/seat later |
| C — the signal | $15 | $150 | "infrastructure, not a toy"; filters hobbyists | The SkyeNet cohort is hobbyists on purpose; twenty founders converting at $15 is a smaller number than twenty at $8 |

**DECIDED: B — $8 / month, $80 / year** (Professor, 2026-09-07). One Pro price, monthly and annual, no other SKU at launch. The annual option exists so the founders' offer can be stated as a number ("a year of Pro — $80 — free") and so the day-366 conversion has a one-payment path.

### 3. The founders' offer: free, then a founders' rate — the recommendation

Professor's phrase is *"free OR discounted … for a year."* The Code seat's observation stands: both are the same code — a founder has **no Stripe object for the year**; at `founder_until` a prompt to subscribe appears; "discounted" is a Stripe coupon applied at that moment. So the choice is not technical. It is what the word "founder" means after year one.

| Option | Year 1 | Day 366+ | Cost to the LLC at 20 founders | What it says |
|---|---|---|---|---|
| 1 — a year free, then full price | free | Pro at list | $0 | "thanks for testing" |
| 2 — a year free, then a **founders' rate for life** (50% off Pro) | free | $4/mo or $40/yr, forever, while they stay subscribed | at most $80/mo of foregone revenue if all twenty convert | "you were here first and it never expires" |
| 3 — a year free, then list price locked forever | free | $8 forever even if Pro rises | $0 now; unknowable later | the same promise as 2, weaker |

**DECIDED: 2 — a year free, then 50% off Pro for life** (Professor, 2026-09-07: *"Founders get half-off after the first year"*). Twenty people at half price is the cheapest loyalty the company will ever buy, and it keeps "founder" honest as a permanent thing rather than a trial period with a nicer name. Implementation is one Stripe coupon (`FOUNDER50`, forever-duration, restricted to customers whose account carries a `founder_no`) attached at Checkout — no code path beyond "is this a founder."

### 4. Day 366, exactly

For a founder with no live subscription at `founder_until`:

1. **T−30 and T−7 days:** one email each, from hello@boonyard.com, stating the date, what changes, the founders' rate, and that export is free either way. Two mails, not a drip.
2. **T+0:** `effective_tier` returns `free`. Free limits apply on the next request: node cap 3, 10k entries, Free rate. If the account is over a Free limit, **writes are refused with the `quota_exceeded` body the router already sends; reads, export and key management keep working; nothing is deleted** (ADR-0005; arch 07). The dashboard shows the same two doors it shows any over-limit Free account: subscribe, or export-and-delete a node.
3. **T+30 days over-limit without action:** arch 07's suspension rule — no writes, no API, no data loss — until resolved. Export still works.
4. `founder_no` and the founder badge never go away.

There is no separate grace tier for founders; the Free rules are the grace, and they are kind by design (the data is never at risk).

### 5. Free → Pro, Pro → Free, and failed payments (arch 07 and PHASE_3 §2, made concrete)

- **Upgrade:** Checkout → `checkout.session.completed` → `plan_until` = current period end, `stripe_*` ids stored → entitlement is Pro on the next request. No migration; the files do not move.
- **Renewal:** `invoice.paid` extends `plan_until`. **Cancellation:** Customer Portal; `customer.subscription.updated` (cancel_at_period_end) leaves `plan_until` at period end; `customer.subscription.deleted` ends it. Downgrade lands at the boundary, never mid-cycle.
- **Failed payment:** PHASE_3's 7-day grace — `plan_until` is not shortened for 7 days after `invoice.payment_failed`; Stripe's own dunning mails run; at day 7 with no `invoice.paid`, `plan_until` = now → Free rules.
- **Reconciliation:** nightly, list active subscriptions from Stripe and compare to `users.db`; disagreements are logged and corrected toward Stripe, never toward local state (Stripe is the ledger; we are the mirror). Idempotent webhook handler keyed on Stripe event id.

### 6. Refunds — DECIDED

PHASE_3 §2 says *pro-rata refunds for mid-cycle downgrades*. That is a code path, a support path, and a Terms clause, for a product with one $8 SKU. **DECIDED (Professor, 2026-09-07): the simpler rule replaces it** — a full refund of any *first* charge on request within 14 days, no questions; after that, cancellation takes effect at period end and partial periods are not refunded. Stripe's Portal does exactly this with no code. Written into the Terms (docs/legal draft) as "14 days on your first charge."

### 7. Team at launch — DECIDED: no (*"teams can wait"*)

Team (PHASE_3 §3) needs node grants, the `~team` URL prefix, per-seat billing and an ACL model that does not exist. Nothing in the founders cohort or the soft launch needs it. Pro only. The word "Team" stays off the pricing page until it is real — arch 07's "no feature that isn't built" spirit.

### 8. What the Code seat builds, and when

Everything here is now buildable. The integration itself stays parked by Professor's word — *"Stripe can wait (for now)"* (umbrella #351) — until he opens a Stripe account under the LLC and says go; the day keys exist, the seat builds in **test mode** first. Price, coupon and refund window are read from config (`PRO_PRICE_ID_MONTHLY`, `PRO_PRICE_ID_ANNUAL`, `FOUNDER_COUPON_ID`, `REFUND_WINDOW_DAYS`), never from a constant, so a future change is a config edit and not a deploy. The entitlement function (§1) and the registry mirror carrying the *effective* tier can land before any Stripe key exists.

### Decisions — ruled 2026-09-07

| # | Choice | Decision |
|---|---|---|
| 1 | Pro price, monthly / annual | **$8 / $80** |
| 2 | Founders after year one | **free year, then 50% off Pro for life** (one Stripe coupon) |
| 3 | Team at launch | **no — Pro only** |
| 4 | Refund rule | **14-day full refund on the first charge; then cancel-at-period-end, no pro-rata** |
| 5 | Sales tax / VAT | still open — a Stripe Tax toggle; whether Mindstorm must collect is the tax people's question (umbrella #322), asked before the first live charge |

## Consequences

**Positive:** one entitlement function means the router, the web, the rate limiter and the dashboard can never disagree about a tier — the JR Hood lesson applied before the first dollar. Founders cost nothing in code. Day 366 is a documented, non-destructive event. The price is a config value; Professor changes it without a deploy.

**Negative:** a single SKU leaves money on the table for heavy users (arch 07 accepts this: the Pro soft caps surface the "talk to us" conversation). A lifetime founders' rate is a promise that has to be honoured through every future price change — that is the point, and it is twenty people.

**Neutral:** `plan=founder` past `founder_until` with no subscription is a legitimate, expected state; readers must never treat it as an error. The registry mirror (`User.plan`) should mirror the **effective tier**, not the raw plan, or the router will read `founder` and have to know the date rule too — one authority means the mirror carries the answer, not the question.

## Alternatives considered

**Usage-based pricing (per entry, per request).** Rejected: it prices the thing the substrate exists to encourage — writing — and turns a runaway agent loop into a bill. Rate limits already bound the load; flat Pro is the honest shape for a memory product.

**A "founder" tier with its own limits row.** Rejected: a third row in the matrix to maintain forever, for twenty accounts, when Pro-for-a-year expresses the same thing with a date.

**Discounted-not-free year one (e.g. $2/mo).** Rejected: it forces Stripe, Terms and a card before seat 21 exists — the opposite of "Stripe can wait" — for revenue that rounds to zero.

**Pro-rata refunds (PHASE_3 §2 as written).** Rejected in favour of §6; kept here as the canon's original line so the reversal is visible.

**Grandfathering founders at Pro forever, free.** Rejected: "free forever" for the first twenty makes every later user a second class, and it makes the founders' data the one cohort the company has no reason to keep serving. A rate they pay is a relationship; a gift that never ends is a liability.

## References

- ADR-0005 (no data loss), ADR-0006 (never paywall an algorithm; export free), ADR-0007 (billing refs in `users.db`), ADR-0008 (rate table)
- architecture/07_freemium.md (the matrix; upgrade/downgrade rules; anti-features)
- roadmap/PHASE_3.md §2 (Stripe mechanics; 7-day grace; the pro-rata line this ADR replaces)
- Walls: boonyard #109, #113, #116, #118 §4, #120; umbrella #338, #347, #348, #350, #351; jrhood #174 (one authority for a price)
- `Umbrella/DESIGN_HANDOFF_SOFT_LAUNCH_20260907.md` §3 ADR-A
