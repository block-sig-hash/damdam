# D1 closure checklist — Telnyx carrier and internet calling

Prepared 27 September 2026. D1 is **OPEN**. This checklist coordinates the
evidence needed to close it. Founder authorization to send the two enquiries
was recorded on 27 September 2026; that authorization does not extend to
account creation, spend, provisioning or calls.

### Founder input recorded 27 September 2026

- Accountable contact: Ibrahim Adamu, Tech Lead. The approved business email is
  retained outside this public repository.
- Initial candidate market: Nigeria. Later expansion was described as other
  West African and Muslim-majority countries; exact countries remain a D2
  decision and must not be represented as an approved catalog.
- Commercial input: projected first-year annual customer revenue of USD 50,000.
- Target launch: November 2026.
- Telnyx account: none. Enquiry authorization does not authorize creating one,
  accepting terms, adding payment details or incurring spend.
- Outreach: the founder authorized sending both D1 enquiries. The current
  official recipient is `sales@telnyx.com`; delivery still requires the
  approved mail account.

## 1. Founder inputs and outreach authorization

- [x] Founder name, role and business contact approved for the enquiry.
- [x] Honest first-year revenue forecast and target launch window supplied.
- [x] Initial candidate selling market identified; physical-test markets and
      later countries remain to be selected under D2, and all are
      candidates, not approved catalog entries.
- [x] Legal entity omitted until D3 closes, or the actual approved entity used.
- [x] Founder approves sending to `sales@telnyx.com` the separate
      [carrier/mobile-voice enquiry](ENQUIRY-DRAFT.md) and
      [internet-calling enquiry](../voice/ENQUIRY-DRAFT.md).
- [ ] The sent message and every written response are retained in the
      restricted evidence store with date, sender/recipient and an immutable
      digest; no credentials or customer data enter this repository.

## 2. Written supplier evidence

Carrier/mobile-voice responses must establish:

- [ ] Consumer and enterprise/government resale eligibility for the actual D3
      entity and candidate markets.
- [ ] Same-profile eSIM data and native inbound/outbound voice, by market,
      visited network/PLMN, IMSI and supported handset/OS.
- [ ] Number availability, KYC/address requirements, replacement/portability,
      roaming/permanent-roaming and emergency-service obligations.
- [ ] Applicable contract, SLA, support, API stability and deprecation terms.
- [ ] Complete Nigeria mobile/landline rate deck: recurring charges, assigned
      number, carrier/SIP components, increments, minimums, connection fees,
      roaming, taxes, commitments and rate-change notice.
- [ ] Network-side data and voice spending controls, reaction/overshoot bounds,
      in-progress-call behavior and suspension propagation time.
- [ ] WDR/mobile-voice CDR schema, stable identifiers, availability latency,
      corrections/restatements, retention and invoice correlation.
- [ ] Purchase accepted-but-response-lost recovery and tag consistency.

Internet-calling responses must close B1–B5:

- [ ] Copied credential containment, direct PSTN denial, emergency-routing
      denial and signed per-device event identity (**B1**).
- [ ] Nigeria rate, invoice/CDR components, increments and fees (**B2**).
- [ ] Provider-enforced abandoned-leg, call-duration, hangup and spend bounds
      sufficient for the offered prepaid promise (**B3**).
- [ ] Nigeria/account verification, resale and caller-identity eligibility
      (**B4**).
- [ ] Supported React Native/iOS/Android/browser versions and expected audio,
      DTMF and background behavior (**B5**, subject to physical proof).

## 3. Capped test-account evidence

The founder approves the account owner, secret custody, exact maximum spend,
test identities, destinations and stop authority before any probe. API keys,
activation material, full phone numbers and payment details stay in the
approved secret/evidence systems.

- [ ] Record account verification level, enabled products, connection/profile
      IDs as opaque references, account rate-card version and configuration
      digest.
- [ ] Read-only contract probes confirm Mobile Voice Connections, Mobile Phone
      Numbers, eSIM purchase/list, WDR/CDR and pricing capabilities available
      to this account.
- [ ] One authorized eSIM purchase proves durable operation correlation and
      accepted-but-response-lost reconciliation without a duplicate purchase.
- [ ] Assigned number and native voice activation converge through real events;
      no application state claims installation or connectivity prematurely.
- [ ] Data usage, limit/suspension timing, WDR latency, replay and correction
      behavior are measured and reconciled to invoice/ledger records.
- [ ] Native-voice CDR identity, rate components, latency, correction behavior
      and termination/spend bounds are measured.
- [ ] WebRTC credential containment, parking, emergency denial, Nigeria route,
      all-leg CDRs, cutoff bounds and copied-credential rejection are measured
      before either internet-calling channel is enabled.

## 4. Physical and commercial confirmation

- [ ] The approved chunk 29 physical-device run proves eSIM install, Wi-Fi-off
      data and native-dialer calls on supported iOS and Android devices.
- [ ] Separate mobile/browser runs prove SDK installation, audio routing,
      microphone denial, DTMF, interruption/background behavior and charging.
- [ ] Finance reconciles supplier usage/CDRs and invoices to DamDam ledger and
      customer receipts with no unexplained variance.
- [ ] Legal/product approve the exact market, number, emergency, disclosure and
      customer-contract position; D2–D5 are not inferred from D1 evidence.

## 5. Closure rule

D1 may move to **CLOSED** only when `DECISIONS.md` names the accountable owner,
decision, date and immutable locators/digests for the written response, account
configuration, rate deck and completed probes. Partial answers close only their
named rows. Any unsupported channel remains fail-closed and receives an
explicit `DISABLED` release decision with negative eligibility tests.
