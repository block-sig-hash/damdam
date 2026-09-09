# Internet-calling capability matrix — chunk V01 evidence

Produced by [chunk V01](../chunks/V01-internet-voice-feasibility.md) (US-44) and
independently corrected on **9 September 2026**. Gate **D1** stays open.

No Telnyx account was used, no API call was made, no SDK was installed and no
call was placed. **DOCUMENTED** means only that the cited current public source
states the behavior.

## Evidence tags

| Tag | Meaning |
|---|---|
| **DOCUMENTED** | Stated in a dated official source |
| **ACCOUNT-CONFIRMED** | Observed in DamDam's Telnyx account or confirmed in writing; none in this matrix |
| **PHYSICALLY-TESTED** | Observed in a live call on a supported client; none in this matrix |
| **UNSUPPORTED** | Official material states that it is unavailable or the product excludes it |
| **UNKNOWN** | Public material does not establish it; treat as unavailable |

## Outbound internet calling

| Capability | Status | Evidence and limit |
|---|---|---|
| Browser WebRTC client | **DOCUMENTED** | Telnyx JavaScript/WebRTC documentation describes outbound calling; exact browser versions and live behavior remain untested |
| React Native client | **DOCUMENTED** | Telnyx publishes React Native voice SDKs; native compatibility remains untested |
| Works without an eSIM | **DOCUMENTED** | WebRTC is an IP media/signaling path and the internet route has no SIM/IMSI prerequisite |
| Park ordinary client-originated calls before PSTN connection | **DOCUMENTED** | Park Outbound Calls holds the leg for Voice API commands and the official outbound-dialer flow creates the PSTN leg from the backend |
| Emergency calls obey that parking gate | **UNSUPPORTED** | Telnyx documents that country-matched emergency calls bypass parking and use the emergency flow |
| Backend Dial to a registered client's SIP URI | **DOCUMENTED** | Dial accepts a SIP URI and Telnyx documents the backend-to-client pattern |
| Destination scope inside a WebRTC JWT | **UNKNOWN** | No per-destination token claim or scope was found; assume the token has its parent credential's permissions |
| Exact credential/device identity on parked webhook | **UNKNOWN** | Must be sufficient to bind one provider leg to one authorized device before the PSTN Dial |
| Hard duration on server-created Dial leg | **DOCUMENTED** | `time_limit_secs` runs from answer, emits a time-limit hangup and defaults/maxes at 14400 seconds |
| Hard duration on client-created parked leg | **UNKNOWN** | The parked leg was not created with Dial; no equivalent provider limit or abandoned-park timeout was found |
| Allowed destinations, channel limit and maximum rate | **DOCUMENTED** | Outbound Voice Profile controls are documented; their exact application to this two-connection design needs account proof |
| Daily spend limit | **DOCUMENTED** | It blocks after the threshold is exceeded; reaction time is not documented, so it is not a hard prepaid bound |
| Signed webhooks | **DOCUMENTED** | Ed25519 signature and timestamp headers cover the raw payload |
| Durable webhook replay protection | **UNKNOWN** | Signature freshness does not deduplicate a valid replay within the tolerance; DamDam must store unique event `data.id` values |
| Command deduplication | **DOCUMENTED** | `command_id` is scoped to one `call_control_id` and 60 seconds; DamDam still needs durable operation idempotency |
| Correlation of independently created legs | **UNKNOWN** | Public docs do not guarantee a shared `call_session_id` or CDR `uuid` for every candidate topology |
| Bridge request body | **UNKNOWN** | Current official generated example and request schema/tutorial use different peer field names; verify with a contract probe |
| Nigeria rates and billing mechanics | **UNKNOWN** | The unauthenticated public-pricing request returned 404; rate, increment, minimum and fee need an account rate deck |
| Nigeria access/Level 2 requirement | **UNKNOWN** | Many destinations require Level 2 verification, but public material does not settle Nigeria for this account |
| Owned Telnyx number as outbound identity | **DOCUMENTED** | Supported as a general outbound caller identity; the specific number type and Nigeria presentation need account/live proof |

## Client compatibility

| Target | DamDam version | Status |
|---|---|---|
| React Native / React | RN **0.86.0**, React **19.2.7** | **DOCUMENTED** peer range: current Telnyx commons package declares RN `>=0.79 <1.0` and React `>=19 <20`; its demo uses RN 0.79.6/React 19.0 and its guide requires `--legacy-peer-deps`, so V04 still needs clean installation and native builds |
| Android | min 24, target/compile 36 | **UNKNOWN** live compatibility; outbound voice requires microphone, internet/network-state and audio-routing permissions, to be added only in V04 |
| iOS | deployment target 15.1 | **UNKNOWN** live compatibility; outbound voice requires a microphone usage description and active-call audio integration |
| Browser | Next.js 16.2.10, React 19.2.7 | **UNKNOWN** exact supported browser/version matrix and live microphone/media behavior |
| Foreground outbound | — | **UNKNOWN** until mobile/browser SDK prototypes prove connect, dial, DTMF, mute, audio routing and hangup |
| Background/locked outbound continuation | — | **UNKNOWN**; outbound-only scope does not justify restoring incoming PushKit/FCM, but active-call OS behavior needs physical testing |

## Scope boundaries

| Capability | Status |
|---|---|
| Incoming app/browser ringing | Deferred |
| Customer-owned verified caller ID | Deferred; chunk 04 removed the previous flow |
| Carrier eSIM/native-dialer voice | Separate evidence track at [../telnyx/](../telnyx/) |
| Emergency calling in the internet product | Unsupported product claim; the Telnyx parking bypass is a launch blocker until safely constrained |

## Sources

All read 2026-09-09:

- <https://developers.telnyx.com/docs/voice/webrtc/sdk-commonalities>
- <https://developers.telnyx.com/docs/voice/webrtc/use-cases/outbound-dialer/index>
- <https://support.telnyx.com/en/articles/4351104-sip-connection-settings>
- <https://developers.telnyx.com/docs/voice/webrtc/auth/jwt>
- <https://developers.telnyx.com/api-reference/call-commands/dial>
- <https://developers.telnyx.com/api-reference/call-commands/bridge-calls>
- <https://developers.telnyx.com/docs/development/api-fundamentals/webhooks/receiving-webhooks>
- <https://support.telnyx.com/en/articles/4320411-more-about-outbound-voice-profiles>
- <https://support.telnyx.com/en/articles/1130717-limits-on-concurrent-outbound-calls>
- <https://telnyx.com/resources/new-set-daily-spend-limits-on-outbound-calling>
- <https://telnyx.com/release-notes/webrtc-billing-and-reporting>
- <https://telnyx.com/pricing/voice-api>
- <https://github.com/team-telnyx/react-native-voice-commons/blob/main/react-voice-commons-sdk/package.json>
- <https://github.com/team-telnyx/react-native-voice-commons/blob/main/package/package.json>
- <https://github.com/team-telnyx/react-native-voice-commons/blob/main/package.json>
