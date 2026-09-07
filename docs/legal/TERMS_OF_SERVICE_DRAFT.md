# boonyard.com — Terms of Service (DRAFT)

> **DRAFT 2026-09-07, design seat (Conductor, Cowork). Not legal advice; nothing here has been reviewed by a lawyer.** Written in plain English from the product's own canon (ADR-0005/0006/0007, arch 05/07, ADR-0011/0012 drafts) so that every sentence maps to something the service actually does. Square brackets mark what must be filled or verified before this is served. Professor blesses it or a lawyer replaces it; the Code seat wires it at `/app/terms` only after that.
>
> **Blessed by: Professor, 2026-09-07** — *"You can do the legal-ese for now. Blessed."* (umbrella wall, the decision entry threaded to #360). The rulings of ADR-0011 are filled in below. **Brackets that remain are measurement items for the Code seat** (a link, a retention number, a venue line), not wording that waits on a blessing — fill each from the running system, never from memory, before `/app/terms` is served.

Effective: [date]. These terms are between you and **Mindstorm Unlimited LLC**, a Florida limited liability company ("we", "us"), for the hosted service at boonyard.com and mcp.boonyard.com (the "Service"). The open-source `boonyard` package is separate: it is licensed under Apache 2.0 and these terms do not apply to running it yourself.

## 1. The short version

You own what you write. We host it, back it up, and serve it to your agents. We do not read it except to answer your own requests, and we say so plainly in the Privacy Policy. You can export everything, at any time, for free, as an ordinary SQLite file. Entries are append-only by design — they cannot be edited or deleted one at a time. If you leave, your data leaves with you.

## 2. Your account

- You must be 18 or older and able to enter a contract.
- One person per account. Keep your sign-in credentials and API keys to yourself; anything done with a valid key is done by you, so revoke a key the moment you think it has leaked (the dashboard does it instantly).
- You give us a working email address. We use it to sign you in, to verify you, and to tell you about your account — nothing else (Privacy Policy §5).

## 3. Your nodes and your entries

- **You own your content.** Everything you or your agents write into a node is yours. We claim no rights in it beyond what is needed to store it and serve it back to you.
- **Append-only.** The Service is built so that an entry, once written, is not edited or deleted individually — by you, by us, or by anyone. Corrections are new entries threaded to the old. This is a feature of the product, not a limitation we are working on. [If a personal detail is logged by mistake and must be removed, write to hello@boonyard.com; we will handle it by hand, and we will tell you exactly what was changed.]
- **You can delete a whole node**, and **you can close your account**; both remove your files from our systems on the schedule in Privacy Policy §7.
- **Export is always free**, on every plan, in every account state, including a suspended one.

## 4. Acceptable use

Do not use the Service to store or distribute content that is illegal where you or we are, to command or control malware, to attack the Service or anyone else, or to harass. Do not try to read another account's data or circumvent limits. We may scan for known-malicious payloads for operational protection only (Privacy Policy §4); we do not otherwise inspect content. If an account is abusive we may suspend it; you can still export.

## 5. Plans, limits, and founders

- **Free** accounts get the limits published at [link to the limits page]: today 3 nodes, 10,000 entries per node, and rate limits on API keys. When a limit is reached, new writes are refused; nothing you already wrote is ever deleted to make room.
- **Founders.** The first twenty verified accounts are founders: a year of the paid plan's limits at no charge, no card required, from the date of verification, and **half price on the paid plan for as long as you stay subscribed after that**. The founder number on your account is permanent.
- **Pro** is a paid plan with higher limits: **$8 a month or $80 a year** at launch. The checkout page is authoritative for the current price; there are no hidden fees.

## 6. Payment (applies only once billing exists)

- Payments are handled by Stripe. We never see or store your card.
- Subscriptions renew until you cancel from the billing page; cancellation takes effect at the end of the current period.
- **Refunds:** the first charge on any subscription is refundable in full on request within 14 days, no questions asked; after that, cancellation takes effect at the end of the period you paid for and partial periods are not refunded.
- If a payment fails, your paid limits continue for 7 days while Stripe retries; after that your account moves to Free limits. Nothing is deleted.
- Moving from Pro to Free never deletes anything. If you are over Free limits, writes pause until you upgrade, export, or delete a node yourself. After 30 days over-limit with no action, the account is suspended — no writes, no API — until resolved; export still works.

## 7. Availability

This is a small service run by a small company, during a soft launch. We work to keep it up and we back it up every night, but we make **no uptime guarantee** on Free or founder accounts, and [no service-level agreement on Pro until one is published]. We will announce planned downtime by email or on boonyard.com when we can.

## 8. Ending things

- **You** can close your account at any time from the dashboard [or by email until the dashboard has the button]. Export first; the schedule for removal is in Privacy Policy §7.
- **We** can suspend or close an account for breach of §4, for non-payment under §6, or if we shut the Service down — in which case we will give at least 30 days' notice and keep export working through the notice period.

## 9. Warranties and liability

The Service is provided **"as is."** To the extent the law allows, we disclaim implied warranties, and our total liability to you for anything arising from the Service is limited to the amount you paid us in the twelve months before the claim (which, on a Free or founder account, is zero). We are not liable for indirect or consequential loss. Nothing here limits liability that cannot be limited by law.

## 10. Changes

We may change these terms. If a change matters, we will email you at least 14 days before it takes effect; continuing to use the Service after that is acceptance. The current version is always at boonyard.com/app/terms with its effective date.

## 11. Law and contact

These terms are governed by the laws of the State of Florida, USA, and any dispute is brought in the state or federal courts located in Florida [county — Professor or a lawyer, if a narrower venue is wanted]. Questions: hello@boonyard.com. Security reports: security@boonyard.com.
