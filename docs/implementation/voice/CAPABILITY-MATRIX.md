# Internet-calling capability matrix — chunk V01 evidence

Produced by [chunk V01](../chunks/V01-internet-voice-feasibility.md) (US-44) on
**9 September 2026**, against the internet track of gate **D1**, which stays
**OPEN**.

**No Telnyx account exists.** No API call was made, no message was sent, no SDK
was installed and no call was placed. Everything below is a reading of public
documentation on the date shown.

## Evidence tags

| Tag | Meaning |
|---|---|
| **DOCUMENTED** | Stated in current official Telnyx documentation, with the source and date recorded |
| **ACCOUNT-CONFIRMED** | Requires a Telnyx account or written confirmation. **None obtained.** |
| **PHYSICALLY-TESTED** | Observed on a real device/browser against live service. **None performed.** |
| **UNSUPPORTED** | Documentation states it is not available |
| **UNKNOWN** | Not addressed by documentation. Per [VOICE-EXPANSION.md](../VOICE-EXPANSION.md), **unknown means unavailable** until evidenced |

## Internet calling — outbound only

| Capability | Status | Evidence |
|---|---|---|
| Browser (WebRTC JS SDK) outbound to PSTN | **DOCUMENTED** | Telnyx WebRTC product and JS SDK docs, 2026-09-09 |
| React Native outbound to PSTN | **DOCUMENTED** | Telnyx React Native / mobile WebRTC SDK docs, 2026-09-09 |
| Calling with **no eSIM installed** | **DOCUMENTED** | WebRTC leg is an IP media leg to Telnyx; nothing in the WebRTC or Call Control documentation ties it to a SIM, IMSI or carrier line |
| Server-controlled destination (client never names the number) | **DOCUMENTED** | `Dial` accepts a SIP URI as `to`, e.g. `sip:username@sip.telnyx.com;secure=srtp` — see [API-CONTRACTS.md](API-CONTRACTS.md) |
| Per-leg hard duration bound | **DOCUMENTED** | `time_limit_secs` terminates the leg and emits `call.hangup` with `hangup_cause=time_limit`; default and maximum 14400 s |
| Provider-enforced allowed destinations | **DOCUMENTED** | Outbound Voice Profile destination whitelist — 255 destinations across 10 regions; **many require Level 2 verification** |
| Provider-enforced concurrency cap | **DOCUMENTED** | Outbound Voice Profile *Channel Limit*: 1 call = 1 channel; calls beyond the limit are rejected |
| Provider-enforced daily spend cap | **DOCUMENTED** | *Daily Spend Limit Per Connection*, resets 00:00:00 UTC, blocks outbound and emails the account owner |
| Provider-enforced max per-minute rate | **DOCUMENTED** | Outbound Voice Profile rate threshold rejects destinations above a set per-minute rate |
| Signed webhooks | **DOCUMENTED** | Ed25519 (`telnyx-signature-ed25519`, `telnyx-timestamp`), signature over `timestamp \| payload`, Base64 |
| Command idempotency | **DOCUMENTED** | `command_id` — duplicates for the same `call_control_id` ignored **within 60 seconds** |
| Nigeria outbound rates | **ACCOUNT-CONFIRMED** | Not published. `GET /v2/public/pricing` returned **HTTP 404 unauthenticated** on 2026-09-09 |
| Outbound Voice Profile with **zero** allowed destinations | **UNKNOWN** | The whitelist is documented as selectable by region/country; whether an empty selection is permitted — the control this design leans on — is not stated. See [GO-NO-GO.md](GO-NO-GO.md) blocker B1 |
| Daily-spend-limit enforcement latency | **UNKNOWN** | "Once spending has exceeded the threshold" is not quantified. A cap that lags by minutes is not a hard prepaid guarantee |
| Nigeria destination availability on a new account | **ACCOUNT-CONFIRMED** | Level 2 verification is documented as required for many destinations; whether Nigeria mobile is included is account-specific |

## Explicitly out of scope for this chunk

| Capability | Status |
|---|---|
| Incoming app/browser ringing | **Deferred by the approved plan.** Not investigated |
| Third-party verified caller ID | **Retired** by chunk 04D; must not be reintroduced |
| Carrier eSIM voice (native dialer) | **Separate track.** See [../telnyx/CAPABILITY-MATRIX.md](../telnyx/CAPABILITY-MATRIX.md); nothing here is evidence for it |
| Emergency calling | **UNSUPPORTED for the internet route.** An IP calling app is not a substitute for carrier emergency access, and must not be presented as one |

## Client platform compatibility

Recorded against the versions actually in this repository, not the SDK's
advertised minimums.

| Target | This repo | Status |
|---|---|---|
| React Native | **0.86.0**, React 19.2.7 | **ACCOUNT-CONFIRMED** — SDK support for an RN version this recent must be checked against the SDK's own published compatibility before V04 |
| Android | `minSdkVersion 24`, target/compile 36 | **UNKNOWN** — WebRTC needs runtime microphone permission; chunk 04D removed `RECORD_AUDIO`, so V04 reinstates it **for outbound calling only** |
| iOS | deployment target **15.1** | **UNKNOWN** — same: `NSMicrophoneUsageDescription` was removed by 04D and would return |
| Browser | Next.js 16.2.10, React 19.2.7 | **DOCUMENTED** — WebRTC is standard in current Chrome/Edge/Firefox/Safari; exact minimums are a V05 input |

**Chunk 04D removed the VoIP background mode, PushKit and CallKit deliberately.**
Outbound-only calling does **not** need them: they exist to wake an app for an
*incoming* call, which is deferred. V04 must not reinstate them "because the old
code had them" — see [LEGACY-REUSE.md](LEGACY-REUSE.md).

## Sources

All read 2026-09-09:

- <https://telnyx.com/products/webrtc>
- <https://developers.telnyx.com/docs/development/webrtc/auth/credential-connections>
- <https://telnyx.com/release-notes/jwt-auth-webrtc>
- <https://developers.telnyx.com/api-reference/call-commands/dial>
- <https://developers.telnyx.com/api-reference/call-commands/bridge-calls>
- <https://developers.telnyx.com/development/api-fundamentals/webhooks/receiving-webhooks>
- <https://support.telnyx.com/en/articles/4320411-more-about-outbound-voice-profiles>
- <https://support.telnyx.com/en/articles/1130717-limits-on-concurrent-outbound-calls>
- <https://telnyx.com/resources/new-set-daily-spend-limits-on-outbound-calling>
- <https://telnyx.com/release-notes/webrtc-billing-and-reporting>
- <https://telnyx.com/pricing/voice-api>
