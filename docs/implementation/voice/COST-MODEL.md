# Internet-calling cost worksheet — chunk V01

Reviewed **9 September 2026**. Nigeria rates and the exact invoice shape are not
evidenced, so this worksheet stays symbolic and makes no claim that internet
calling is cheaper than carrier calling.

## Published unit inputs

| Symbol | Published value | Limit |
|---|---|---|
| `W` — WebRTC/browser/app calling usage | **$0.002/min** | Public Telnyx pricing/release material; applicable count and billed duration need CDR proof |
| `V` — Voice API usage | **$0.002/min** | Public Voice API price; whether charged once or for each controlled leg is not established here |
| Billing currency | USD | Supplier billing currency; customer tariff may use another explicit currency |
| `T_dial_max` | 14400 seconds | Default/maximum `time_limit_secs` for a Dial-created Call Control leg |

Telnyx's WebRTC billing release gives an example with two CDRs sharing a
`uuid` for a WebRTC plus SIP-trunk call. It does not establish that every
candidate Call Control topology has exactly two CDRs, shares that identifier or
incurs one Voice API charge.

## Unknown inputs

| Symbol | Required evidence |
|---|---|
| `R_ng_mobile`, `R_ng_fixed` | Current Nigeria prefix-level termination rates |
| `n_w`, `n_v`, `n_p` | Count of billed WebRTC, Voice API and PSTN components for the chosen topology |
| `d_w[i]`, `d_v[i]`, `d_p[i]` | Billable duration of each component from actual CDRs |
| `I_x`, `M_x` | Billing increment and minimum for each component |
| `C_connect[x]` | Per-call/per-leg connection fees |
| `N_rent` | Monthly rental for the chosen outbound number type |
| `T_tax` | Taxes, regulatory fees and carrier passthrough for the seller/route |
| `FX` | Versioned supplier-to-customer currency conversion and spread |
| `D_hangup` | Worst observed delay from requested/provider limit to final termination |
| `D_park` | Maximum billable lifetime of an abandoned client-originated parked leg |

## Supplier-cost equation

Apply each component's own increment and minimum:

```text
billable(raw_seconds, I_x, M_x) =
    max(M_x, ceil(raw_seconds / I_x) * I_x) / 60

supplier_cost =
    sum(i=1..n_w, billable(d_w[i], I_w, M_w) * W)
  + sum(i=1..n_v, billable(d_v[i], I_v, M_v) * V)
  + sum(i=1..n_p, billable(d_p[i], I_p, M_p) * R_ng_<type>[i])
  + sum(all applicable C_connect)
  + T_tax
```

The public sources establish `W` and `V` as unit prices. They do not establish
`n_w`, `n_v` or the Nigeria termination rate for DamDam's chosen route.
There is therefore no defensible fixed per-minute floor beyond the individual
published units.

### Monthly fixed cost

```text
monthly_fixed = N_rent * numbers_held + other_account_fees
```

Number type, inventory strategy and any account minimum remain decisions.

## Retail tariff and reservation

Supplier cost and the customer tariff are separate records. The customer quote
uses a versioned retail tariff in its own currency. Settlement retains the
supplier currency/units and records any FX version explicitly.

For a live prepaid route, the reservation must cover every component that can
remain billable through the authorized maximum and termination overrun:

```text
max_liability =
    upper_bound(chosen topology, authorized_seconds,
                component rates, increments, minimums,
                connection fees, D_hangup, D_park, taxes)
```

No finite hard-prepaid formula is proven for the selected parked topology while
`D_park` and spend-control latency are unknown. V03 may implement the generic
reservation calculation and reject live authorization when any required bound
or tariff input is absent.

## Settlement rule for V03

Do not settle from an estimate, webhook duration alone or an assumed pair of
CDRs. Ingest each supplier record idempotently, associate it through the durable
attempt and provider leg mapping, preserve corrections, and finalize only when
all known liabilities have reached the provider's terminal state.

Customer talk duration is the bridged conversation interval and is charged once
under the retail tariff. WebRTC, Voice API, PSTN, connection and tax lines are
supplier-cost components; they are not duplicate customer minutes.

## Evidence required before pricing

1. Nigeria mobile and fixed rates, including prefix differences.
2. Billing increments, minimums and connection fees per component.
3. A real CDR/invoice set for both the parked topology and, if retained, the
   server-originated fallback.
4. Number rental and account minimums.
5. Taxes/surcharges for the selected seller under D3.
6. Measured hangup and parked-leg bounds.
7. Written confirmation of the Voice API/WebRTC fee count for the route.

These questions are included in the unsent
[ENQUIRY-DRAFT.md](ENQUIRY-DRAFT.md).
