# Telnyx capability matrix — verified 8 September 2026

Produced by [chunk 03](../chunks/03-telnyx-feasibility.md) (US-35, gate **D1**).

**This is a documentation review, not commercial confirmation.** Every row below
is sourced to a page fetched on **2026-09-08**. Nothing here has been confirmed
by Telnyx sales or support, no account was used, no API call was made against
`api.telnyx.com`, and **D1 remains OPEN**. Re-verify before contracting: the
VoLTE product is explicitly beta and its documentation is explicitly incomplete.

Every claim is tagged with how it is known:

| Tag | Meaning |
|---|---|
| **DOCUMENTED** | Stated on a current official Telnyx page, quoted and linked here |
| **ABSENT** | Not found on any official page after searching — an open question, not a "no" |
| **SIMULATED** | Reproduced from documented schemas in our own fixtures; proves our parsing, nothing about Telnyx |
| **OBSERVED** | Seen from a real API call or device. **There is nothing in this class yet.** |

## 1. Separated capability matrix

The plan's core question is whether *one* eSIM carries data **and** native voice
in a market we can sell in. The published material answers those as separate
products with separate evidence, so they are separated here.

### 1.1 eSIM data

| Question | Status | Evidence |
|---|---|---|
| Branded/white-label eSIM resale | **DOCUMENTED** | "Our eSIM API empowers you to resell under your own brand"; "Create your own pricing models and packages to resell eSIM data profitably, with no minimum order quantities or hidden fees" — [products/esim](https://telnyx.com/products/esim) |
| Service name shown on the handset | **DOCUMENTED** | `whitelabel_name` — "Service Provider Name (SPN) for the Whitelabel eSIM product. It will be displayed as the mobile service name by operating systems of smartphones" — [Purchase eSIMs](https://developers.telnyx.com/api-reference/sim-cards/purchase-esims.md) |
| Data coverage claim | **DOCUMENTED, data only** | "Connect your customers instantly in 180+ countries"; "650+ 5G & 4G (LTE) networks" — [products/esim](https://telnyx.com/products/esim). The page **does not mention voice, VoLTE or calling at all.** |
| Multi-IMSI / local attachment | **DOCUMENTED** | "Every Telnyx SIM carries multiple IMSIs (Telnyx, Sparkle, BICs, T-Mobile, US Cellular). An on-SIM applet automatically selects the best IMSI per location" — [get-started](https://developers.telnyx.com/docs/iot-sim/get-started.md) |
| Data pricing | **DOCUMENTED** | eSIM $0.70 activation; $2/mo active SIM; $0.20/mo disabled or standby; data "tiered by zone and volume" — [get-started](https://developers.telnyx.com/docs/iot-sim/get-started.md) |
| Per-country data zone table | **ABSENT from the pages checked** | [International coverage](https://support.telnyx.com/en/articles/3270106-telnyx-wireless-international-coverage) states "over 180 countries" and that "each zone has a discrete price per MB for data usage", but lists no countries in the fetched content |

### 1.2 Native VoLTE voice

| Question | Status | Evidence |
|---|---|---|
| Product maturity | **DOCUMENTED — BETA** | "**Beta** — VoLTE is in beta. API reference and detailed configuration docs coming soon." — [voice-enabled-iot](https://developers.telnyx.com/docs/iot-sim/voice-enabled-iot.md), fetched 2026-09-08. The beta label from the 8 September planning review **has not changed**. |
| Native calling without an app | **DOCUMENTED** | "Add a real phone number to any eSIM-capable device. No second phone, no SIP client, no app — just a native cellular line with full API control" — same page |
| Voice on the same SIM as data | **DOCUMENTED at the resource level** | Voice is a per-SIM flag on the same SIM Card resource (`voice_enabled`; `POST /sim_cards/{id}/actions/enable_voice`). This is an API-model fact. It is **not** evidence that both work simultaneously on a given visited network. |
| Which countries voice works in | **ABSENT** | No coverage page, country list or matrix exists in the Wireless documentation section. Searched [iot-global-coverage](https://telnyx.com/iot-global-coverage), the wireless docs index and the international-coverage support article; the only published coverage claims are **data** claims. |
| Voice while roaming | **ABSENT** | Not documented anywhere found. |
| Production support terms during beta | **ABSENT** | No SLA, API-stability or production-use statement. The page says the API reference itself is "coming soon". |
| Consumer-handset (as opposed to IoT) support | **ABSENT / contrary signal** | The whole product tree lives under `/docs/iot-sim/`, and every device guide is a router or dev board — Raspberry Pi, Sixfab, Cradlepoint, Pepwave, MikroTik, Nordic nRF9160, Particle Boron. **No smartphone integration guide exists.** eSIMs are described as "downloadable SIM profiles for consumer devices (phones, tablets, laptops)", so phones are in scope for *data*; nothing states a tested consumer-handset VoLTE matrix. |

> **The single most important finding.** The 650+/180+ figures appear only on
> data pages and are qualified as "5G & 4G (LTE) networks". The VoLTE pages
> carry **no coverage figure at all**. Treating the data footprint as the voice
> footprint would be the central mistake available here, and nothing published
> supports it.

### 1.3 Assigned mobile number

| Question | Status | Evidence |
|---|---|---|
| A real number is assigned | **DOCUMENTED** | "When you enable voice on a SIM, Telnyx assigns a Mobile Phone Number — a real +E.164 number" — [mobile-phone-numbers](https://developers.telnyx.com/docs/iot-sim/mobile-phone-numbers.md) |
| Inbound rings natively | **DOCUMENTED** | "Inbound calls ring the device natively." — same page |
| Outbound caller ID | **DOCUMENTED** | "Outbound calls show your number as caller ID." — same page. This is the **assigned** number, and is consistent with the reset product's identity model. |
| Third-party verified +234 caller ID | **ABSENT — and not required** | Nothing documents presenting an arbitrary third-party number as CLI on the cellular line. External CLI is **deferred** (D2) and is explicitly **not a launch disqualifier**. |
| Which countries numbers are available in | **ABSENT** | The page documents *how* a number is assigned but never *where*. No number-country list. |
| Number portability / +234 retention | **ABSENT** | Nothing documented. Do not promise retention or porting. |
| Regional bias signal | **DOCUMENTED** | Inbound call screening: "Number reputation screening applies to US and Canada calls. SHAKEN/STIR screening applies to North America." — [call-forwarding-recording](https://developers.telnyx.com/docs/iot-sim/call-forwarding-recording.md). Feature depth is North-America-centric. |

### 1.4 Messaging

| Question | Status | Evidence |
|---|---|---|
| SMS/MMS/RCS on cellular numbers | **DOCUMENTED as not yet available** | The Wireless docs index describes messaging as "Send and receive SMS, MMS, and RCS messages directly to and from cellular phone numbers attached to Telnyx IoT SIM cards **(coming soon)**". The marketing overview's "A real messaging experience — same as any carrier line" is not matched by shipped documentation. |

Messaging is **out of the committed launch scope** and this confirms it should
stay out. Do not design any flow that depends on SMS to the assigned number.

### 1.5 Device support

| Question | Status | Evidence |
|---|---|---|
| eSIM is a downloadable profile, not hardware | **DOCUMENTED** | "eSIMs are downloadable SIM profiles for consumer devices (phones, tablets, laptops) — not embedded SIM hardware." — [ordering-sims](https://developers.telnyx.com/docs/iot-sim/ordering-sims.md) |
| Activation codes are single-use | **DOCUMENTED** | "eSIM activation codes are one-time use. If the device loses the profile, you need a new eSIM purchase — you can't re-download the same profile." — same page |
| IMEI restriction is available | **DOCUMENTED** | `authorized_imeis` on the SIM Card resource; a SIM in an unlisted device enters `unauthorized_imei` |
| Tested handset matrix for VoLTE | **ABSENT** | None published. |

> **`eSIM activation codes are one-time use` is a product-shaping fact, not a
> detail.** A customer who factory-resets, loses or replaces a phone cannot
> re-download their profile — a **new eSIM purchase** is required, at cost. Any
> "recover your service on a new device" promise must be built on replacement,
> not restoration. This is exactly the constraint the chunk 01 review flagged
> (finding 7) and it is now confirmed against the vendor's own documentation.

### 1.6 Roaming

| Question | Status | Evidence |
|---|---|---|
| Roaming model | **DOCUMENTED** | Multi-IMSI with automatic selection — "local network attachment instead of roaming" where an IMSI exists |
| Permanent-roaming restrictions | **ABSENT** | Not documented. This is a standard MVNO/regulatory constraint and its absence from the docs is not evidence that none apply. |
| Network control | **DOCUMENTED** | Wireless Blocklists "Prevent SIMs from connecting to specific networks by country, MCC, or PLMN" |
| Voice while roaming | **ABSENT** | See 1.2. |

### 1.7 Costs — the Nigeria question

| Question | Status | Evidence |
|---|---|---|
| Per-minute rate to Nigeria from a Telnyx mobile line | **ABSENT** | Not published. [pricing/mobile-voice](https://telnyx.com/pricing/mobile-voice) shows only US carrier data fees ($0.0780/MB for AT&T and US Cellular) and states costs are "Carrier fee + the SIP Trunking fee", varying by destination, with custom quotes via sales. [pricing.md](https://telnyx.com/pricing.md) contains **no mobile-voice per-minute rate at all**, for Nigeria or anywhere. |
| Connection fees, billing increments, inbound charges | **ABSENT** | Not published. |
| Minimum commitments, taxes | **ABSENT** | Not published. |

**No launch pricing can be derived from public sources.** A rate deck from
Telnyx sales is a hard prerequisite for D5 (charging policy) as well as D1.

## 2. Spending control — the hard-cap question

D1 asks whether a hard spending cap can be enforced supplier-side while the app
is closed. Partial answer, for **data only**:

| Mechanism | Status | Evidence |
|---|---|---|
| Group or SIM data limit | **DOCUMENTED** | `data_limit` (`amount` + `unit`) on SIM card groups; a SIM exceeding it enters `data_limit_exceeded` and cannot transition until the limit is raised or the billing cycle resets |
| Usage alerts | **DOCUMENTED as informational** | "Set per-SIM usage thresholds and get notified when SIMs approach their limits" — alerts, not enforcement |
| Enforcement latency / accuracy | **ABSENT** | The docs do not state how quickly `data_limit_exceeded` takes effect network-side, nor the measurement lag. An overshoot window is therefore unquantified. |
| **Any voice spending cap** | **ABSENT** | No minute cap, spend cap or voice-side limit is documented anywhere. |

This is the sharpest commercial risk in the chunk. The reset product's proposed
prepaid model (D5) promises the customer cannot overspend. **Data has a
documented supplier-side cap with unquantified latency; voice has no documented
cap at all.** Until D1 answers this, an app-side balance computed from delayed
records must not be presented as a guaranteed hard cap — which is exactly what
`prd.md` AC-36.4 already forbids.

## 3. What changed since the 8 September planning review

`IMPLEMENTATION-PLAN.md` §5 recorded a documentation review the same day. This
chunk re-verified it independently against current pages and **found no
contradiction**, plus material new detail:

| Plan claim | Re-verified 2026-09-08 |
|---|---|
| VoLTE is labelled beta | **Confirmed**, verbatim, and stronger than recorded: the API reference itself is "coming soon" |
| eSIM resale is supported | **Confirmed**, plus the `product: whitelabel` / `whitelabel_name` mechanism and the SPN-on-handset behaviour |
| SIMs and eSIMs share one resource with optional voice | **Confirmed** — "eSIMs are purchased via a separate endpoint but become the same SIM Card resource" |
| 650+/180+ is not proof of voice coverage | **Confirmed and strengthened** — those figures appear only on data pages; VoLTE pages carry no coverage figure |
| Assigned number is the outbound identity, not third-party CLI | **Confirmed** verbatim |
| Nigeria call rates need to be asked for | **Confirmed** — no mobile-voice per-minute rate is published at all |
| *(new)* Messaging | Documented as "coming soon" — keep out of scope |
| *(new)* eSIM activation codes are one-time use | Reshapes device-replacement and recovery design |
| *(new)* Product framing is IoT | All device guides are routers/dev boards; no smartphone VoLTE guide |
| *(new)* No voice spending cap is documented | Direct risk to the prepaid promise |

## 4. Reproducing this review

```bash
curl -sSL https://developers.telnyx.com/llms.txt
curl -sSL https://developers.telnyx.com/docs/development/llms/wireless-volte-llms-full-txt
curl -sSL https://developers.telnyx.com/docs/development/llms/wireless-sims-esims-llms-full-txt
curl -sSL https://developers.telnyx.com/api-reference/sim-cards/purchase-esims.md
curl -sSL https://developers.telnyx.com/api-reference/sim-cards/get-all-sim-cards.md
curl -sSL https://developers.telnyx.com/docs/iot-sim/api-errors.md
curl -sSL https://telnyx.com/pricing.md
```

Telnyx publishes an LLM-oriented documentation index at
`https://developers.telnyx.com/llms.txt` with per-section full-text exports.
That is the most reliable way to re-verify this matrix, because it carries the
same beta labels and prose as the rendered pages.

**Documentation changes without notice.** Re-date this file on every recheck
rather than assuming it still holds.
