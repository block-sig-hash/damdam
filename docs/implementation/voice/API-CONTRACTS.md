# Internet-calling route and control contract — chunk V01

Produced by [chunk V01](../chunks/V01-internet-voice-feasibility.md) (US-44) on
**9 September 2026** from public documentation. **No account, no API call, no
SDK installed, no call placed.**

This document proposes **one** topology and shows what evidence supports each
part. Where documentation does not settle a point it is marked, not filled in.

## 1. The problem this topology has to solve

[VOICE-EXPANSION.md](../VOICE-EXPANSION.md) states the requirement plainly:

> A copied SDK token must not bypass this grant, change destination or fund
> another call.

So the question is not "can a WebRTC client call a phone number" — it obviously
can — but **who chooses the destination**.

**Finding: a Telnyx WebRTC credential or JWT does not carry a destination
scope.** The credential/JWT documentation describes authentication of a SIP
endpoint — username/password or a time-limited JWT in their place. It says
nothing about restricting which numbers that endpoint may dial, and no
per-destination claim, scope or allowed-list on the token is documented.

Per the plan's rule that unknown means unavailable, **the token must be assumed
to authorise dialling anything the connection is permitted to dial.** Any design
where the client passes a destination to the SDK is therefore unacceptable: a
copied token becomes a funded dialler.

## 2. Chosen topology — server-originated, two legs, bridged

The client **never dials and never names a destination.** It registers and
answers.

```
  authorize (HTTPS)        ┌─────────────┐
  ────────────────────────>│   DamDam    │
   {destination, payer}    │   backend   │
                           └──────┬──────┘
                                  │ 1. POST /v2/calls  to = sip:<client>@sip.telnyx.com
                                  │                    time_limit_secs, client_state=attempt_id
                                  v
   ┌──────────┐  leg A     ┌─────────────┐  leg B    ┌──────────────┐
   │ RN /     │<===========│   Telnyx    │==========>│  Nigeria     │
   │ browser  │  (answers) │             │ 2. Dial   │  PSTN        │
   └──────────┘            └─────────────┘  3. Bridge└──────────────┘
```

1. Client asks the backend to authorise a call. The backend records a durable
   **call attempt** binding destination, outbound identity, payer, tenant, rate
   version, maximum liability and expiry, and reserves funds — all before any
   provider command.
2. Backend issues `Dial` with `to` = the client's **SIP URI**. Evidenced: `to`
   accepts "DID or SIP URI", e.g. `sip:username@sip.telnyx.com;secure=srtp`.
3. Client SDK answers leg A. It was told nothing about the destination.
4. On `call.answered` for leg A, backend issues `Dial` for leg B to the E.164
   destination with `from` set to an owned Telnyx number.
5. On leg B answer, backend issues `bridge`.

**Why this satisfies the requirement:** the destination exists only in the
backend's attempt record and in the leg-B `Dial` command. A stolen token lets an
attacker impersonate the *called* endpoint — they can answer calls the backend
originates for that user — which is a real but far smaller problem than an
attacker choosing destinations and spending the balance.

**What this design does not do:** it does not prevent a stolen credential from
*attempting* its own outbound call. That has to be blocked at the account level;
see §5 and blocker **B1**.

### Rejected alternative

Client dials the destination directly with the SDK, backend "approves" via a
webhook veto. **Rejected: no such veto hook is documented.** The Call Control
event flow reports state; it does not offer a pre-authorisation gate that can
deny a client-initiated leg before it is billable. Building on an imagined hook
is precisely what the assignment forbids.

## 3. Commands and events

All from current documentation, read 2026-09-09.

| Command | Purpose | Key parameters |
|---|---|---|
| `POST /v2/calls` (Dial) | Originate leg A, then leg B | `to` (E.164 **or SIP URI**), `from` (+E.164), `from_display_name` (≤128), `time_limit_secs`, `command_id`, `client_state`, `webhook_url` |
| Bridge | Join the two legs | `call_control_id`, `client_state`, `command_id`, `park_after_unbridge` |
| Hangup | Server-side termination | `call_control_id` |

**Identifiers returned by Dial**, all three needed:

| Identifier | Use |
|---|---|
| `call_control_id` | The token for issuing further commands on that leg |
| `call_leg_id` | Correlates webhooks for one leg |
| `call_session_id` | Correlates **both legs of one call** — the key for settlement |

`client_state` is Base-64 and round-trips through events: carry the attempt id
in it so every event maps to a reservation without a lookup table.

## 4. Webhook validation, idempotency and termination

**Signature — Ed25519, not HMAC.** Headers `telnyx-signature-ed25519` and
`telnyx-timestamp`; the signed string is `timestamp | payload`, Base64-encoded;
verified with Telnyx's public key.

> This is already implemented correctly in this repository at
> `apps/api/app/voice/service.py::_verify_signature`, including a timestamp
> tolerance window against replay. See [LEGACY-REUSE.md](LEGACY-REUSE.md) R1.

**Command idempotency — bounded and short.** `command_id` causes Telnyx to
ignore duplicate commands for the same `call_control_id`, **within 60 seconds**.

> **This is not sufficient on its own.** A retry after a worker restart more than
> 60 seconds later is *not* deduplicated by the provider. V02 must treat
> `command_id` as a cheap first line and rely on its own attempt-state machine
> for correctness, reconciling an unknown outcome against the original attempt
> rather than re-dialling. This is finding 4 of the original review, in a new
> place.

**Termination — provider-enforced per leg.** `time_limit_secs` "sets the maximum
duration of a Call Control Leg in seconds. If the time limit is reached, the
call will hangup and a `call.hangup` webhook with a `hangup_cause` of
`time_limit` will be sent." The bound runs **from answer**; default and maximum
are 14400 s.

> Set `time_limit_secs` on **both** legs from the reservation's maximum billable
> duration. This is the only documented bound that survives the backend being
> unavailable — a worker that dies mid-call cannot leave an unbounded billable
> leg. It is the single most important control in this design.

## 5. Account-level controls (Outbound Voice Profile)

These are provider-enforced and independent of application code:

| Control | Behaviour |
|---|---|
| Allowed destinations | Whitelist by region or individual country; 255 destinations across 10 regions; many need **Level 2 verification** |
| Channel Limit | Concurrent outbound channels; 1 call = 1 channel; excess rejected |
| Daily Spend Limit Per Connection | Blocks outbound once exceeded, resets 00:00:00 UTC, emails the account owner |
| Max per-minute rate | Rejects destinations above a set rate — a blunt but useful guard against premium-rate abuse |

**Proposed separation, requiring account confirmation:**

- Connection **W** — the WebRTC credential connection the clients register to.
  Attached to an Outbound Voice Profile permitting **no PSTN destinations**, so
  a stolen credential cannot originate a billable call.
- Connection **C** — the Call Control application the backend uses to dial legs
  A and B. Its credentials never leave the server.

**Blocker B1: whether an Outbound Voice Profile can be configured with zero
allowed destinations is not documented.** If it cannot, a stolen WebRTC
credential retains some dialling ability and the residual exposure has to be
bounded by the channel limit, daily spend limit and rate threshold instead —
weaker, and it must be stated as such rather than assumed away.

## 6. Settlement inputs

**Two CDRs per call, correlated.** A call with a WebRTC component and a SIP
trunking component produces "two separate CDRs describing the call and its
costs, with identical `uuid` field values so they can be easily matched."

> Consequence for V03: **do not sum leg durations as customer talk time.** One
> customer minute is two billable supplier legs. Charging the customer for the
> sum would roughly double the bill. Reconcile supplier cost from both CDRs;
> derive the customer price from the versioned retail tariff and the *bridged*
> duration.

## 7. What V02 may implement

Only the evidenced parts: server-originated Dial to a SIP URI, bridge,
`time_limit_secs` on both legs, Ed25519 webhook validation, `command_id` plus an
own idempotency key, and `call_session_id` correlation.

**Not** implementable from documentation alone: any hard prepaid guarantee that
depends on the daily spend limit reacting quickly, and any claim that a stolen
credential cannot dial — both need account confirmation.
