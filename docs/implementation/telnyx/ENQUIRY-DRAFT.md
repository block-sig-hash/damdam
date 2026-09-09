# UNSENT DRAFT — Telnyx capability and commercial enquiry

> **STATUS: UNSENT. DO NOT SEND.**
>
> Prepared by [chunk 03](../chunks/03-telnyx-feasibility.md) on 8 September 2026
> as preparation for gate **D1**. No message has been sent to Telnyx, no account
> has been opened, no sales contact has been made and no commercial commitment
> exists. Sending this is the founder's decision and requires their own review —
> particularly of the volume and market statements in §1, which are **planning
> assumptions and must be corrected to reality before any outreach.**
>
> Placeholders are written as `[[LIKE THIS]]`. Every one must be filled or
> deleted before sending; none may be guessed.

---

**To:** Telnyx sales / solutions engineering
**Subject:** Wireless eSIM + VoLTE feasibility for a consumer and enterprise connectivity product

Hello,

We are evaluating Telnyx Wireless as the launch carrier for a mobile
connectivity product and need to confirm a small number of capabilities before
committing. We have read the public Wireless, eSIM and VoLTE documentation, so
the questions below are deliberately the ones the documentation does not answer.

## 1. What we are building

`[[FOUNDER: correct all of this before sending — the figures below are internal
planning placeholders, not commitments, and must not be sent as if they were
real forecasts.]]`

A consumer mobile app and an enterprise/government dashboard selling prepaid
connectivity. Customers install an eSIM and then use their phone's **normal
dialer and mobile data** — no VoIP app, no SIP client. The same profile must
carry data and native voice.

- Legal selling entity: `[[UNDECIDED — see D3]]`
- First selling markets: `[[UNDECIDED — see D2]]`
- Primary calling destination: **Nigeria** (mobile and landline)
- Expected first-year volume: `[[FOUNDER TO SUPPLY — do not send a guess]]`
- Target launch: `[[FOUNDER TO SUPPLY]]`

## 2. The decisive question

**Can one resold Telnyx eSIM profile carry both mobile data and native
incoming/outgoing cellular voice, simultaneously, on a consumer smartphone, in
each market we intend to sell in?**

If the answer is market-dependent, we need the list of markets where it holds,
not a global statement. We would rather exclude a market than mis-sell one.

## 3. VoLTE production readiness

Your [VoLTE overview](https://developers.telnyx.com/docs/iot-sim/voice-enabled-iot)
states, as of 8 September 2026: "**Beta** — VoLTE is in beta. API reference and
detailed configuration docs coming soon."

1. What are the terms of the beta — is production, revenue-generating consumer
   use permitted today?
2. What is the expected GA timeline, and what changes at GA?
3. What API-stability guarantee applies during beta? Will the voice action and
   `mobile_phone_numbers` schemas change?
4. What support commitment and SLA applies to beta VoLTE in production?
5. When will the voice API reference and configuration documentation publish?
6. Are there beta customers running consumer smartphone voice at scale today?

## 4. Coverage — four separate matrices, please

Your published "650+ networks / 180+ countries" figures appear on the eSIM data
pages and are qualified as 5G/4G LTE networks. We are not treating them as voice
coverage. Please supply, ideally as a machine-readable matrix:

1. **Data coverage** — by country, network/PLMN, IMSI profile and technology.
2. **Native voice coverage** — by country, visited network and IMSI profile.
   Outbound and inbound stated separately.
3. **Assigned-number availability** — which countries you can issue a Mobile
   Phone Number in, and the regulatory or address requirements for each.
4. **Roaming** — where voice works while roaming; where permanent roaming is
   restricted, time-limited or prohibited; and any country exclusions.

Also: does a multi-IMSI switch interrupt an in-progress call or registration for
voice, and is voice guaranteed across every IMSI on the profile?

## 5. Consumer handsets

Your device documentation covers routers and IoT development boards (Raspberry
Pi, Sixfab, Cradlepoint, Pepwave, MikroTik, Nordic, Particle). We are targeting
consumer smartphones.

1. Is there a tested handset matrix for eSIM install **and** VoLTE — iOS and
   Android, by model and OS version?
2. Are there known-incompatible handsets, or handsets where data works and voice
   does not?
3. Does VoLTE require any carrier bundle, MCC/MNC entry, IMS profile or
   device-side configuration that a consumer cannot perform themselves?
4. Dual-SIM handsets: any known issues when your profile is the secondary line?
5. What does the customer see as the network name — is `whitelabel_name` (SPN)
   displayed on both iOS and Android?

## 6. Calls to Nigeria — complete cost

No mobile-voice per-minute rate is published on
[telnyx.com/pricing](https://telnyx.com/pricing) or
[pricing/mobile-voice](https://telnyx.com/pricing/mobile-voice), so we need a
rate deck. For calls **to Nigeria** from a Telnyx mobile line, please state:

1. Per-minute rate to Nigerian **mobile** networks, by operator if it varies.
2. Per-minute rate to Nigerian **landline**.
3. Connection/setup fee per call, if any.
4. Billing increments (per second, 6/6, 60/60?) and minimum duration.
5. **Inbound** call charges to the assigned number.
6. How rates differ by the originating (visited) network — specifically for our
   candidate test journeys: Nigeria→Nigeria, Saudi Arabia→Nigeria, UK→Nigeria.
   These are test candidates, not confirmed markets.
7. Any surcharge while roaming.
8. Data pricing by zone for the countries in §4.1.
9. Monthly recurring charges — we understand $2/month active and $0.20/month
   disabled or standby per SIM, and $0.70 per eSIM activation. Please confirm and
   state anything else recurring, including per-number monthly charges.
10. Taxes, regulatory fees and surcharges, by selling market.
11. Minimum commitments, ramp requirements or volume tiers.
12. Rate-change notice period.

## 7. Spending controls — enforcement, not alerts

We are selling a **prepaid** product. A customer must not be able to spend past
their balance, including while the app is closed or the device is offline.

Your documentation covers a `data_limit` on SIM card groups, with SIMs entering
`data_limit_exceeded`, and separately covers usage alerts which appear to be
informational.

1. Is `data_limit` enforced **network-side**, independent of any action by us?
2. What is the enforcement latency, and what worst-case overshoot should we
   budget for?
3. Can a data limit be set **per SIM** rather than per group, at scale?
4. **Is there any equivalent hard limit for voice — a spend cap, minute cap or
   balance?** We found none documented. If none exists, what do you recommend
   for a prepaid consumer product, and what is the maximum exposure on a single
   long international call?
5. Can we suspend a line in near-real time, and what is the propagation delay?
6. What happens to a call already in progress when a limit is hit?

## 8. Usage records and reconciliation

1. What is the latency between usage occurring and it appearing in Wireless
   Detail Records?
2. Do WDRs carry a stable unique record identifier we can deduplicate on?
3. Can records be **restated or corrected** after first publication, and how are
   corrections signalled?
4. What is the retention period for WDRs?
5. **Is there any CDR or usage record for mobile voice?** We found none
   documented. If so, what are its fields, latency and identifiers?
6. Is `current_billing_period_consumed_data` a cumulative counter, and how does
   it behave across billing-cycle boundaries?

## 9. Provisioning idempotency and recovery

`POST /actions/purchase/esims` accepts `amount` and returns `202` with the
created SIMs. We can find no idempotency key.

1. Is there any idempotency mechanism — a header, a body field, or server-side
   dedup — on eSIM purchase?
2. If our request times out after you accepted it, what is the correct
   recovery procedure? We plan to tag each purchase with a unique
   `tags` value and reconcile via `GET /sim_cards?filter[tags][]=...`.
   **Is that reliable, and are tags on newly created eSIMs immediately
   consistent for that filter?**
3. Are there rate limits on purchase, and what response signals them?
4. Error `70001` ("There aren't enough available SIM cards") — how often does
   this occur in practice, is there an inventory-reservation mechanism, and can
   we query available inventory before purchasing?
5. Can a partially-successful purchase be identified reliably from the `errors`
   array?

## 10. eSIM lifecycle and device replacement

Your documentation states eSIM activation codes are one-time use and that a lost
profile requires a new eSIM purchase.

1. Is there **any** supported path to reinstall a profile on a replacement or
   factory-reset device without a new purchase?
2. If not, is there a reduced-cost replacement or a goodwill mechanism? This
   directly determines what we can promise a customer who loses a phone.
3. Can a number be retained across a profile replacement, so the customer keeps
   their number after replacing a device?
4. What is `esim_installation_status` and what are its values?
5. Can a profile be moved between devices at all?

## 11. Number policy

1. In which countries can you assign a Mobile Phone Number?
2. What KYC, address or regulatory evidence is required, and from whom — us or
   the end customer?
3. Can a customer **port a number out** later, and can we port a number **in**?
4. Can a Nigerian (+234) number be assigned or ported in? We are **not**
   requesting third-party caller-ID presentation — only whether a +234 number
   can be issued or ported onto the line.
5. What happens to the number when a SIM is disabled, deleted or replaced?

## 12. Resale and commercial

1. Confirm we may resell eSIM **and** voice under our own brand to consumers and
   to enterprise customers, in the markets from §4.
2. Any restriction on selling to government or public-sector customers?
3. What contract, KYC and compliance obligations fall on us as the reseller —
   lawful intercept, emergency calling, number registration, data retention?
4. **Emergency calling:** what obligation applies to our customers' lines in each
   market, what does Telnyx provide, and what must we provide? We need this
   answered per market before selling there.
5. What are your termination and data-portability terms if we migrate away?

## 13. What we would like next

1. A **test account** with eSIM and VoLTE enabled, and an agreed non-production
   test scope with a spending cap.
2. A **rate deck** covering §6.
3. The **coverage matrices** in §4.
4. A technical call with solutions engineering on §§3, 7 and 9.

We are not asking for a commercial commitment at this stage and are not
authorised to place a paid order under this enquiry.

Thank you,

`[[FOUNDER NAME]]`
`[[ROLE]]`
`[[ENTITY — leave blank until D3 is decided; do not name an entity that does not exist]]`
`[[CONTACT]]`

---

## Pre-send checklist

- [ ] Every `[[PLACEHOLDER]]` filled or deleted; no guessed volumes or dates
- [ ] §1 corrected by the founder; no invented forecast sent
- [ ] Entity naming consistent with D3, or omitted entirely
- [ ] Markets in §4 consistent with D2, or stated as undecided
- [ ] Confirmed no order, commitment or payment is implied anywhere
- [ ] Founder has approved sending, and to whom
- [ ] Answers, once received, recorded in [`../DECISIONS.md`](../DECISIONS.md)
      under D1 with date and artifact — not summarised into code comments
