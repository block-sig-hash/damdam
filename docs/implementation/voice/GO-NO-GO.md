# Internet calling — go/no-go

Chunk V01, **9 September 2026**. Decision covers **documented preparation only**.

## Verdict

| Question | Answer |
|---|---|
| Is the route technically expressible from documented Telnyx contracts? | **YES** |
| May V02 implement the authorization and lifecycle skeleton? | **YES**, for the evidenced parts only |
| Is a **live** internet-calling route ready to enable? | **NO** |
| Is a **hard prepaid spending guarantee** provable today? | **NO** |
| May any pricing or cost-saving claim be made? | **NO** |

**GO for V02 documented implementation. NO-GO for live calling and for any
prepaid guarantee.** The gap is account evidence, not design.

## Why GO for V02

The topology in [API-CONTRACTS.md](API-CONTRACTS.md) is built entirely from
documented behaviour:

- `Dial` accepts a **SIP URI** as `to`, so the backend can originate to the
  client and the client never names a destination
- `time_limit_secs` gives a **provider-enforced** per-leg duration bound that
  survives backend failure
- Ed25519 webhook signing is documented and **already correctly implemented** in
  this repository
- `call_session_id` correlates both legs; CDRs share a `uuid`
- Outbound Voice Profiles provide destination, concurrency, daily-spend and
  rate ceilings independent of application code

None of that required inventing a claim or a hook.

## Why NO-GO for live calling

### B1 — Can a stolen WebRTC credential dial out? *(blocking, unresolved)*

A Telnyx WebRTC credential/JWT authenticates an endpoint. **No per-destination
scope on the token is documented.** The proposed mitigation is to attach the
WebRTC credential connection to an Outbound Voice Profile permitting **no**
destinations — but whether a profile can be configured with an empty allowed-
destination set is not documented.

- **If yes:** a stolen credential can answer calls but not originate billable
  ones. Residual risk acceptable.
- **If no:** a stolen credential can dial whatever that profile permits, bounded
  only by channel limit, daily spend limit and rate threshold. That is a real
  financial exposure and must be stated to the founder before launch, not
  discovered later.

**This is the single question that most changes the design.**

### B2 — Nigeria rates are unobtainable without an account *(blocking pricing)*

Not published per-country; `GET /v2/public/pricing` returned **HTTP 404
unauthenticated** on 2026-09-09. Billing increment, minimum duration and
connection fee are also unstated. **No cost comparison with carrier calling is
possible** — see [COST-MODEL.md](COST-MODEL.md).

### B3 — Daily spend limit latency is unquantified *(blocking hard caps)*

Documented as blocking outbound "once spending has exceeded the threshold", with
no stated reaction time. A cap that lags cannot back a hard prepaid promise. The
per-leg `time_limit_secs` is the only bound with documented, immediate semantics.

### B4 — Level 2 verification for destinations *(blocking Nigeria specifically)*

"Many destinations require Level 2 verification before activation." Whether
Nigeria mobile is among them, and what that entails for a new account, is
account-specific.

### B5 — SDK compatibility with RN 0.86 *(blocking V04 only)*

This repository runs React Native **0.86.0** / React **19.2.7**. Telnyx's RN SDK
support for a version this recent must be confirmed against its own published
matrix. Does not block V02 or V03, which are backend-only.

## Interface proposal for V02

Concrete enough to build against, narrow enough not to pre-empt V03.

```
POST /v1/calls/authorize
  request:  { destination_e164, on_behalf_of? }
  response: { attempt_id, expires_at, max_seconds, estimated_max_charge }
```

Creates a durable **call attempt** binding destination, outbound identity, payer,
tenant, rate version, maximum liability and expiry; reserves funds atomically in
PostgreSQL **before** any provider command. Returns no SDK credential and no
destination-bearing token.

```
POST /v1/calls/{attempt_id}/start
  → server Dials leg A to the client's SIP URI with time_limit_secs
  → on call.answered(leg A): Dial leg B to the destination
  → on call.answered(leg B): bridge
```

```
POST /v1/webhooks/telnyx/call-events    (Ed25519 verified — reuse R1)
  call.initiated | call.answered | call.hangup | call.bridged
  → resolve attempt via client_state, converge state, settle on hangup
```

**Invariants V02 must hold:**

1. The client never sends a destination to the SDK, and never receives one in a
   token.
2. `time_limit_secs` is set on **both** legs from the reservation.
3. An unknown outcome reconciles against the **original** attempt — no blind
   second PSTN leg. (`command_id` dedupes only within 60 s; own idempotency key
   required.)
4. No reservation is released until settlement is final.
5. Both CDRs are settled; leg durations are never summed as customer talk time.

## Negative test matrix for V02

| # | Scenario | Required behaviour |
|---|---|---|
| N1 | Replayed authorize request | One attempt, one reservation |
| N2 | Client presents an attempt id belonging to another user | Refused; nothing dialled |
| N3 | Expired attempt used | Refused; reservation already released |
| N4 | Leg A never answered | Reservation released; no leg B |
| N5 | Leg B rejected by the provider | Reservation released; no customer charge |
| N6 | Worker dies between the two Dials | Reconciles to the original attempt; no duplicate PSTN leg |
| N7 | Duplicate `call.hangup` webhooks | Settled once |
| N8 | Late/reordered `call.answered` after `call.hangup` | Converges without negative duration |
| N9 | Unsigned or wrongly-signed webhook | Rejected before any state change |
| N10 | Webhook replayed outside the tolerance window | Rejected |
| N11 | Call reaches `time_limit_secs` | `hangup_cause=time_limit`; settled at the bound |
| N12 | Two concurrent calls exceeding available funds | Second refused at reservation |
| N13 | Membership revoked mid-call | Defined termination policy; personal service unaffected |
| N14 | Destination outside policy (premium/unsupported) | Refused server-side before any provider command |
| N15 | Stolen credential attempts direct origination | **Cannot be tested without an account — B1** |

N15 is deliberately listed as untestable rather than quietly dropped.

## What must not be claimed

- That internet calling is cheaper than carrier calling — **B2**.
- That spending is hard-capped — **B3**; only the per-leg time bound is proven.
- That a stolen credential cannot dial — **B1**.
- That this provides emergency calling. It does not, and must not be presented
  as an alternative to carrier emergency access.

## Status

**V01 delivered scope: READY_FOR_REVIEW.**
**Remainder: EXTERNAL_BLOCKED on D1 account access** — B1, B2, B3 and B4 cannot
be closed by documentation. The unsent [ENQUIRY-DRAFT.md](ENQUIRY-DRAFT.md)
covers all four.
