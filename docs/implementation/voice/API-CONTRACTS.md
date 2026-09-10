# Internet-calling route and control contract — chunk V01

Reviewed against public Telnyx documentation on **9 September 2026**. No
Telnyx account was used, no API call was made and no call was placed. The
selected route below is suitable for preparatory implementation; the open
controls in §7 keep the Telnyx adapter disabled for live traffic.

## 1. Security requirement

[VOICE-EXPANSION.md](../VOICE-EXPANSION.md) requires a durable server grant that
binds destination, identity, payer, tariff, liability and expiry before a
billable destination leg starts. A copied client credential must not create a
different funded call.

Telnyx documents a WebRTC JWT as authentication for a telephony credential. It
does **not** document a destination restriction inside that JWT. Treat a token
as able to do everything its parent credential connection permits.

## 2. Documented pre-connection control

Telnyx documents **Park Outbound Calls** for a credential SIP connection. A
WebRTC client can initiate a call, Telnyx parks it instead of connecting it to
the requested destination, emits call events to the configured Voice API
application, and waits for a backend command. The backend can then originate a
PSTN leg and bridge it to the parked WebRTC leg.

This is a real pre-connection decision point for ordinary destinations. It
corrects the submitted V01 claim that no such hook exists.

There is a critical exception: Telnyx states that calls it classifies as
emergency calls for the caller's country **bypass parking and follow its
emergency flow**. Therefore parking alone does not prove that an exposed token
cannot connect or incur cost. DamDam must reject emergency and special numbers
before invoking the SDK and must obtain account evidence that the credential
connection cannot route them. The internet product must not advertise emergency
calling.

## 3. Selected preparatory topology

The minimum documented topology for V02 is the Telnyx outbound-dialer pattern:
a client-originated **parked** WebRTC leg plus a backend-originated PSTN leg.

```text
  1. authorize (HTTPS)             2. SDK newCall
  destination + payer       WebRTC client ──────────────> Telnyx
          │                       │                         │
          v                       │                  parked leg A
     DamDam backend <─────────────┴──── signed webhook ───┘
          │
          │ 3. validate and atomically consume exact grant
          │ 4. Dial destination with time_limit_secs (leg B)
          │ 5. bridge only after leg B answers
          v
       Nigeria PSTN
```

1. `POST /calls/authorize` creates one short-lived attempt and reserves funds in
   PostgreSQL. It binds the normalized destination, assigned caller identity,
   payer, tenant or personal scope, tariff version, maximum liability, client
   device/credential and expiry.
2. The client passes the destination and an opaque attempt reference to the SDK.
   Telnyx must park this leg. The destination in the client request is a claim,
   not authority.
3. The backend accepts the parked event only after signature verification,
   durable event-id deduplication, a database lookup of the attempt and provider
   leg, and exact comparison with the unused, unexpired grant. It atomically
   consumes the grant before any destination command.
4. The backend creates leg B with `POST /v2/calls`, using the stored destination
   and an owned Telnyx number. It never copies an unchecked destination from the
   webhook into the Dial command.
5. After the expected leg B answers, the backend bridges the two recorded legs.

This route is selected because Telnyx publishes it as its outbound WebRTC
dialer pattern. It is **not live-approved**: the emergency bypass, exact webhook
identity fields, parked-leg lifetime and invoice shape require account tests.

### Server-originated fallback

Telnyx also documents that a backend can Dial a registered WebRTC SIP URI. That
allows the backend to originate both legs, keep the destination out of the
client SDK and set `time_limit_secs` on both created legs. It remains a fallback
until an account test proves that:

- a client credential can be inbound-reachable while unable to originate any
  billable or emergency call;
- foreground registration and answering are reliable on supported clients;
- two independently originated calls can be correlated and billed correctly.

V02 must keep provider topology behind an adapter and must not encode either
topology as a settled billing contract.

## 4. Commands, events and identifiers

| Contract | Evidenced use | Review constraint |
|---|---|---|
| Park Outbound Calls | Hold an ordinary client-originated call for backend commands | Emergency calls bypass it; account behavior must be tested |
| `POST /v2/calls` | Create the PSTN leg, or either leg in the fallback | `time_limit_secs` applies only to a leg created with Dial |
| Bridge | Join the recorded WebRTC and PSTN legs | Current official examples conflict between `call_control_id_to_bridge_with` and `call_control_id`; probe the accepted request field before enabling the adapter |
| Hangup | End a controlled leg | Termination delay remains unknown |
| `call.initiated`, `call.answered`, `call.bridged`, `call.hangup` | Drive a convergent local state machine | Events can be duplicated, delayed and reordered |

Persist `call_control_id`, `call_leg_id`, `call_session_id`, connection id and
event `data.id` when present. DamDam's own attempt-to-leg table is authoritative.

The documentation does not establish that two calls created by separate Dial
commands share a `call_session_id`, nor that every possible topology produces
CDRs with one shared `uuid`. Neither value may be the only correlation key.

`client_state` is Base64-encoded data that is echoed in later events. It is a
correlation hint, not an integrity or authorization mechanism. Decode it only
after signature validation, look up the referenced attempt, and validate all
expected provider identifiers and ownership from the database.

## 5. Webhook and command idempotency

Telnyx signs webhook payloads with Ed25519 over `timestamp + "|" + body`. The
existing `_verify_signature` implementation verifies that signature and rejects
timestamps outside a configured tolerance.

A timestamp tolerance limits the age of accepted traffic; it does not stop the
same valid event being replayed within the window. V02 needs a durable webhook
inbox with a unique provider event id. Insert the event before applying a state
transition, acknowledge an already-stored id without applying it twice, and
retain enough information to process late or reordered events.

Telnyx `command_id` deduplicates a command for the same `call_control_id` for
only 60 seconds. Persist a DamDam operation id before sending each command. On
timeout or worker restart, reconcile that operation and its known provider
identifiers; do not issue a second Dial based only on elapsed time.

## 6. Duration and spend bounds

For a Call Control leg created by Dial, `time_limit_secs` runs from answer,
hangs up the leg at the limit and has a documented maximum/default of 14400
seconds. Set it on every server-created leg from the reservation.

The selected parked client leg was not created with Dial. Public documentation
does not expose an equivalent provider-enforced duration on that leg or state
how long it remains parked if the backend is unavailable. Consequently:

- the PSTN destination leg has a documented provider time bound;
- the WebRTC/parked leg and termination overrun remain unbounded by documented
  evidence;
- the Daily Spend Limit is a backstop, not a hard prepaid guarantee, because
  its reaction time is unspecified.

## 7. Account-level controls and live blockers

Outbound Voice Profiles document destination allowlists, a channel limit, a
daily spend limit and a maximum per-minute rate. These reduce exposure but do
not replace the per-attempt grant.

Before live traffic, the account probe must determine whether the WebRTC
credential connection can be configured to allow registration and parking while
blocking direct PSTN and emergency routing. It must also verify the credential
and connection identifiers supplied on parked events so that an attempt can be
bound to one device credential.

Use a separate telephony credential per device or browser installation. Telnyx
recommends separate credentials per device and warns that multiple clients on
one credential share a SIP identity. JWT lifetime is at most 24 hours or the
parent credential's earlier expiry. V02 therefore needs a server endpoint that
issues a short-lived client session for an authenticated, non-revoked device;
the account API key never reaches a client.

## 8. Settlement boundary

Telnyx publishes $0.002/min units for WebRTC and Voice API usage and documents a
two-CDR, shared-`uuid` example for a WebRTC plus SIP-trunk call. That source does
not prove the number of Voice API charges or identifiers for each topology in
this contract.

V03 must ingest all actual provider CDRs into an idempotent usage/settlement
model, associate them through the durable attempt and recorded leg identifiers,
and retain raw supplier units. Customer talk time is measured once from the
bridged interval; supplier components are reconciled separately.

## Sources

All checked 2026-09-09:

- <https://developers.telnyx.com/docs/voice/webrtc/use-cases/outbound-dialer/index>
- <https://support.telnyx.com/en/articles/4351104-sip-connection-settings>
- <https://developers.telnyx.com/docs/voice/webrtc/sdk-commonalities>
- <https://developers.telnyx.com/docs/voice/webrtc/auth/jwt>
- <https://developers.telnyx.com/api-reference/call-commands/dial>
- <https://developers.telnyx.com/api-reference/call-commands/bridge-calls>
- <https://developers.telnyx.com/docs/development/api-fundamentals/webhooks/receiving-webhooks>
- <https://telnyx.com/release-notes/webrtc-billing-and-reporting>
- <https://telnyx.com/pricing/voice-api>
