# Telnyx go/no-go by proposed market — 8 September 2026

Produced by [chunk 03](../chunks/03-telnyx-feasibility.md) (US-35). Based on the
[capability matrix](CAPABILITY-MATRIX.md) and [API contracts](API-CONTRACTS.md),
both from documentation review only.

**No market is cleared for sale.** Every row below is **NO-GO for now**, and
that is a statement about missing evidence, not about Telnyx. D1 and D2 are both
OPEN; nothing in this chunk could close them, and a documentation review is
structurally incapable of closing them.

## Decision rule

A market may move to GO only when all of the following are recorded in
[`../DECISIONS.md`](../DECISIONS.md) with a date and an artifact:

| # | Condition | Gate |
|---|---|---|
| 1 | Written confirmation that one eSIM carries data **and** native voice in that market | D1 |
| 2 | Voice coverage confirmed for that market by visited network and IMSI profile, inbound and outbound stated separately | D1 |
| 3 | Assigned-number availability and its regulatory requirements confirmed | D1/D2 |
| 4 | Permanent-roaming position confirmed for that market | D1 |
| 5 | Complete call cost to Nigeria from that market, including increments and fees | D1/D5 |
| 6 | Supplier-side spending enforcement adequate for the prepaid promise, **including voice** | D1/D5 |
| 7 | VoLTE production-use terms acceptable while in beta | D1 |
| 8 | Tested consumer-handset matrix for eSIM install and VoLTE | D1/D2 |
| 9 | Emergency-calling obligation understood and satisfiable | D1 + legal |
| 10 | Physical proof on real hardware — install, data, native call to Nigeria with the app closed | chunk 29 |
| 11 | Selling entity and merchant approval permit selling there | D3/D4 |

Conditions 1–9 are answerable by the [enquiry draft](ENQUIRY-DRAFT.md).
Condition 10 is chunk 29 and cannot be met by any amount of documentation.

## Status by proposed market

The three rows below are the **candidate test journeys** recorded in
`IMPLEMENTATION-PLAN.md` §5. They are candidates, not selected markets — D2 has
not chosen any selling market.

| Proposed market (origin → destination) | Decision | Blocking conditions | Notes |
|---|---|---|---|
| Nigeria → Nigeria | **NO-GO — insufficient evidence** | 1–11 | No published voice coverage for Nigeria; no +234 number availability documented; no rate. Domestic origination may also carry local licensing implications not assessed here. |
| Saudi Arabia → Nigeria | **NO-GO — insufficient evidence** | 1–11 | Highest permanent-roaming risk of the three, and roaming voice is entirely undocumented. |
| United Kingdom → Nigeria | **NO-GO — insufficient evidence** | 1–11 | Most likely of the three to have mature coverage, but nothing published confirms voice, number availability or rate. |

**No market has a single condition satisfied.** The uniformity is the finding:
the blockers are not market-specific gaps, they are the absence of any published
voice coverage, number-availability or pricing data whatsoever.

## Assessment of the supplier direction

Telnyx remains a **reasonable launch candidate**, and nothing found contradicts
the user's selection:

- Branded eSIM resale is explicitly supported and API-driven, including the
  service name shown on the handset.
- Data, voice and the assigned number sit on **one** SIM Card resource, which is
  the architecture the product needs.
- The assigned number is documented as the outbound caller ID and inbound calls
  ring natively — exactly the reset product's identity model.
- Lifecycle, groups, data limits and detail records are documented well enough to
  design against.

The risk is concentrated and specific, not diffuse:

1. **VoLTE is beta with an unpublished API reference.** Building a launch voice
   product on it is a commercial risk decision, not a technical one.
2. **Voice coverage is entirely undocumented.** This is the gating unknown.
3. **No voice spending cap is documented**, which is in direct tension with the
   prepaid promise (D5).
4. **The product is framed as IoT.** Every device guide is a router or dev
   board; there is no consumer-handset VoLTE story published.
5. **One-time-use activation codes** reshape device replacement and recovery, and
   have a per-replacement cost.

## What must not be inferred from this chunk

- That any market is sellable.
- That the data footprint (650+ networks / 180+ countries) is the voice
  footprint. It is not, and the documentation never claims it is.
- That Telnyx has been contacted, quoted or contracted. It has not.
- That the harness passing proves anything about Telnyx. It proves our parsing
  matches published schemas.
- That verified +234 caller ID is required. It is **deferred** and is explicitly
  **not a launch disqualifier**.

## Effect on other chunks

| Chunk | Effect |
|---|---|
| 05, 09, 10, 11 | **Unblocked.** Generic contracts, fixtures and recovery logic proceed. Chunk 09's catalog must stay test-only until D2. |
| 15 (line lifecycle) | **Blocked for live acceptance.** The documented contracts here are enough to design against; the tag-reconciliation pattern must be proven live before it is relied on. |
| 16 (usage) | **Partially informed.** Data usage has documented per-session records; **voice usage has no documented record at all**, so the charging design cannot yet be completed for voice. |
| 17 (controls) | **Blocked on evidence.** Data caps documented with unquantified latency; no voice cap documented. |
| 29 (physical pilot) | **Blocked.** Requires D1 access and real devices. |

D1 and D2 stay **OPEN**. This chunk supplies the questions and the harness; it
does not supply the answers, and it must not be recorded as having done so.
