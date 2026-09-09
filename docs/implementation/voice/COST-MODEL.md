# Internet-calling cost worksheet — chunk V01

Produced **9 September 2026**. Supplier rates for Nigeria are **not evidenced**,
so the model is symbolic. Every number below is either cited or a named symbol —
**no rate is invented, and no claim is made that this is cheaper than carrier
calling.**

## What is evidenced

| Input | Value | Source |
|---|---|---|
| WebRTC call leg | **$0.002 / min** | Telnyx WebRTC billing release note, 2026-09-09 |
| Voice API / Call Control usage | **$0.002 / min** | Voice API pricing page, 2026-09-09 |
| Billing currency | **USD** | Same |
| CDRs per bridged call | **2**, correlated by identical `uuid` | WebRTC billing release note |
| Max leg duration | 14400 s default and maximum | Dial API reference |

## What is not evidenced

| Input | Why it is symbolic |
|---|---|
| `R_ng_mobile` — Nigeria mobile termination, $/min | Not published per-country. `GET /v2/public/pricing` returned **HTTP 404 unauthenticated** on 2026-09-09 |
| `R_ng_fixed` — Nigeria landline termination, $/min | Same |
| `C_connect` — per-call connection fee | Existence and amount unknown for this account |
| `I` — billing increment (per second / 6 s / 60 s) | Not stated on the public pricing page; materially changes short-call cost |
| `M` — minimum billable duration | Not stated |
| `N_rent` — number rental, $/month | Published per-country on the numbers page, but the *specific* number type this product needs is not chosen yet |
| `T` — taxes, surcharges, carrier passthrough | "Carrier passthrough and taxes vary by destination" — explicitly variable |
| `FX` — USD→NGN rate and spread | Commercial choice, not a Telnyx input |
| `D_term` — permitted termination delay | How long a leg may persist after a hangup command; bounds worst-case overrun |

## Per-call supplier cost

For one bridged customer call of billable duration `d` minutes to Nigeria:

```
supplier_cost(d) =
      d × 0.002                     # leg A, WebRTC       (evidenced)
    + d × 0.002                     # Call Control usage  (evidenced)
    + d × R_ng_<type>               # leg B, PSTN         (UNKNOWN)
    + C_connect                     # per call            (UNKNOWN)
    + T                             # taxes/passthrough   (UNKNOWN)

where d = max(M, ceil(actual_seconds / I) × I / 60)
```

**The two evidenced legs alone are $0.004/min before the PSTN leg.** That is the
floor, not the price. `R_ng_mobile` is very likely the dominant term, so no
comparison with carrier calling is possible yet.

### Amortised per-account

```
monthly_fixed = N_rent × numbers_held        # UNKNOWN
```

## Retail price and prepaid headroom

Supplier cost is **not** the customer tariff. Per
[VOICE-EXPANSION.md](../VOICE-EXPANSION.md), the customer price comes from a
**versioned retail tariff**, and supplier cost reconciles separately.

Reservation before a call must cover the **worst case**, not the expected case:

```
max_liability = (T_max / 60) × (0.002 + 0.002 + R_ng_<type>)
              + C_connect + T
              + overrun_allowance(D_term)

where T_max = time_limit_secs set on the legs
```

`overrun_allowance(D_term)` exists because a hangup command is not instantaneous.
With `D_term` unknown, V03 must either measure it on a real account or hold a
deliberately conservative allowance — and say which.

## Worked example — structure only, not a quotation

`T_max = 600 s (10 min)`, per-second increment, no minimum:

| Component | Cost |
|---|---|
| Leg A WebRTC | 10 × $0.002 = **$0.020** |
| Call Control | 10 × $0.002 = **$0.020** |
| Leg B Nigeria | 10 × `R_ng_mobile` = **unknown** |
| Connection fee | `C_connect` = **unknown** |
| Taxes | `T` = **unknown** |
| **Reservation floor** | **$0.040 + 10·R_ng_mobile + C_connect + T** |

At a hypothetical `R_ng_mobile = $0.05/min` the PSTN leg is $0.50 — **12× the
two evidenced legs combined.** This is exactly why no cost claim can be made
before D1 produces a rate deck. The figure is an illustration of sensitivity,
**not** an estimate of Nigeria pricing.

## What must be obtained before any pricing decision

1. Nigeria mobile and landline rates, per destination prefix if they differ.
2. Billing increment `I` and minimum `M`.
3. Connection fee `C_connect`, if any.
4. Taxes and carrier passthrough for the selling entity's jurisdiction (**D3**,
   also open — the seller determines the tax treatment).
5. Permitted termination delay `D_term`.
6. Whether Voice API usage is billed on both legs or once per session.

Items 1–5 are in the unsent [ENQUIRY-DRAFT.md](ENQUIRY-DRAFT.md). Item 6 is
resolvable from a real CDR pair once an account exists.

## Rule for V03

**Do not charge a customer from an estimate.** Reserve against
`max_liability`, settle against the two actual CDRs correlated by `uuid`, and
release the difference. A displayed balance that assumes the expected case will
over-commit funds on long calls to expensive destinations.
