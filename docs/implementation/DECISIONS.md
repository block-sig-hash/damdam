# External decision register — D1–D6

Opened by [chunk 01](chunks/01-scope-and-specifications.md) on 8 September 2026.
This is the repository's authoritative record for the six external gates named
in [IMPLEMENTATION-PLAN.md](IMPLEMENTATION-PLAN.md) §5.

**All six start OPEN.** Nothing here is closed by a passing test, a mock, a
vendor marketing page or a prior conversation. A decision closes only when this
file records the owner, the decision, the supporting artifact and its date.

Two rules apply to every row:

- **A proposed default is not an approval.** Where the plan proposes a default,
  it is recorded below as *proposed*, attributed to the plan, and it stays
  proposed until the named owner records a decision here. Chunk 01 did not
  obtain founder approval for anything and does not claim to have.
- **A gate blocks acceptance of dependent scope, not all progress.** Claude
  finishes the independent preparatory work, names the exact missing input, and
  leaves the remainder explicitly open. Codex may accept a named preparatory
  subchunk while the gate stays open.

## Register

### D1 — Telnyx carrier capability and commercial terms

| Field | Value |
|---|---|
| Status | **OPEN** |
| Owner | Founder + Telnyx commercial/technical team |
| Blocks | Live carrier implementation acceptance; saleable catalog; any public coverage claim |
| Chunks gated | 03 (feasibility), 15 (line lifecycle), 16 (usage/charging), 17 (controls), 29 (physical pilot) |
| Chunks that may still progress | 05, 09, 10, 11 with generic contracts, fixtures and recovery logic |

Required evidence, all in writing from Telnyx:

1. Consumer-handset and resale eligibility for the branded eSIM product.
2. Whether the *same* eSIM profile carries data and native-dialer voice
   (incoming and outgoing) in each proposed market.
3. VoLTE access terms while the product is documented as **beta** — production
   support commitment, API stability and support SLA.
4. A capability matrix by profile/IMSI, visited network, device and service.
   The "650+ networks / 180+ countries" figure is a data claim and is not
   evidence for voice, inbound calls, local numbers or permanent roaming.
5. Assigned-number countries, first-activation requirements and voice-roaming
   requirements.
6. All-in rates for calls to Nigeria: mobile and landline, connection fees,
   billing increments, inbound charges, roaming, minimum commitments, taxes.
7. How caps, usage records and corrections are exposed, and whether hard
   spending enforcement works supplier-side while the app is closed.
8. A test account and rate deck.

Recorded so far: the documentation review dated 8 September 2026 in
[IMPLEMENTATION-PLAN.md](IMPLEMENTATION-PLAN.md) §5. That is a reading of public
documentation, not commercial confirmation, and it does not move D1.

**Explicitly not assumed:** that Telnyx can present a third-party verified +234
caller ID on the cellular line. External CLI is deferred (see D2) and is not a
launch disqualifier.

### D2 — Market, coverage, device and number policy

| Field | Value |
|---|---|
| Status | **OPEN** |
| Owner | Founder / product |
| Blocks | Public claims, launch eligibility rules, catalog contents |
| Chunks gated | 09 (catalog), 19 (plans UI), 20 (installation guidance) |
| Chunks that may still progress | Eligibility engine and a clearly test-only catalog |

Required decisions, keeping the four kinds of coverage distinct: selling
markets (where a customer may buy), visited countries (where the eSIM works),
calling destinations (who can be called), and supported devices.

**Proposed default recorded in the plan, not approved:** a new carrier-assigned
number is the launch identity, with **no promise of +234 retention or porting**.
External verified caller ID and app/browser VoIP are deferred. This is the
plan's proposal; the founder owns confirming it before any plan is published.

### D3 — Legal seller entity

| Field | Value |
|---|---|
| Status | **OPEN** |
| Owner | Founder + cross-border tax/legal advisers |
| Blocks | Merchant onboarding, seller identity on receipts, tax configuration |
| Chunks gated | 12, 13, 14 for live mode; 30 for launch disclosures |
| Chunks that may still progress | A configurable seller/money model with no hardcoded structure |

US LLC (Atlas), UK operating company and Isle of Man were all evaluated and
**none was selected**. Nigerian treatment must be assessed alongside. The
existing UAE-parent recommendation in `docs/corporate-structure.md` is a prior
recommendation, not a decision, and the product reset does not confirm it.

`data-model.md`, `api-spec.md` and receipts must carry the selling legal entity
as data. No chunk may hardcode an entity or a tax treatment.

### D4 — Payment processors and merchant approval

| Field | Value |
|---|---|
| Status | **OPEN** |
| Owner | Founder + payment providers |
| Blocks | Live payments of any kind |
| Chunks gated | 12, 13, 14 for live mode; 24 for enterprise funding |
| Chunks that may still progress | Payment abstractions plus a selected provider's sandbox |

Required in writing: telecom-category approval, merchant and settlement
eligibility for the D3 entity, fees, FX, reserve terms, refund and dispute
handling, and renewal support if subscriptions are ever promoted into scope.

Paystack is retained **conditionally** for approved local NGN business through a
matching merchant entity. The global processor is undecided; Stripe is a
candidate only. **Stripe-specific code requires a recorded selection here
first** — a generic payment boundary does not.

### D5 — Charging, refund and funding policy

| Field | Value |
|---|---|
| Status | **OPEN** |
| Owner | Founder / product + finance |
| Blocks | Final checkout and billing behavior, published plan terms |
| Chunks gated | 13, 14, 16, 17, 24 |
| Chunks that may still progress | Prepaid mechanics recorded as proposed, with no pricing guarantee |

**Proposed default recorded in the plan, not approved:** prepaid plans and
top-ups for consumers, and prepaid organization service balances for
enterprises. Recurring subscriptions are separately gated; the data model
should be able to support them without shipping them.

Also open: SKU margins, refund policy, enterprise funding/credit policy, and
whether the promised hard spending cap is achievable given D1's answer on
supplier-side enforcement. If it is not, the offered contract changes before
launch — an app-side balance computed from delayed usage records must not be
presented as a guaranteed hard cap.

### D6 — Release, hosting and device access

| Field | Value |
|---|---|
| Status | **OPEN** |
| Owner | Founder + release owner |
| Blocks | Signed staging builds, store submission, production release |
| Chunks gated | 26, 27, 29, 30 |
| Chunks that may still progress | Automation, local checks and written procedures |

Required: Apple and Google developer account access, signing material, domains,
hosting, secrets ownership, support ownership, and physical test devices for the
supported matrix. No fabricated signed-build, device or live-payment result may
be recorded anywhere in this repository.

## Product defaults and existing decisions

Family contacts and offline SOS removal are already authorized by the user
(plan §1); do not ask for that approval again. The four defaults below remain
proposals, not founder approvals. Use them for reversible preparatory work while
recording unresolved choices; do not invent approval for irreversible removal or
public service promises. Record any subsequent session decision here.

| Proposed default | Source | Owner | Consequence if reversed |
|---|---|---|---|
| Remove the remaining check-in / welfare workflow | Plan §1, "recommended scope interpretation" | Founder / product | Chunk 04 retirement scope changes; enterprise dashboard scope changes |
| Email-based account identity and recovery, independent of SMS | Plan §1 | Founder / product | Chunk 06 identity model changes |
| A new carrier-assigned number, no +234 retention promise | Plan §1, D2 | Founder / product | Chunk 15 number lifecycle and all plan copy change |
| Prepaid charging; recurring billing separately gated | Plan §1, D5 | Founder / product + finance | Chunks 13, 16, 17, 24 change materially |

Chunk 01 records these as proposed defaults exactly as the plan does. It did not
invent founder approval for any of them.

The welfare and identity defaults are product choices, not hidden additions to
D2's carrier-market gate. The assigned-number policy is under D2 and charging
is under D5. Each affected chunk must name its remaining choice explicitly.

## Recording a decision

Append a dated entry under the relevant gate:

```
#### Decision — <YYYY-MM-DD>
- Decided by: <name/role>
- Decision: <what was decided>
- Evidence: <contract, email, dashboard export, dated document>
- Chunks unblocked: <list>
- Chunks still blocked and why: <list>
```

Then update [STATUS.md](STATUS.md) for every chunk whose gate changed. Do not
delete a superseded decision; append the replacement.
