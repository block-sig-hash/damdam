# Pre-Pilot Checklist

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

---

## 1. Push / notification delivery

| Item | Source | Done looks like |
|---|---|---|
| FCM/APNs push delivery on real devices (arrival + date-triggered eSIM activation prompts) | US-13, PR #64, `testing-qa.md` §14.3 | A real push notification observed arriving on at least one physical iOS and one physical Android device, not a mocked payload assertion |
| Production FCM topic subscription + live delivery to a subscribed browser | US-19, PR #70 | A real Firebase project's `hto-{organization_id}` topic sends a message that a real subscribed browser (not a headless test) visibly receives, via the dashboard's `firebase-messaging-sw.js` |
| HTO SOS push delivery through live Meta/Resend/FCM accounts | US-16, PR #68 | One real SOS alert dispatched through all three channels against production (or production-equivalent) vendor accounts, with delivery confirmed on the receiving end, not just a 200 from the vendor API |
| `FIREBASE_ACCESS_TOKEN` live rotation | US-16, PR #68 | The short-lived FCM HTTP v1 OAuth token is refreshed by a real deployment process at least once without manual intervention — "not testable locally" per the PR, so this can only be closed against a real deployment |
| Real device-token registration end-to-end (`PUT /me/device-token`) | US-13, PR #64 | Firebase/Apple runtime configuration (recorded as "deployment-secret work, not committed configuration") is actually present in a deployed environment and a real device successfully registers a token against it |

## 2. Voice / PSTN (US-14)

All items below are from `testing-qa.md` §14.9's own explicit "Required
real-device / real-network evidence before an HTO pilot" list, plus PR #66.

| Item | Done looks like |
|---|---|
| One real Telnyx-account PSTN call | One actual outbound PSTN call placed per platform over real cellular/eSIM data, confirming the recipient sees the verified Nigerian CLI and the call reaches Telnyx's signed webhook endpoint — logged, not simulated |
| Real call quality | Call quality observed on at least 4G, on degraded/packet-loss cellular data, and through a forced mid-call network drop, with the in-app quality indicator compared against actual audible behavior, and confirmation that only connected seconds are billed |
| CallKit (iOS) / ConnectionService (Android) native integration | Native call UI and audio routing verified on physical iOS and Android hardware, including background/lock-screen behavior, microphone, mute, speaker, and Bluetooth routes — not the mocked Telnyx SDK transitions already covered in CI |
| Contextual Contacts permission | Verified on both physical platforms, including a denial path and a later Settings re-enable |
| iOS native project generation | The repository has no `apps/mobile/ios` project directory as of PR #66/US-14; iOS AppDelegate/PushKit/CallKit autolinking cannot be built until this exists — blocking, not optional, per `testing-qa.md` §14.9 |

## 3. Check-in / offline queue (US-15)

Source: US-15 PR #67, `testing-qa.md` §14.3, §14.4.1, §14.4.3.

| Item | Done looks like |
|---|---|
| Real device force-quit / reboot of the SQLite outbox | A check-in triggered offline, the app force-quit before sync, then the device rebooted — on a physical device, not an emulator — with the queued check-in still present and still syncing on relaunch |
| Actual Meta WhatsApp delivery confirmation | A real WhatsApp template message sent and its delivery receipt observed from Meta's live API, not the signed-webhook simulation already covered in CI |
| Actual Termii family SMS fallback | A real SMS delivered through Termii's live API when the 60-second WhatsApp delivery window is exercised for real (not the deterministic 59s/60s boundary test already in CI) |
| Poor cellular / eSIM network testing | The intermittent-connectivity scenario (§14.4.1 — connection dropping every few seconds, matching the actual Mina/Arafat scenario) exercised on a real device over real degraded cellular/eSIM data, confirming no duplicate check-ins are created |
| OS background-wake timing | The exact 30-second retry cadence is only proven deterministic while the JS runtime is alive (fake timers in CI); real OS background-wake timing (`react-native-background-fetch`, ~15-minute iOS minimum, Android scheduler deferral) must be observed on real devices, not inferred |
| OEM battery-management survival | Budget Android devices' aggressive process-killing behavior — the exact failure mode the offline queue exists to survive — verified on the actual target device profile (see §5 below), not a generic Android emulator |

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
| Android device screenshot production (10–15 device models) | Real, physical-device-captured, verified screenshots for the Android activation guide across Tecno Camon/Spark, Infinix Hot/Note, itel, and Samsung Galaxy A-series (`frontend-mobile.md`'s Screen 19 spec). As of US-13/PR #64, these are explicitly labelled placeholder frames, not final artwork — this is a **content production task**, not an engineering one, and should be scoped as its own workstream per `frontend-mobile.md`'s own note |
| Full eSIM download → QR fallback → activation flow | End-to-end on each of the physical devices above — `testing-qa.md` §14.3 explicitly states this "cannot be meaningfully emulated" |
| Device Compatibility Warning path on iOS | Confirmed actually firing correctly (AC-10.3) on at least one non-eSIM-capable or older physical iPhone, per `testing-qa.md` §14.3's two-iPhone requirement |

## 6. Physical device matrix (cross-cutting)

Source: `testing-qa.md` §14.3, referenced by nearly every item above.

**Required before pilot launch — same physical device set used across §3, §4, §5:**

| Platform | Devices |
|---|---|
| Android | Tecno Camon (recent generation), Infinix Hot/Note (recent generation), itel (current budget model), Samsung Galaxy A-series |
| iOS | One eSIM-capable iPhone (XS or later), one non-eSIM-capable or older iPhone still in reasonable use |

**Done looks like:** every item in §2–§5 above that says "real device" has actually been run against this specific device set, not a substitute device or an emulator/simulator claiming to represent it.

## 7. HTO dashboard usability (US-05 family, `testing-qa.md` §14.5)

| Item | Done looks like |
|---|---|
| Usability testing with an actual HTO pilot partner | A real (or realistic proxy) operator attempts the manifest upload → order → monitor flow with minimal guidance, observed live, before general HTO rollout — qualitative, scheduled as its own milestone per §14.6, not assumed to happen informally |

## 8. Infrastructure / deploy pipeline pre-promotion

Source: PR #79 ("feat: implement deploy pipeline and readiness checks") —
merged 2026-07-19, so `infrastructure.md` §11.11 (cited below) is on
`develop`. The items in this section are still real, unfinished pre-launch
work; only the PR-merge prerequisite itself is closed.

| Item | Done looks like |
|---|---|
| Isolated staging OCI host provisioned | A real staging OCI instance exists and is reachable — none is provisioned by PR #79 itself |
| Staging GitHub Environment secrets configured | All four named secrets (`STAGING_OCI_HOST`, `STAGING_OCI_DEPLOY_USER`, `STAGING_OCI_SSH_KEY`, `STAGING_API_BASE_URL`) are set in the `staging` GitHub Environment — the workflow's own preflight check fails with one named error per missing secret until this is done |
| `/opt/damdam/.env.staging` created | Real staging environment file present on the staging host, not the committed `compose.env.example` placeholder |
| First production Compose release manually bootstrapped | Explicitly documented as "manual and Ibrahim-owned" (PR #79) — automated production deploy refuses to proceed without a prior image to preserve as a rollback target, so this is a hard prerequisite, not automatable |
| Cloudflare tunnel / DNS configured for production | Real tunnel token and DNS records in place — `compose.env.example`'s `CF_TUNNEL_TOKEN` is a placeholder (`replace-with-a-real-cloudflare-tunnel-token`) |
| Production secrets supplied | Real values for every secret currently placeholder/example-only across `.env.example` and `compose.env.example` |
| `ESIM_ACCESS_PACKAGE_CODES` format migration | **From PR #78 (merged 2026-07-18), deploy-safety fix landed separately:** the eSIM Access package-code config changed from integer keys (`{"5":"SA_5GB"}`) to destination-composite keys (`{"SA:5":"SA_5GB"}`). `Settings` now validates this at app boot (`esim_access_package_codes_must_use_composite_keys` in `app/config.py`) — an old-format or SA-less env var now crashes the app on startup instead of silently degrading eSIM Access into "every tier unconfigured" behind the vendor cascade. **Done:** production/staging's `ESIM_ACCESS_PACKAGE_CODES` env var is confirmed in the `"COUNTRY:GB"` composite format with at least one `SA:` entry, and a real deploy (or `Settings()` construction against the real production env values) boots cleanly — i.e. the startup validator has actually run against the real value, not just against a test fixture |
| Kuma monitoring configured and alerting confirmed working | **From `infrastructure.md` §11.13:** self-hosted Uptime Kuma is deployed and isolated on Hermes, with the API readiness monitor and the WAL-G push/heartbeat monitor both configured, and a deliberately-triggered test alert (real induced Down/Up transition, or a real withheld heartbeat) was received via the real configured Telegram channel — not just "the monitor exists in Kuma's dashboard." The production readiness monitor will legitimately show Down until `api.damdam.app` actually resolves (tracked by the staging/production rows above); that is not this item's blocker. This item's blocker is confirming the *alert path itself* fires end to end, which was proven once during setup (see §11.13) but should be re-confirmed by Ibrahim after real production/staging deploys land, since that is the first time the readiness monitor will exercise a real transition rather than a substitute test target |

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

See `security.md` §10.10 directly for the full list (privacy policy, ToS,
processor DPAs, NDPA filing, retention automation).

---

## Summary

**37 distinct checklist rows** consolidated across 8 stories/PRs and 4 spec
documents into the 9 categories above (counted directly from this
document's tables). §6's 2 rows are the physical device roster itself —
cross-cutting infrastructure that §2–§5's "real device" items depend on,
not a separate set of gaps on top of them.

Sources pulled from, directly:
- `testing-qa.md` §14.3 (device matrix), §14.4.1–§14.4.4 (check-in/SOS
  chaos scenarios + real-device boundaries), §14.5 (HTO usability), §14.9
  (voice real-device/real-account evidence)
- `security.md` §10.10 (compliance — cross-referenced, not duplicated)
- `infrastructure.md` §11.13 (self-hosted Uptime Kuma replacing UptimeRobot)
- PR descriptions: #62 (US-10), #64 (US-13), #66 (US-14), #67 (US-15), #68
  (US-16), #70 (US-18/19/22), #78 (destination-country Phase 3, merged
  2026-07-18), #79 (deploy pipeline, merged 2026-07-19)
- `frontend-mobile.md` (Android screenshot content-production note)

**One item newly surfaced while compiling this document, not previously
flagged anywhere:** PR #78's `ESIM_ACCESS_PACKAGE_CODES` key-format change
needed an atomic production env-var update on deploy (§8) — this was recorded
as a deploy note inside PR #78 itself but had not been pulled into any
pre-pilot or pre-promotion checklist until this document. It has since moved
from a documentation-only risk to a startup-time guardrail: `Settings` now
refuses to boot on the old key format or on an SA-less config (see §8), so
the remaining pre-pilot work on that item is confirming the real
production/staging env var, not building anything further.
