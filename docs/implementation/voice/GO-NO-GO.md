# Internet calling — go/no-go

Chunk V01, independently reviewed **9 September 2026**. This decision covers
documented preparation only.

## Verdict

| Question | Answer |
|---|---|
| Is an outbound route expressible from documented Telnyx contracts? | **YES** |
| May V02 build the provider-neutral authorization, event inbox and lifecycle model after its listed prerequisites? | **YES** |
| May V02 treat one Telnyx topology or invoice shape as production-proven? | **NO** |
| May live internet calling be enabled? | **NO** |
| Is a hard prepaid guarantee or cost-saving claim supported? | **NO** |

**GO for provider-neutral V02 preparation; NO-GO for a live Telnyx route.** The
official outbound-dialer pattern supplies the missing parking hook, but account
and live tests must close five blockers.

## What V02 may rely on

- A server can create an expiring, single-use authorization and reserve money
  before any PSTN Dial.
- Park Outbound Calls is the documented pre-connection control for ordinary
  client-originated calls.
- A server can create a separate PSTN leg and bridge controlled legs.
- Dial-created legs accept `time_limit_secs`.
- Ed25519 verifies webhook authenticity; event ids and DamDam operation ids
  provide durable replay/idempotency boundaries.
- Outbound Voice Profiles provide coarse destination, concurrency, spend and
  maximum-rate controls.

V02 must keep the Telnyx adapter feature-disabled until the account probes pass.

## Live blockers

### B1 — Credential containment and emergency bypass

No destination scope is documented inside the client JWT. Parking provides a
backend decision for ordinary destinations, but Telnyx explicitly routes
country-matched emergency calls without parking. Account tests must prove the
credential connection can register clients while blocking all unintended direct
PSTN and emergency routing, and must identify one device credential reliably in
the parked event. Client-side validation alone is insufficient.

### B2 — Nigeria rates and billing shape

Nigeria mobile/landline rates, billing increments, minimums and connection fees
were not obtained. The public pricing request returned 404 without an account.
The number of WebRTC, Voice API and termination invoice components for each
candidate topology also needs real CDR evidence. No price comparison is valid.

### B3 — Bounded stopping and spend

`time_limit_secs` bounds a server-created PSTN leg. Public documentation does
not give the client-created parked leg an equivalent provider time limit or
state how long an abandoned parked leg persists. Daily-spend-limit reaction time
and hangup delay are also unstated. A hard prepaid guarantee remains blocked.

### B4 — Nigeria account eligibility

Telnyx says many destinations require Level 2 verification. Whether the account
can activate Nigeria mobile and landline termination, resell it in the intended
markets and present the selected Telnyx number must be confirmed in writing and
tested.

### B5 — Supported client behavior

The current Telnyx packages declare peer ranges that include RN 0.86 and React
19, but the official demo is on RN 0.79.6 and the integration guide acknowledges
peer-resolution friction. V04 must prove clean dependency resolution, native
iOS/Android builds, microphone/audio routing, DTMF, foreground outbound calls and
active-call background/lock behavior. V05 must prove supported browsers and
microphone/media failure behavior.

## V02 interface proposal

These are proposed contracts, not implemented endpoints.

```text
POST /v1/calls/client-session
  request:  { device_id }
  response: { token, sip_identity, expires_at }
```

Issues a short-lived JWT for a non-revoked per-device telephony credential. It
does not expose the Telnyx account API key.

```text
POST /v1/calls/authorize
  request:  { destination_e164, on_behalf_of?, idempotency_key }
  response: { attempt_id, expires_at, max_seconds, estimated_max_charge }
```

Creates one durable attempt and reservation binding the exact destination,
identity, payer, tenant/personal scope, tariff, liability and device credential.

```text
POST /v1/calls/{attempt_id}/start
  validates owner/device and returns only what the selected client adapter needs
  for one attempt; repeated requests converge on the same operation
```

```text
POST /v1/webhooks/telnyx/call-events
  verify signature and timestamp
  insert unique provider event id
  resolve stored attempt/leg mapping
  validate connection, device credential, destination and expected transition
  consume grant once, then create/bridge/reconcile the original provider operation
```

The selected preparatory route is the parked WebRTC pattern in
[API-CONTRACTS.md](API-CONTRACTS.md). The provider interface must still support
the server-originated fallback without changing domain authorization or money
records.

## V02 invariants

1. A destination leg starts only from an unused, unexpired, owner-scoped grant
   whose reservation committed first.
2. No webhook field, `client_state` value or SDK destination is authoritative
   without a matching database record.
3. One provider credential belongs to one device/browser installation and can
   be revoked without changing the user's other credentials.
4. Every signed provider event id is applied at most once, including a replay
   inside the signature tolerance window.
5. Every provider command has a durable local operation id; an unknown outcome
   reconciles against that operation instead of issuing a second Dial.
6. `time_limit_secs` is set on every server-created leg. Unproven bounds keep
   live mode disabled.
7. Attempt-to-leg mappings are authoritative; shared session/CDR identifiers
   are optional evidence, not required assumptions.
8. A reservation remains held until every known supplier liability is final.

## Negative test matrix

| # | Scenario | Required behavior |
|---|---|---|
| N1 | Same authorize idempotency key is replayed | One attempt and one reservation |
| N2 | Another user/device presents the attempt | Refused; no provider command |
| N3 | Expired or already-consumed attempt is started | Refused; no second leg |
| N4 | Destination differs from the stored grant | Refused; stored destination is never replaced |
| N5 | Unsupported, premium, emergency or special number | Refused before SDK/provider invocation |
| N6 | Parked event has an unexpected connection/credential/leg | Quarantined; no PSTN Dial |
| N7 | `client_state` is missing, malformed or names another attempt | Database mapping governs; no authorization from client state |
| N8 | Valid signed event is replayed inside timestamp tolerance | Stored once and transition applied once |
| N9 | Event is unsigned, wrongly signed or too old | Rejected before persistence/state change except audit-safe rejection metadata |
| N10 | Events arrive late or in reverse order | State converges without regression or negative duration |
| N11 | PSTN Dial response is lost or worker restarts after send | Reconcile original operation; no second destination leg |
| N12 | Duplicate bridge/start command after 60 seconds | Durable idempotency still prevents duplication |
| N13 | Client/WebRTC leg never becomes usable | No destination charge; reservation follows defined expiry/reconciliation |
| N14 | PSTN leg rejects or never answers | No retail talk charge; all supplier liabilities still reconciled |
| N15 | Call reaches provider time limit | Known legs end and settlement uses actual components |
| N16 | Two calls race for insufficient available funds | Only the committed reservation may proceed |
| N17 | Membership is revoked mid-call | Defined work-call termination; personal service remains separate |
| N18 | Copied credential dials directly or uses an emergency number | Live account test must prove containment; failure keeps route disabled |

## Status

**V01 documented/preparatory scope: ACCEPTABLE AFTER REVIEW FIXES.**
**Live route: EXTERNAL_BLOCKED** on B1–B5 and D1. V02 is also sequenced behind
chunks 06, 07, 09, 10 and 11; V01 acceptance alone does not make it eligible to
start.
