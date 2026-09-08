# Pre-Pilot Checklist

> **Current scope:** the September 2026 reset in the closing product-reset amendment and
> [PRD §10](prd.md) governs conflicts with earlier text. Use the
> [scope disposition](implementation/SCOPE-DISPOSITION.md) and
> [decision register](implementation/DECISIONS.md) for retained, retired
> and proposed behavior. These are target requirements; existing code and
> supported transition paths remain subject to their applicable checks.

Every item below was flagged individually, in its own PR description or spec
section, across the project's build history — nothing here is new work being
proposed; this document only consolidates gaps that were already identified
and puts them in one place someone can actually check against before
declaring the product ready for a real Hajj-season pilot. It does not
replace `testing-qa.md`, `security.md` §10.10, or `infrastructure.md` — it
cross-references them so this is the *one* document to work from, not a
fourth scattered list.

**How to use this:** every item has a concrete "done" condition. None of
them are satisfied by simulator/emulator output, mocked vendor SDKs, or unit
tests alone — those are already-completed evidence tiers (see each story's
PR for that), not what's tracked here.

**Last refreshed:** 2026-07-28, against `develop` @ `ceabce8` (through PR
#98's English/French localization implementation and PR #81's runner-history
documentation). The refresh adds localization release gates, reconciles the
completed cross-manifest HTO home work, and rechecks deployment state rather
than carrying the 2026-07-26 branch/secrets snapshot forward.

## Pilot release-candidate control

The implementation is now under a pilot feature freeze. The annotated Git tag
`v0.1.0-rc.1` designates the merge commit of the PR that introduced this
control. It means **code-complete candidate for staging and real-device
validation**; it does not mean production-approved, store-approved, or
pilot-ready. Do not move the tag after creation. Any later candidate is a new
incrementing tag (`v0.1.0-rc.2`, and so on).

Until the first pilot release reaches `main`, changes are limited to:

- P0/P1 correctness, safety, security, privacy, accessibility, or data-loss
  fixes;
- CI/release-pipeline fixes and dependency updates required to produce or
  validate signed builds;
- staging/production configuration, vendor integration, monitoring, backup,
  restore, compliance, localization-review, and release-evidence work; and
- copy or layout corrections found by native-language, legal, HTO-usability,
  or physical-device review.

New product features, speculative refactors, visual redesigns, and post-MVP
scope stay deferred. An exception must name the pilot blocker it resolves in
the PR description. `.github/PULL_REQUEST_TEMPLATE.md` exposes this
classification on every PR. Every accepted change reruns the relevant release
gates and cuts a new RC tag; an existing RC tag is never rewritten.

**Tied to a real enforcement mechanism now, not just a document:** since PR
#91 (`infrastructure.md` §11.14), a `staging → main` PR cannot merge without
a `docs/release-signoffs/<sha>.md` file (template:
`docs/release-signoffs/TEMPLATE.md`) whose device-matrix and
critical-scenario tables map directly onto this document's
§2/§3/§4/§6/§7/§10 —
`main`'s branch protection genuinely blocks the merge button on a missing or
placeholder-filled signoff, confirmed by attempting real broken PRs. That
gate does not verify the *content* is honest (photo/video evidence isn't
required yet — see the template's own note on when that changes), but it
does mean this checklist's real-device items are now mechanically forced
into every release's attention, not something that can be quietly skipped.

---

## 1. Push / notification delivery

| Item | Source | Done looks like |
|---|---|---|
| FCM/APNs push delivery on real devices (arrival + date-triggered eSIM activation prompts) | US-13, PR #64, `testing-qa.md` §14.3 | A real push notification observed arriving on at least one physical iOS and one physical Android device, not a mocked payload assertion |
| Production FCM topic subscription + live delivery to a subscribed browser | US-19, PR #70 | A real Firebase project's `hto-{organization_id}` topic sends a message that a real subscribed browser (not a headless test) visibly receives, via the dashboard's `firebase-messaging-sw.js` |
| HTO SOS push delivery through live Meta/Resend/FCM accounts | US-16, PR #68 | One real SOS alert dispatched through all three channels against production (or production-equivalent) vendor accounts, with delivery confirmed on the receiving end, not just a 200 from the vendor API |
| `FIREBASE_ACCESS_TOKEN` live rotation | US-16, PR #68 | The short-lived FCM HTTP v1 OAuth token is refreshed by a real deployment process at least once without manual intervention — "not testable locally" per the PR, so this can only be closed against a real deployment |
| Real device-token registration end-to-end (`PUT /me/device-token`) | US-13, PR #64 | Firebase/Apple runtime configuration (recorded as "deployment-secret work, not committed configuration") is actually present in a deployed environment and a real device successfully registers a token against it |

*Operational note (PR #89):* the admin dashboard's Failed Notification Queue
(`/admin/sos-notifications`) now exists, so once real delivery attempts are
happening against a deployed environment, failures in the above are
observable and retriable from the dashboard rather than only from logs —
doesn't close any row above by itself, but is the tool you'd use while
closing them.

## 2. Voice / PSTN (US-14)

Items below are from `testing-qa.md` §14.9's own explicit "Required
real-device / real-network evidence before an HTO pilot" list, plus PR #66,
updated for PR #87 (iOS CallKit/PushKit), PR #88 (Android ConnectionService),
and PR #96 (Verified Caller Identity CLI hardening).

| Item | Done looks like |
|---|---|
| One real Telnyx-account PSTN call | One actual outbound PSTN call placed per platform over real cellular/eSIM data, confirming the recipient sees the verified Nigerian CLI and the call reaches Telnyx's signed webhook endpoint — logged, not simulated |
| Real call quality | Call quality observed on at least 4G, on degraded/packet-loss cellular data, and through a forced mid-call network drop, with the in-app quality indicator compared against actual audible behavior, and confirmation that only connected seconds are billed |
| CallKit (iOS) / ConnectionService (Android) native integration | Native call UI and audio routing verified on physical iOS and Android hardware, including background/lock-screen behavior, microphone, mute, speaker, and Bluetooth routes — not the mocked Telnyx SDK transitions already covered in CI. This is the exact evidence `docs/release-signoffs/TEMPLATE.md`'s critical-scenario table now requires a PASS/FAIL on for every release: incoming call wake from killed/backgrounded state (both platforms), CallKit lock-screen UI, PushKit delivery |
| Android incoming-call wake — specific disclosed risks (PR #88) | Four named uncertainties the PR itself flagged as real-device-only, not oversights: (1) FCM payload key names (`call_id`/`voice_sdk_id`/`metadata`) used to detect an incoming call are inferred from Telnyx's JS SDK source, never confirmed against a live Telnyx-delivered push; (2) the manually-added `VoiceConnectionService` entry in `AndroidManifest.xml` is unverified against a real Android Telecom framework bind (fails silently either way — no crash signal either direction); (3) `RNCallKeep.setup()` and its phone-account permission prompt only run once Dial Pad has been opened at least once on that device — until then ConnectionService cannot display an incoming call at all, a device-state dependency with no iOS equivalent; (4) the Headless-Task-to-live-app JS context handoff for a cold-start incoming call has never been verified end-to-end. All four require a physical Android device and a real incoming PSTN call |
| Contextual Contacts permission | Verified on both physical platforms, including a denial path and a later Settings re-enable |
| **Verified Caller ID phone-possession flow (PR #96, US-14 CLI hardening)** | One real Telnyx Verified Numbers SMS code actually delivered to a real Nigerian number, entered in the app, and confirmed — end-to-end through `POST /voice/cli/verify` → `/confirm` → `/consent` on a physical device — not the `FakePhoneVerificationProvider` test double CI uses. New since the previous version of this document; not yet run against any real Telnyx account |
| iOS native project generation | **Resolved by PR #87** — `apps/mobile/ios` now exists with CallKit/PushKit wired; no longer blocking. Superseded by the EAS build-credential row below, which is the current blocker on getting a real signed build onto physical hardware |
| **EAS iOS build — non-interactive distribution credentials** | Every recorded `eas-verify-build.yml` attempt visible as of 2026-07-28 remains red; the iOS attempts fail with `Distribution Certificate is not validated for non-interactive builds` / `Credentials are not set up. Run this command again in interactive mode.` Someone with Apple Developer account access needs to run `eas credentials` interactively once to provision a distribution certificate/profile EAS can reuse non-interactively; until then, no real signed iOS build has been produced after PR #87. Ibrahim-owned, same category as the OCI/DNS items in §8 |
| EAS Android build — never attempted | No recorded `eas-verify-build.yml` run targets Android. Unlike iOS, Android EAS builds can create a managed keystore, so this is a smaller gap — but a signed AAB must actually build and install from the Play internal-testing track before this row closes |

## 3. Check-in / offline queue (US-15)

Source: US-15 PR #67, `testing-qa.md` §14.3, §14.4.1, §14.4.3.

| Item | Done looks like |
|---|---|
| Real device force-quit / reboot of the SQLite outbox | A check-in triggered offline, the app force-quit before sync, then the device rebooted — on a physical device, not an emulator — with the queued check-in still present and still syncing on relaunch |
| Actual Meta WhatsApp delivery confirmation | A real WhatsApp template message sent and its delivery receipt observed from Meta's live API, not the signed-webhook simulation already covered in CI |
| Actual Termii family SMS fallback | A real SMS delivered through Termii's live API when the 60-second WhatsApp delivery window is exercised for real (not the deterministic 59s/60s boundary test already in CI) |
| Poor cellular / eSIM network testing | The intermittent-connectivity scenario (§14.4.1 — connection dropping every few seconds, matching the actual Mina/Arafat scenario) exercised on a real device over real degraded cellular/eSIM data, confirming no duplicate check-ins are created |
| OS background-wake timing | The exact 30-second retry cadence is only proven deterministic while the JS runtime is alive (fake timers in CI); real OS background-wake timing (`react-native-background-fetch`, ~15-minute iOS minimum, Android scheduler deferral) must be observed on real devices, not inferred |
| OEM battery-management survival | Budget Android devices' aggressive process-killing behavior — the exact failure mode the offline queue exists to survive — verified on the actual target device profile (see §6 below), not a generic Android emulator |

Note: PR #86's US-23 session-persistence work (Keychain/Keystore-backed
token storage, 30-day inactivity lifecycle, background-time PIN-gate) landed
since the previous version of this document and touches the same
foreground/background lifecycle this section's offline queue relies on. No
new real-device gap is being asserted here beyond what's already listed
above — flagged only so whoever runs the §6 device matrix exercises both
paths together rather than assuming US-15's queue and US-23's session gate
were independently re-verified on hardware.

## 4. SOS (US-16)

Same categories as check-in above, plus SOS-specific items. Source: US-16
PR #68, `testing-qa.md` §14.4.2, §14.4.4.

| Item | Done looks like |
|---|---|
| Real iOS/Android airplane-mode, force-quit, device-reboot, OS scheduler matrix | Same real-device matrix as check-in (§3), run specifically against the SOS trigger/outbox path, not just check-in's |
| Real native dialer launch | `Linking.openURL('tel:...')` observed actually launching the native phone dialer on a physical device with a real number, confirming it is never the VoIP gateway |
| Outdoor accessibility / hold-gesture validation | The 3-second linear hold/countdown SOS trigger tested outdoors in realistic lighting/glove/stress conditions on a physical device — this is a UX-under-stress check, not a functional test |
| **Pre-Hajj-season load/chaos exercise** (`testing-qa.md` §14.4.2) | A dedicated exercise, run at least once before the real Hajj 2027 season: (a) a concurrent check-in burst simulating several hundred to a few thousand simultaneous requests (matching the ~1,500-pilgrim pilot-scenario volume) with no dropped requests or unacceptable latency; (b) concurrent SOS events fired *while* the API's own connectivity to WhatsApp/Twilio is degraded, confirming server-side retry/queue behavior degrades gracefully |
| **Tabletop exercise** (`testing-qa.md` §14.4.2, `security.md` §10.8) | An actual walkthrough with whoever will be operationally on-call during the real Hajj season, of "a pilgrim's SOS doesn't seem to have reached anyone, what do you actually do right now" — a human-process rehearsal, not a system test. This is the same tabletop referenced in `security.md` §10.10's "Incident response plan reviewed and tabletop-tested" line — one exercise satisfies both |

## 5. eSIM / geofencing (US-10, US-13)

Source: US-10 PR #62, US-13 PR #64, `testing-qa.md` §14.3.

| Item | Done looks like |
|---|---|
| Geofence delivery on real hardware | The 150km Jeddah arrival geofence (now backed by the real `destination_geofences` table + `GET /packages/{id}/geofence`, per §6.34) actually fires on physical Android hardware crossing the real boundary, including observed OS-level geofence throttling behavior — not the parametric-lookup unit test already covered |
| Carrier-managed eSIM switching | `EuiccManager`/`SubscriptionManager.canManageSubscription()`-driven single-tap switching confirmed working on real carrier-manageable Android hardware, including validated post-switch connectivity — this cannot be meaningfully emulated |
| Android device screenshot production (10–15 device models) | Real, physical-device-captured, verified screenshots for the Android activation guide across Tecno Camon/Spark, Infinix Hot/Note, itel, and Samsung Galaxy A-series (`frontend-mobile.md`'s Screen 19 spec), with matching English/French walkthrough assets captured on the same OS version. As of PR #98, the translated guide frame is real but the OS-image slots remain placeholders — this is a **content production task**, not an engineering one, and should be scoped as its own workstream per `frontend-mobile.md` and `localization.md` |
| Full eSIM download → QR fallback → activation flow | End-to-end on each of the physical devices above — `testing-qa.md` §14.3 explicitly states this "cannot be meaningfully emulated" |
| Device Compatibility Warning path on iOS | Confirmed actually firing correctly (AC-10.3) on at least one non-eSIM-capable or older physical iPhone, per `testing-qa.md` §14.3's two-iPhone requirement |

## 6. Physical device matrix (cross-cutting)

Source: `testing-qa.md` §14.3, referenced by nearly every item above, and
now also the required "Device matrix tested" table in
`docs/release-signoffs/TEMPLATE.md`.

**Required before pilot launch — same physical device set used across §2–§5:**

| Platform | Devices |
|---|---|
| Android | Tecno Camon (recent generation), Infinix Hot/Note (recent generation), itel (current budget model), Samsung Galaxy A-series |
| iOS | One eSIM-capable iPhone (XS or later), one non-eSIM-capable or older iPhone still in reasonable use |

**Done looks like:** every item in §2–§5 above that says "real device" has
actually been run against this specific device set, not a substitute device
or an emulator/simulator claiming to represent it — and, since PR #91, the
actual model/OS-version tested is recorded in the release signoff for the
commit being promoted to `main`, not just asserted informally here.

## 7. HTO dashboard usability (US-05 family, `testing-qa.md` §14.5)

| Item | Done looks like |
|---|---|
| Usability testing with an actual HTO pilot partner | A real (or realistic proxy) operator attempts the manifest upload → order → monitor flow with minimal guidance, observed live, before general HTO rollout — qualitative, scheduled as its own milestone per §14.6, not assumed to happen informally |

Scope note: PR #89 added three admin/dashboard surfaces since the previous
version of this document (Failed Notification Queue, cross-manifest HTO
Home, Device Compatibility Log) — all fully unit-tested, none flagged by
their own PR as needing real-partner evidence the way the manifest-upload
flow above is. Not adding a new row for them; noting so the usability
session's scope is understood to be the current dashboard, not the
narrower one this document originally described.

## 8. Infrastructure / deploy pipeline pre-promotion

Baseline: PR #79 (deploy pipeline, merged 2026-07-19). Updated for PR #82
(WAL-G PITR), PR #84 (self-hosted Kuma), and PR #91 (three-branch promotion
gate) — all merged since, all directly changing what's actually still open
in this section.

| Item | Done looks like |
|---|---|
| Isolated staging OCI host provisioned | A real staging OCI instance exists and is reachable. **Still open as of 2026-07-28:** the `staging` and `production` GitHub Environments both exist with zero secrets, and no staging health check has succeeded. Staging and production remain separate hosts/environments per `infrastructure.md` §11.1; co-hosting them does not close this isolation gate |
| Staging GitHub Environment secrets configured | All four named secrets (`STAGING_OCI_HOST`, `STAGING_OCI_DEPLOY_USER`, `STAGING_OCI_SSH_KEY`, `STAGING_API_BASE_URL`) are set in the `staging` GitHub Environment — the workflow's own preflight check currently fails because all four are absent. This also blocks the `staging` branch from advancing past its bootstrap commit |
| `/opt/damdam/.env.staging` created | Real staging environment file present on the staging host, not the committed `compose.env.example` placeholder |
| First production Compose release manually bootstrapped | Explicitly documented as "manual and Ibrahim-owned" (PR #79) — automated production deploy refuses to proceed without a prior image to preserve as a rollback target, so this is a hard prerequisite, not automatable |
| Cloudflare tunnel / DNS configured for production | Real tunnel token and DNS records in place — `compose.env.example`'s `CF_TUNNEL_TOKEN` is a placeholder (`replace-with-a-real-cloudflare-tunnel-token`) |
| Production secrets supplied | Real values for every secret currently placeholder/example-only across `.env.example` and `compose.env.example` |
| `ESIM_ACCESS_PACKAGE_CODES` format migration | From PR #78 (merged 2026-07-18): the eSIM Access package-code config changed from integer keys to destination-composite keys (`{"SA:5":"SA_5GB"}`), and `Settings` now refuses to boot on the old format. **Done** looks like: production/staging's real env var confirmed in the composite format, and a real deploy (or `Settings()` construction against the real production values) boots cleanly — i.e. the startup validator has actually run against the real value |
| **`develop → staging → main` promotion has never been exercised for a real release** | As of 2026-07-28, `develop` is 7 commits ahead of `staging` and 75 commits ahead of `main`; `main` remains at the initial spec-suite commit. `deploy-staging` has never passed against a real host, so `staging` has not advanced since its bootstrap. The promotion tooling and signoff gate are built and proven to block a bad merge, but no application commit has traversed the real path end-to-end. This is blocked on staging infrastructure/secrets, not another application feature |
| WAL-G real restore drill against a real backup | PR #82 built and proved the mechanism against local MinIO (`scripts/test-walg-pitr.sh`) — archiving, recovery-target-time-scoped replay, and the runbook are real and tested. **Explicitly out of scope per `infrastructure.md` §11.12, not done**: provisioning the real R2 bucket, injecting its restricted credentials, and an actual point-in-time restore against production/staging data. This is a genuine restore-drill gap, distinct from "the mechanism works," and needs Ibrahim/the incident owner |
| Kuma monitoring configured and alerting confirmed working | **Updated — the alert path itself is now done, per `infrastructure.md` §11.13**: self-hosted Uptime Kuma is deployed and isolated on Hermes; both the API readiness monitor and the WAL-G push/heartbeat monitor were proven with *real induced failures* (a real monitor stopped and confirmed Down, a real heartbeat withheld and confirmed timing out to Down), and the exact configured Telegram bot/chat was independently confirmed to deliver a real message. **What's left is the same staging/production host-provisioning gap already tracked above** — the readiness monitor will legitimately show Down until `api.damdam.app` resolves; that is not a Kuma problem, and re-confirming the alert path after the first real deploy is a re-confirmation, not new work |

## 9. Compliance (cross-reference, not duplicated)

The full checklist lives in `security.md` §10.10 — do not maintain a second
copy here. Flagging the two items with the most real-device/pilot-timing
overlap with this document:

- Incident response plan reviewed and tabletop-tested — **this is the same
  exercise as §4's pre-Hajj tabletop above**; one run satisfies both, don't
  schedule it twice.
- Apple App Store / Google Play privacy label and data safety disclosures —
  timing-sensitive against §5/§6's physical-device work, since submission
  review can be rejected/delayed if disclosures don't match `security.md`
  §10.2's data classification exactly.

`security.md` §10.10's data-retention-automation row moved from unchecked to
`[x]` since the previous version of this document (PR #85) — independently
re-verified with real Postgres boundary tests and a genuine concurrency race
test, not just marked done. Everything else in §10.10 (privacy policy, ToS,
processor DPAs, NDPA filing) remains open and is pure legal/business work,
not re-summarized here — see that section directly.

## 10. English/French localization (PR #98)

PR #98 implemented locale persistence and English/French rendering across the
mobile app, dashboard, API responses, native resources, and outbound
notifications. Catalog parity, frontend/backend tests, and the Android
32-artifact screenshot matrix are implementation evidence; they do not close
the human-language, legal, vendor-account, or final-content gates below.

| Item | Done looks like |
|---|---|
| Native Francophone language review | A named native Francophone reviewer familiar with West African usage reviews the complete French mobile/dashboard catalogs and notification output, corrections are merged, and the approving review is linked from the release signoff |
| French safety and legal review | SOS, emergency phrases, check-in, OTP, activation, Caller ID consent, privacy, emergency limitations, and family-notification basis are approved by the responsible safety/product and legal reviewers; later changes to approved text require a new recorded review |
| French vendor templates approved and delivered | Every French Meta template is approved in the production account, Termii/Twilio/Resend/Firebase output is exercised with a French recipient, and account-level delivery is observed rather than inferred from mocked provider tests |
| Bilingual visual and final eSIM-content approval | Android and iOS each produce all 32 English/French CI artifacts, a reviewer signs off wrapping/truncation/accessibility on both matrices, and the placeholder eSIM OS walkthrough frames are replaced with matching final English/French assets |

---

## Summary

**47 distinct checklist rows** (up from 43) consolidated into the 10
categories above. §6's 2 rows are the physical-device roster itself —
cross-cutting infrastructure that §2–§5's "real device" items depend on, not
a separate set of gaps on top of them. The four new rows are PR #98's
explicit human-language, safety/legal, vendor-delivery, and visual/content
release gates; no previously-completed engineering work was reclassified as
unfinished.

**What changed in this refresh (2026-07-26 → 2026-07-28, PR #96 → #98):**
- added the pilot feature-freeze and `v0.1.0-rc.1` candidate convention;
  the tag means code-complete for staging/physical-device validation, not
  production approval
- §2 refreshed EAS evidence without retaining a stale run count; signed iOS
  credentials remain blocked and Android EAS remains unattempted
- §5 now requires matching final English/French eSIM walkthrough assets
- §8 rechecked GitHub directly: both environments still have zero secrets,
  `develop` @ `ceabce8` is 7 commits ahead of `staging` and 75 ahead of
  `main`, and no real staging deployment has succeeded
- §10 adds PR #98's localization release gates; the 2026-07-28 iOS nightly
  produced 30/32 artifacts because only `sos-confirm` failed to reach its
  off-screen harness target, and the release-candidate PR adds the missing
  bounded scroll before the target on both locales
- issue #19 was closed after verifying PR #89's cross-manifest HTO home
  against all seven US-18 acceptance criteria

**What changed in this refresh (2026-07-19 → 2026-07-26, PR #79 → #96):**
- §2: iOS native project generation marked resolved (PR #87); added
  Android's four specifically-disclosed incoming-call-wake risks (PR #88);
  added the Verified Caller ID SMS-verification real-device gap and the EAS
  iOS/Android build-credential gaps (all new, none previously tracked
  anywhere)
- §3: cross-referenced US-23's session-persistence lifecycle (PR #86)
  against the existing offline-queue foreground/background item
- §7: noted three new dashboard admin surfaces (PR #89) are in scope for
  "the current dashboard" without adding new usability-testing rows
- §8: added the never-yet-exercised `develop → staging → main` promotion
  (PR #91) as its own row — arguably the single most important "what's
  next" item now that every user story is implemented; added the WAL-G
  real-restore-drill gap (PR #82); updated the Kuma row from "needs
  confirming" to "alert path confirmed, blocked only on host provisioning"
  (PR #84)
- §9: data retention automation (PR #85) moved from open to done in
  `security.md` §10.10, noted here rather than re-listed as a gap
- Added the top-of-document note tying this checklist to the
  `docs/release-signoffs/` promotion gate (PR #91), which didn't exist at
  the previous refresh

Sources pulled from, directly:
- `testing-qa.md` §14.3 (device matrix), §14.4.1–§14.4.4 (check-in/SOS
  chaos scenarios + real-device boundaries), §14.5 (HTO usability), §14.9
  (voice real-device/real-account evidence)
- `security.md` §10.10 (compliance — cross-referenced, not duplicated)
- `infrastructure.md` §11.12 (WAL-G PITR), §11.13 (self-hosted Uptime Kuma),
  §11.14 (three-branch promotion and release signoff gate)
- `docs/release-signoffs/TEMPLATE.md` (the mechanically-enforced signoff
  structure this document's §2/§3/§4/§6/§7/§10 now feed into)
- PR descriptions: #62 (US-10), #64 (US-13), #66 (US-14), #67 (US-15), #68
  (US-16), #70 (US-18/19/22), #78 (destination-country Phase 3), #79
  (deploy pipeline), #82 (WAL-G PITR), #84 (self-hosted Kuma), #86/#88
  (US-23 session persistence + Android ConnectionService), #87 (iOS
  CallKit/PushKit + native project generation), #89 (dashboard admin
  surfaces), #91 (three-branch promotion), and the US-14 Verified Caller
  Identity CLI-hardening merge (`0fa3f53`, #96), and #98 (English/French
  implementation and release gates)
- `frontend-mobile.md` (Android screenshot content-production note) and
  `localization.md` §§6–7 (bilingual visual, language, safety/legal, and
  vendor-account gates)
- Direct GitHub evidence refreshed 2026-07-28: environment secret lists,
  branch comparisons, EAS workflow history, and nightly iOS run
  `30331585215` (15/16 flows, 30/32 artifacts, isolated `sos-confirm`
  failure)

**One item newly surfaced while compiling the original version of this
document, carried forward:** PR #78's `ESIM_ACCESS_PACKAGE_CODES`
key-format change needed an atomic production env-var update on deploy
(§8) — recorded as a deploy note inside PR #78 itself but not pulled into
any pre-pilot or pre-promotion checklist until the first version of this
document. `Settings` now refuses to boot on the old key format or on an
SA-less config, so the remaining pre-pilot work on that item is confirming
the real production/staging env var, not building anything further.

---

## Amendment — Superseded as a Gate by the Product Reset

**Recorded 8 September 2026 by build chunk 01. Registered story: US-27.**
Documentation only — `scripts/validate-release-signoff.sh`,
`.github/workflows/release-promotion.yml` and
`docs/release-signoffs/TEMPLATE.md` are **unchanged**; see "Known inconsistency"
below.

### Status change

`prd.md` §10 resets the product to global consumer and enterprise/government
connectivity. This checklist was written for a Hajj-season pilot of a product
with SOS, check-ins, family contacts, verified caller ID and WebRTC calling.

**Everything above is reclassified as historical.** It is retained as the record
of what was demanded for the old pilot and as a source of still-useful evidence
discipline. It is **not** the current release criteria, and no item above should
be worked, closed or cited as a current gate.

### The pilot feature freeze is lifted

The "Pilot release-candidate control" section above froze the implementation to
P0/P1 fixes and pipeline work ahead of a Hajj 2027 pilot. **That freeze is
lifted.** The user has explicitly authorized the product redesign, so the reset
is an authorized scope change, not an exception to a freeze.

The tag `v0.1.0-rc.1` is **not moved, rewritten or deleted** — it stays as the
record of the old release candidate, and existing release tags and historical
migrations are all retained. A future candidate for the reset product is a new
incrementing tag.

Change control is now the chunk and review workflow in
[`implementation/README.md`](./implementation/README.md): one chunk at a time,
Claude implements, Codex independently reviews and records acceptance, and no
chunk starts before its dependencies are accepted.

### What replaces this document

| Old role | Replacement |
|---|---|
| Consolidated pilot gate list | The 30 chunk assignments in [`implementation/chunks/`](./implementation/chunks/) |
| Story-level acceptance criteria | `prd.md` §10.5 (`US-27`–`US-43`) |
| External blockers | D1–D6 in [`implementation/DECISIONS.md`](./implementation/DECISIONS.md) |
| "What is actually failing right now" | [`implementation/BASELINE.md`](./implementation/BASELINE.md), re-established by chunk 02 |
| Launch checklist | `implementation/IMPLEMENTATION-PLAN.md` §10, enforced by `US-43` |
| Device matrix and physical evidence | AC-35.5 and chunk 29, against the D2-confirmed device list |

### Items that carry forward in substance

Not as this document's items, but as requirements in the reset scope:

- Push and notification delivery evidence → chunk 26.
- Physical device matrix on real hardware, never simulator or emulator output →
  AC-35.5, chunk 29, scoped by the D2 device decision rather than the Hajj
  handset list.
- Infrastructure and deploy-pipeline pre-promotion checks → chunks 26 and 27.
- Compliance cross-references → `security.md` §10.14, re-scoped to the
  jurisdictions D2 and D3 actually select.
- Real-administrator usability observation → AC-43.5, with an enterprise pilot
  administrator instead of an HTO operator.
- English/French release gates → `localization.md` §9.

### Items that retire with their features

The launch verified-CLI/app-call path, SOS, geofencing and HTO-specific UI
leave the reset scope; remaining check-in/welfare paths follow the product-default
decision. Existing safety scenarios remain required for every supported or
transitioning path under `testing-qa.md` §14.13. Account isolation in AC-30.4 is
an additional requirement, alongside history preservation, safe shutdown and
old-client/job compatibility. Removal is proven by chunk 04, not by this amendment.

### Known inconsistency, deliberately left open

`scripts/validate-release-signoff.sh` still requires "Offline check-in survival
through force-quit/reboot" and "Offline SOS survival through force-quit/reboot"
rows in every release signoff. Those rows describe the legacy product. The
workflow still runs on PRs to `main`; current server-side merge enforcement was
not verified (the branch-protection API returned 404 during review). Treat the
July protection claim as historical; do not infer either enforcement or absence
from that response. See `implementation/BASELINE.md`.

Chunk 01 did **not** change that script: release automation is chunk 27's scope,
and quietly weakening a release gate from a documentation chunk is exactly the
kind of change that should be reviewed on its own. Until chunk 27 lands, a
`staging → main` promotion still mechanically demands SOS evidence. This is
tracked in [`implementation/STATUS.md`](./implementation/STATUS.md) and closed by
AC-42.5.
