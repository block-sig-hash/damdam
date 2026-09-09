# UNSENT enquiry — Telnyx internet calling

> **STATUS: UNSENT. DRAFT ONLY.**
> No message has been sent to Telnyx or any other supplier. This chunk had no
> authority to contact anyone, and did not. Sending requires founder approval.

Prepared by chunk V01 on 9 September 2026. It covers the **internet-calling**
track only. The carrier/eSIM enquiry is separate and already drafted at
[../telnyx/ENQUIRY-DRAFT.md](../telnyx/ENQUIRY-DRAFT.md) — send them together or
cross-reference them, but do not merge them: they gate different decisions.

Each question exists because a specific blocker in [GO-NO-GO.md](GO-NO-GO.md)
cannot be closed from public documentation.

---

**Subject:** Outbound WebRTC calling to Nigeria — authorization controls, rates and account eligibility

Hello,

We are building a consumer application that places **outbound** calls from a
React Native app and a browser to ordinary phone numbers, primarily Nigerian
mobile and landline. Calls are placed over the internet; there is no SIM
involved. We are not asking about inbound calling or number verification.

We are evaluating your documented **Park Outbound Calls** WebRTC pattern and a
server-originated two-leg fallback. In both cases our backend creates the PSTN
destination leg only after a short-lived DamDam authorization and reservation.

**1. Credential scope (our largest open question).** If one of our WebRTC
telephony credentials or JWTs were copied from a user's device, what could the
holder do with it?

  a. Can a telephony credential or JWT be restricted so that it can **receive**
     calls we originate but **cannot originate** outbound calls at all?
  b. Can an Outbound Voice Profile be configured with **no** allowed
     destinations, so a connection used only for WebRTC registration cannot
     terminate any billable call?
  c. Is there any per-destination restriction available on the credential or
     token itself, as opposed to at the connection or profile level?
  d. Your SIP Connection Settings page says emergency calls bypass Park
     Outbound Calls. Can emergency routing be disabled completely on this
     credential connection while WebRTC registration and ordinary parked calls
     remain available? Which emergency rules apply to browser/mobile clients
     outside their home country?
  e. Which signed webhook fields reliably identify the telephony credential and
     registered device that originated a parked call?

**2. Spending controls and their timing.**

  a. What is the **reaction time** of the Daily Spend Limit Per Connection?
     Between exceeding the threshold and outbound calls being blocked, how much
     additional spend is possible?
  b. Is there any control that enforces a **hard** prepaid ceiling in real time,
     rather than blocking subsequent calls after a threshold is crossed?
  c. Does `time_limit_secs` apply from answer, and what is the maximum delay
     between the limit being reached and the leg actually terminating?
  d. If our backend becomes unreachable mid-call, what bounds the call's cost?
  e. What provider-enforced limit or timeout applies to a WebRTC leg created by
     the client and left parked without a Voice API command?

**3. Nigeria rates and billing mechanics.**

  a. Current outbound per-minute rates to Nigeria **mobile** and **landline**,
     including any per-prefix variation.
  b. Billing increment (per second, 6-second, per minute) and any minimum
     billable duration.
  c. Any per-call connection fee.
  d. Applicable taxes, surcharges or carrier passthrough, and how they appear
     on the CDR.
  e. For both (i) a client-originated parked WebRTC leg bridged to a Voice API
     PSTN leg and (ii) two server-originated Dial legs, how many WebRTC, Voice
     API and PSTN invoice lines/CDRs are produced? Which identifiers reliably
     associate them?

**4. Account eligibility.**

  a. Does calling Nigeria require **Level 2 verification**, and what does that
     involve for a company at our stage?
  b. Are there resale restrictions on selling outbound calling to consumers, and
     does the answer depend on our legal entity's jurisdiction?
  c. What outbound caller identity may we present? We intend to use a Telnyx
     number we own; we are **not** seeking to display a customer's own number.

**5. SDK support.** The current SDK package declares peer ranges that include
React Native 0.86 and React 19, while the published demo uses RN 0.79.6 and the
integration guide calls for `--legacy-peer-deps`. Do you test RN 0.86/React
19.2 on iOS and Android? Which browser versions does the JS SDK support?

**6. Bridge request contract.** Current official material shows both
`call_control_id_to_bridge_with` and `call_control_id` as the peer field in
the bridge request. Which field is accepted by the current v2 API?

**7. Test access.** Can you provide a test account and rate deck so we can
verify the above before committing to a design? We would particularly like to
measure the spending-control behaviour in question 2 ourselves.

Thank you,

DamDam

---

## Answer tracking

| # | Question | Blocker it closes | Answer | Date |
|---|---|---|---|---|
| 1a–1e | Credential scope, emergency bypass and event identity | **B1** | | |
| 2a/2b | Spend-limit timing | **B3** | | |
| 2c–2e | Termination and parked-leg bound | **B3**, COST-MODEL | | |
| 3a–3e | Nigeria rates and mechanics | **B2** | | |
| 4a | Level 2 verification | **B4** | | |
| 4b | Resale restrictions | D1 commercial | | |
| 4c | Outbound identity | CAPABILITY-MATRIX | | |
| 5 | SDK versions | **B5** | | |
| 6 | Bridge request field | Adapter contract | | |
| 7 | Test account | D1 evidence item 8 | | |

Record answers here **with the date and the person who gave them**, then update
[CAPABILITY-MATRIX.md](CAPABILITY-MATRIX.md) tags from ACCOUNT-CONFIRMED and
[DECISIONS.md](../DECISIONS.md) D1. A supplier's verbal assurance is not
evidence until it is in writing.
