# Chunk 29 physical and enterprise pilot — operator runbook

Prepared 24 September 2026. **Not authorized to execute.** The founder has
not supplied an approved EAS project, Apple/Google signing identities,
consenting physical-device testers, live carrier/merchant pilot approval or a
spending limit. Use [blank evidence forms](29-PILOT-EVIDENCE.md); do not turn
this checklist into a claim that any test has run. An old `EXPO_TOKEN` secret
or a queued cloud build is not a release-owner approval.

## 0. Stop/go and custody

The release owner names a pilot lead, security/privacy reviewer, support
contact and finance reconciler. Before any build or invitation, record written
approval of the EAS organization/project ID, source commit, build profile,
iOS bundle ID/team/certificate/profile, Android package/upload certificate,
approved fingerprint, testers and distribution channel. Keep credentials in
the approved account/secret manager; never paste them into issues, logs or this
record. The on-demand [EAS workflow](../../../.github/workflows/eas-verify-build.yml)
does not submit to stores. The production Android build requires
`DAMDAM_RELEASE_CERT_SHA256` to match the release-owner-approved certificate;
EAS can inject the keystore into the bare app's release signing config.
However, an EAS-shaped task-callback fixture hit Gradle 9.3.1's finalized
`storeFilePath` during CI preparation. Do not assume the current EAS-generated
script works on this Android toolchain. Before an authorized cloud build, the
release owner must choose and review a compatible credential path; the
repository has **not** set `withoutCredentials` or selected a signing identity.
An actual EAS build and AAB signature inspection are required to close this.

Separately, the founder or delegated commercial owner must approve the exact
carrier/merchant accounts, legal seller, countries, plans and rate versions,
maximum pilot spend and exposure, refund path and stop authority. D1–D6 and
V01 B1–B5 are not waived by access to a build. Do not buy, provision, invite,
place calls or collect customer data until the specific approvals are recorded.
If a prerequisite is absent, record `BLOCKED` and stop at that gate.

## 1. Verify cloud signing, then internal distribution

1. Pin the source SHA, EAS CLI/profile, native project configuration, app
   version/build number and approved project ID. Confirm `com.damdam.app` is
   the intended iOS bundle ID and Android package in the approved accounts.
   Record the cloud build ID, platform, profile, artifact checksum and log
   location. Do not publish URLs containing access tokens.
2. With approved remote credentials, run the manual iOS and Android EAS
   builds on that exact SHA. Verify success, then independently compare the
   exported IPA's distribution team/certificate/provisioning and entitlements
   and the AAB's upload-certificate fingerprint to the approved identities.
   A successful EAS job without this comparison is `UNVERIFIED`.
3. Confirm the current native CI jobs on the same source/configuration: actual
   iOS simulator and Android emulator flows, counts and artifacts. Native CI
   supports software verification only; it is not physical carrier proof.
4. Only after release-owner distribution approval, configure App Store Connect
   TestFlight internal testing and Google Play internal testing in their
   approved accounts. Invite only named consenting testers; record invitation
   acceptance and physical install against build number and device/OS. Do
   not infer an install from a delivered invitation. Use the approved Play
   testing track and TestFlight groups; no public release or production store
   rollout is part of this runbook.

Platform procedures: [EAS Build for existing React Native projects](https://docs.expo.dev/build/),
[EAS existing credentials](https://docs.expo.dev/app-signing/existing-credentials/),
[Apple internal TestFlight testers](https://developer.apple.com/help/app-store-connect/test-a-beta-version/add-internal-testers),
[Google Play internal testing](https://support.google.com/googleplay/android-developer/answer/9845334?hl=en-GB).
Check current platform instructions immediately before use.

## 2. Physical consumer test, per approved market/device/offer

Reserve a fresh test identity and capped payment method. Record only synthetic
or consented identifiers in the restricted evidence store; reference records
by opaque IDs here. The pilot lead records device model/OS, eSIM capability,
dual-SIM state, visited network, country, date/time, tester and build. Run each
advertised carrier offer on at least one approved physical iOS and Android
device; record unsupported combinations as **not offered**, not passed.

1. Capture catalog offer and immutable quote: market, plan/rate version,
   currency, taxes/fees, data/voice terms, expiry and seller. Complete an
   authorized purchase; correlate merchant authorization/capture, order,
   ledger reservation/posting, supplier operation and receipt without exposing
   payment instrument or activation payload.
2. Provision exactly once. Install via QR and manual fallback where offered;
   check failed/retried installation on a disposable profile if carrier policy
   allows it. Verify device-reported install independently of supplier status.
   Check dual-SIM/default-data selection and customer recovery after an
   interrupted install. Stop immediately if a duplicate profile or charge
   appears.
3. Turn Wi-Fi off and consume cellular data on the installed eSIM. Record
   device counters and a bounded timestamped traffic proof, supplier usage
   event time/ingest time, customer balance display, lag and ledger posting.
   Compare invoice/rate-deck/settlement with ledger; investigate every
   discrepancy. Test a top-up and spend cap only if that capability is actually
   approved and the supplier enforces it. Never call an app-side warning a
   hard carrier cutoff.
4. With DamDam **closed**, dial the approved Nigeria mobile and landline
   destinations from the native dialer where advertised. Confirm line/CLI,
   selected SIM, ringing, two-way audio, DTMF and termination; record call
   duration, carrier CDR, rated amount, taxes/fees and ledger amount. Test a
   controlled poor-connectivity/interruption case and recovery, not an
   emergency destination. Inbound/caller-ID checks apply only where sold.
5. Treat app/browser internet calling as separate V01–V05 capability gates.
   Do not use a native-call result to certify internet audio, or vice versa.
   Capture route, quote, all-leg charges, authorization, DTMF/audio and
   termination only after the separate live route is approved.

An adverse financial result, unsupported market/identity, privacy leak,
duplicate provisioning, unbounded exposure, missing call/data event or unsafe
recovery is a pilot stop. Pilot lead suspends further spend; support preserves
sanitized correlation IDs and finance reconciles/refunds under approved policy.

## 3. Enterprise administrator pilot

With a consenting representative organization and approved legal/funding
model, record admin MFA/tenant and employee-consent boundaries. Import a
de-identified pilot roster; verify valid, duplicate and rejected rows. Fund
through the approved merchant path, compare payment/ledger/receipt, and place
a capped bulk order with a deliberate partial failure. Confirm no duplicate
supplier purchase, allocation or cross-tenant visibility. Have a consenting
employee install on a physical device, then compare line/usage/spend report to
supplier and ledger data. Offboard one employee and confirm actual carrier
suspension, remaining balance/refund disposition, access revocation and audit.
If live funding, supplier suspension or legal entity is not approved, mark the
individual step `BLOCKED`; a dashboard fixture does not count as pilot proof.

## 4. Reconcile and hand off

The pilot lead completes one [evidence form](29-PILOT-EVIDENCE.md) per build,
device/offer scenario and enterprise run. Link restricted raw artifacts by
opaque locator, record reviewer and time, and redact phone numbers, ICCIDs,
activation codes, tokens, payment details and customer content. Finance signs
off supplier-to-ledger-to-merchant variance or records an unresolved defect.
The release owner maps every finding to a fix and exact retest SHA. Chunk 30
must reject readiness while any mandatory gate, incompatible artifact or
blocking defect is open. EAS builds, generic labs and CI simulators/emulators
never replace real eSIM installation, cellular data and native-call evidence.
