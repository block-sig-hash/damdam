# Testing & QA Specification

> **Current scope:** the September 2026 reset in §14.13 and
> [PRD §10](prd.md) governs conflicts with earlier text. Use the
> [scope disposition](implementation/SCOPE-DISPOSITION.md) and
> [decision register](implementation/DECISIONS.md) for retained, retired
> and proposed behavior. These are target requirements; existing code and
> supported transition paths remain subject to their applicable checks.

# DamDam — Version 0.1

This document closes a gap that existed across the rest of the
spec suite: `infrastructure.md` §11.4 runs `pytest`/`jest` in CI,
and the PR template asks "tests added?", but nothing until now
specified *what* to test, *how much* coverage is required, or how
a passing test suite maps back to the acceptance criteria already
written in `prd.md` §4. This document is that missing link.

---

## 14.1 Test-Driven Development Policy

**Decision: TDD is required for safety-critical features, strongly
recommended everywhere else, not mechanically enforced by tooling.**

Given the 7-month build runway (`prd.md` §6) and a small team, a
blanket "no code without a failing test first" rule would be
process overhead the team can't afford everywhere. Instead:

| Feature category | TDD requirement |
|---|---|
| Check-in & SOS (US-15, US-16, US-24) | **Strict TDD required.** Write the test for each acceptance criterion first, confirm it fails, then implement. This is the one category where a bug is a real-world safety failure, not a product inconvenience — see §14.4 for why this gets extra rigor beyond just "write tests first." |
| Payment & idempotency (US-09, US-25) | **Strict TDD required.** Double-provisioning or double-charging a pilgrim is a trust-destroying failure mode at exactly the moment (pre-departure) when it's hardest to resolve. |
| Authentication (US-01, US-02, US-23) | **Strict TDD required.** Account lockout logic, PIN handling, and session expiry are exactly the kind of edge-case-heavy logic where writing the test first catches the off-by-one errors that manual testing misses. |
| eSIM provisioning (US-10, US-11, US-13) | TDD recommended, not mandated — much of this feature's correctness depends on real device/aggregator behavior that a unit test can't fully simulate (see §14.3's device matrix instead). |
| HTO dashboard CRUD screens (US-05 through US-20) | TDD recommended, not mandated — standard CRUD risk profile, integration tests after the fact are an acceptable trade against shipping speed. |
| UI polish, copy changes, styling | No TDD expectation. |

**What "strict TDD required" means in practice for a PR:** the test
file's commit timestamp (or, more practically, the PR's commit
history) should show the test being added before or in the same
commit as the implementation, and CI must show that test failing
against the pre-change code if asked. This is a review-time check,
not a tool-enforced gate — reviewers on PRs touching the categories
above should explicitly verify this in review, per the checklist
addition to `.github/PULL_REQUEST_TEMPLATE.md` in §14.7.

---

## 14.2 Test Coverage Requirements, Mapped to Acceptance Criteria

Every acceptance criterion (`AC-XX.X`) in `prd.md` §4 is written in
a testable form already — this section is mostly wiring those to
concrete test types, not inventing new requirements.

**Coverage targets by layer:**

| Layer | Tool | Minimum coverage | What "coverage" means here |
|---|---|---|---|
| API (FastAPI) | pytest + pytest-cov | 85% line coverage on `app/` excluding migrations | Every endpoint in `api-spec.md` has at least one success-path and one failure-path test |
| Data model / ORM | pytest (against a real test Postgres, not mocked) | 100% of unique constraints and idempotency keys explicitly tested | Every `UNIQUE` and idempotency-relevant field in `data-model.md` §6.2 has a test proving duplicate insertion is handled correctly |
| Mobile (React Native) | Jest + React Native Testing Library | 70% on business logic (hooks, state management, offline queue); UI component snapshot tests opportunistic, not mandated | The offline queue (`prd.md` §5.6) specifically needs deterministic unit tests independent of any device |
| Dashboard (Next.js) | Jest + React Testing Library | 70% on data-fetching/state logic; UI components opportunistic | Role-based route guards (`security.md` §10.5) have explicit tests proving cross-tenant isolation |
| API contract | Schemathesis or equivalent property-based API testing against the OpenAPI spec | All endpoints | Catches cases where the implementation technically passes unit tests but doesn't match what `api-spec.md` promises — this is the automated version of the drift check already in `infrastructure.md` §11.4 |
| Mobile visual/design-system compliance | Manual + Claude review via `claude-review.yml` (see note below) | Every `apps/mobile` screen PR, excluding the Claude-implemented exception screens | **Not a code-coverage metric** — a screen can pass 100% of its unit tests and still not match `design-system.md`. This layer specifically requires a rendered screenshot, not code inspection; see the dependency note below |

**Dependency note on the visual-compliance row:** `claude-review.yml`
is written to check a PR's rendered screenshot against
`design-system.md`. That prerequisite is now built — see
"Amendment — Screenshot-Generation CI" at the end of this document
for what's actually covered and what's still out of scope. Until
that amendment's coverage gaps close (most of the screen inventory
isn't wired into the harness yet, and the iOS job only runs
nightly/on-demand rather than per-PR), still treat this row as
**partially satisfied**: a screen inside the harness's covered set
gets a real rendered-screenshot check, but a screen outside it still
falls back to the weaker text-only review.

**Migration testing gap:** the API coverage row above excludes
migrations, and CI's "Apply database migrations" step
(`infrastructure.md` §11.4) always runs against a freshly-provisioned,
empty Postgres service container — it has no persistent volume and no
seeded data, so it can never catch a migration that only fails against
a table that already has rows (a `NOT NULL` column added with no
backfill, a new constraint an existing row would violate, a shape
change that assumes emptiness). CI passing is therefore not sufficient
evidence a migration is safe for any environment other than a fresh
one. PR #41 is the concrete example: `0008_us26_manual_pricing`'s
initial version passed CI cleanly but failed with a `NotNullViolation`
the first time it was run against a database that already had
`pricing_tiers` rows. Any migration that adds a `NOT NULL` column, a
new constraint, or otherwise changes shape on a table that could
plausibly already have rows in some real environment (local dev, a
teammate's seeded database, staging once it exists) should be manually
tested against seeded data before merging, not just against CI's empty
database.

**Explicit test-to-AC mapping requirement:** every PR implementing
a user story should include, in the test file itself (as comments
or test names), a reference to which `AC-XX.X` each test proves.
Example:

```python
def test_otp_expires_after_10_minutes():
    """AC-01.4: OTP expires after 10 minutes"""
    ...

def test_checkin_rate_limited_to_one_per_15_min():
    """AC-15.9: Check-ins are rate-limited to one per 15 minutes"""
    ...
```

This makes it possible to grep the test suite against `prd.md` and
see, at a glance, which acceptance criteria have no corresponding
test yet — a cheap, high-value practice worth enforcing from the
first PR rather than retrofitting later.

---

## 14.3 Device & Platform Test Matrix

Given the dual-platform decision (`prd.md` §1, §6) and the specific
device profile of the target demographic, testing exclusively on
emulators/simulators is not acceptable for this product —
particularly for the eSIM and offline-queue features, where real
hardware behavior (battery optimization killing background
processes, actual eSIM hardware support) diverges meaningfully from
emulator behavior.

**Required physical device coverage before Hajj-season pilot
launch:**

| Platform | Devices | Rationale |
|---|---|---|
| Android | Tecno Camon (recent generation), Infinix Hot/Note (recent generation), itel (a current budget model), Samsung Galaxy A-series | Covers the majority Nigerian device profile referenced throughout `prd.md`; budget Android devices have the most aggressive battery-management behavior that threatens the offline queue's reliability (`prd.md` §5.6) |
| iOS | One eSIM-capable iPhone (iPhone XS or later, per `frontend-mobile.md` §8.3's compatibility note), one *non*-eSIM-capable or older iPhone still within reasonable use (to test the Device Compatibility Warning path, AC-10.3, actually firing correctly on iOS) | Confirms the device-model-allowlist approach (since no iOS capability API exists) is accurate, not just theoretically correct |

**What must be tested on real hardware, not emulator/simulator:**
- Full eSIM download → QR fallback → activation flow (`prd.md`
  §5.4) on each device — this cannot be meaningfully emulated
- Offline queue survival across app backgrounding, force-quit, and
  device reboot (`prd.md` §5.6, AC-24.4) — budget Android devices'
  aggressive process-killing behavior is exactly the failure mode
  this feature exists to survive, and it must be proven on the
  actual devices most likely to kill the app process
- Push notification delivery reliability (geofence-triggered and
  date-triggered eSIM activation prompts, `prd.md` §5.4) — real
  OS-level notification throttling behavior differs from simulator
  behavior
- CallKit (iOS) / ConnectionService (Android) integration
  (`frontend-mobile.md` §8.3, Active Call screen note)

**Acceptable to test on emulator/simulator:** UI layout across
screen sizes, most Dashboard-side testing (desktop web, no device
fragmentation concern per `frontend-dashboard.md` §9.5), unit and
integration test suites for business logic that doesn't depend on
platform-specific OS behavior.

---

## 14.4 Offline-First & Safety-Critical Feature Testing (Check-in / SOS)

This is the section that matters most given the product's actual
purpose. A bug here is not "a feature doesn't work" — it's "a
pilgrim in genuine danger doesn't get help," which is a different
category of risk than anything else in this spec suite and
deserves testing rigor beyond the general coverage targets in
§14.2.

### 14.4.1 Required test scenarios (beyond standard unit tests)

- **Airplane-mode round trip:** trigger check-in/SOS with the
  device in airplane mode, confirm local write succeeds and UI
  reflects "queued" state correctly (AC-15.4, AC-16.3), then
  disable airplane mode and confirm sync completes within the
  specified retry interval
- **Force-quit during queued state:** trigger check-in/SOS while offline,
  force-quit the app before connectivity returns, relaunch, confirm
  the queued SOS is still present and still attempts to sync
  (AC-24.4 — "queue persists across app restarts and device
  reboots")
- **Device reboot during queued state:** same as above but with a
  full device reboot, not just app force-quit — this is a stronger
  test of the "not in-memory" requirement on the SQLite queue
- **Intermittent connectivity (the actual Mina/Arafat scenario):**
  simulate a connection that comes and goes every few seconds
  (achievable with network-condition tooling — Android's Network
  Profiler / iOS Network Link Conditioner, or a proxy tool like
  Charles/mitmproxy configured to drop connections on a timer) —
  confirm the retry logic doesn't create duplicate check-ins/SOS
  events (this is what the `client_generated_id` idempotency key in
  `data-model.md` §6.2/§6.3 exists to prevent — this test is the
  proof it actually works, not just a theoretical design)
- **Rapid repeated SOS presses:** confirm the "no rate limit on
  SOS" design decision (AC-16.7) doesn't create a flood of
  duplicate server-side alerts if a panicking user presses multiple
  times — the idempotency key should collapse these correctly even
  though there's no application-level rate limit
- **Notification delivery failure simulation:** force a WhatsApp
  API failure (mockable in a staging environment) and confirm the
  admin Failed Notification Queue (`frontend-dashboard.md` §9.3,
  Screen 16) actually receives the failed row, and that the
  underlying check-in/SOS record itself is unaffected by the
  notification failure (per the explicit failure-mode note in
  `prd.md` §5.6)
- **Redis rate-limiter outage:** force Redis `SET`/`GET` to raise while the API
  receives a new check-in; the PostgreSQL check-in and notification rows must
  still commit (rate limiting fails open, UUID idempotency remains enforced)
- **WhatsApp delivery-time boundary:** confirm an accepted WhatsApp with no
  delivery receipt sends no SMS at 59 seconds and sends exactly one at 60
  seconds; a signed `delivered` webhook before the deadline must suppress it.
  Unsigned and malformed Meta status webhooks must not suppress fallback.

### 14.4.2 Pre-Hajj-season load and chaos testing

Beyond individual-device testing above, a dedicated load/chaos
exercise should run **at least once before the actual Hajj 2027
season**, simulating realistic concurrent conditions rather than
one device at a time:

- **Concurrent check-in burst:** simulate several hundred to a few
  thousand simultaneous check-in requests hitting the API (roughly
  matching the pilot-scenario volume in the margin model — 1,500
  pilgrims checking in within a similar time window, as would
  plausibly happen around a fixed prayer time or scheduled group
  movement) — confirm the API and Celery worker queue
  (`infrastructure.md` §11.3) handle the burst without dropped
  requests or unacceptable latency
- **Concurrent SOS during degraded network:** the worst-case
  combination — simulate multiple simultaneous SOS events while
  the API's own connectivity to WhatsApp/Twilio is also degraded,
  confirming the retry/queue architecture on the *server* side
  (not just the client) degrades gracefully rather than silently
  dropping events
- **Tabletop exercise, not just automated testing:** per
  `security.md` §10.8's incident-response note, run an actual
  tabletop exercise with whoever will be operationally on-call
  during the real Hajj season — walk through "a pilgrim's SOS
  doesn't seem to have reached anyone, what do you actually do
  right now" as a human process question, not just a system test

### 14.4.3 US-15 automated evidence and OS scheduling boundary

The US-15 feature PR must include deterministic tests that recreate the mobile
sync service over the same SQLite-backed rows (process-restart simulation),
retry the identical `client_generated_id` after a lost response, and prove the
server creates one `check_ins` row and one `check_in_notifications` row under a
real-PostgreSQL concurrent retry. The foreground retry interval is exactly 30
seconds and a connectivity-change event triggers an immediate attempt. A newly
captured row is held from sync for at most two seconds while contextual GPS is
resolved, preventing a connectivity event from racing location enrichment while
still leaving at least three seconds of AC-15.3's connected-send budget.

The maintained native modules selected for this implementation are
[`react-native-nitro-sqlite`](https://github.com/margelo/react-native-nitro-sqlite)
for the durable outbox, React Native Community
[`geolocation`](https://github.com/michalchudziak/react-native-geolocation) for
optional tap-time GPS, and Transistor Software
[`react-native-background-fetch`](https://github.com/transistorsoft/react-native-background-fetch)
for OS-assisted Android terminate/reboot recovery and iOS background fetch. The
last mechanism does not make a false timing promise: iOS controls background
wakeups (approximately 15-minute minimum), and Android schedulers may defer
work. AC-15.4's exact 30-second cadence is deterministic while the JS runtime is
alive; SQLite persistence, connectivity-triggered sync, app-start recovery, and
OS-assisted background work protect process-death cases. The full force-quit /
reboot matrix in §14.3 remains mandatory real-device evidence before pilot.

### 14.4.4 US-16 automated evidence and real-device boundary

US-16 adds deterministic tests for local-write-before-network ordering, the
10-second foreground retry, connectivity-triggered immediate retry, process
recreation over the same durable outbox rows, and rapid repeated hold
completion collapsing to one `client_generated_id`. API tests prove the same
UUID produces one alert/four trigger notifications, while a different UUID is
not rate-limited; cancellation and HTO resolution exercise distinct actor paths.
Forced channel failure is retried three times into the admin queue without
changing the active alert.

The native dialer is asserted as a `tel:` Linking call rather than the DamDam
VoIP gateway. Simulator/emulator tests cannot prove real dialer launch,
background scheduling after an OS-level force-stop/reboot, production FCM topic
subscription, or delivery through live Meta/Resend/FCM accounts. The §14.3
real-device matrix, airplane-mode round trip, device reboot, real notification
delivery, and native-dialer verification remain required before the pilot.

---

## 14.5 HTO Dashboard Testing

Given `frontend-dashboard.md`'s explicit note that operators are
"semi-technical... under potential stress," dashboard testing needs
a usability-testing component, not just functional correctness.

**Note on scope versus §14.2's new visual-compliance row:** the
dashboard is deliberately excluded from the screenshot-based
design-system check — it's explicitly speced as "functional, not
polished" per `frontend-dashboard.md` §9.5, and Codex implements it
directly (per `AGENTS.md`'s ownership table) without needing to
match `design-system.md`, which only governs `apps/mobile`. Don't
extend the screenshot-review requirement here; it would be spending
review effort on a surface where the spec has already decided
polish doesn't matter.

- **Functional:** standard integration tests per the coverage
  targets in §14.2, particularly around the manifest multi-order
  flow (`data-model.md` §6.5) which has genuine logical complexity
  (unordered-pilgrim-pool queries, family grouping constraints)
- **Cross-tenant isolation:** explicit, mandatory tests proving one
  HTO operator cannot access another's manifests/pilgrims/orders
  via any endpoint, including deliberate attempts to manipulate
  IDs in requests — this is the single highest-consequence bug
  category on the dashboard side (`security.md` §10.5)
- **Usability testing with an actual HTO pilot partner:** before
  general HTO rollout, have a real (or realistic proxy) operator
  attempt the manifest upload → order → monitor flow with minimal
  guidance, observing where they get stuck — this is qualitative,
  not a pass/fail test suite item, but should be scheduled as a
  concrete milestone (see §14.6) rather than assumed to happen
  informally

---

## 14.6 Testing Milestones Against the Build Timeline

Mapped against the phased build-sequencing table in `prd.md` §6
(the "Phase 0" through "Phase 4 / Hajj launch" table — not the
separate, differently-scoped business/GTM roadmap phases noted
there):

| Milestone | Timing | What must be tested |
|---|---|---|
| `design-system.md` produced (dedicated design session) | Start of Phase 1, before any mobile screen work | See `design-system.md`'s own status note — this blocks Codex starting on `apps/mobile` screens per `AGENTS.md` |
| Screenshot-generation CI step built (Detox/Maestro or Expo preview) | Start of Phase 1, alongside the design session, before the first mobile screen PR merges | Without this, §14.2's visual-compliance coverage row is unsatisfied regardless of what `claude-review.yml`'s prompt asks for — see that row's dependency note |
| Core auth + purchase flow test-complete | End of Phase 1 (per the original build sequencing) | US-01 through US-09 fully covered per §14.2's targets |
| Check-in/SOS offline-chaos suite passing | End of Phase 3 | All scenarios in §14.4.1 passing on at least one real device per platform |
| Device matrix testing complete | Before Phase 4 (HTO pilot onboarding) | Full device list in §14.3 covered |
| HTO usability test with a real/proxy operator | Before Phase 4 | §14.5's usability observation completed, findings incorporated |
| Load/chaos exercise + tabletop | Before Hajj season launch, not before Phase 4 | §14.4.2 completed with real findings documented, not just scheduled |

---

## 14.7 Process Integration

**PR template addition** (`'.github/PULL_REQUEST_TEMPLATE.md'`
already has a "Tests added/updated?" checkbox — extend it):

```markdown
- [ ] Tests added/updated, mapped to specific AC-XX.X per §14.2
- [ ] If this PR touches check-in, SOS, payment, or auth: TDD
      policy in testing-qa.md §14.1 followed (test-first, verified
      in commit history)
- [ ] If this PR touches the offline queue or SOS: relevant
      scenarios from testing-qa.md §14.4.1 re-run, not just new
      tests added
```

**CI additions to `infrastructure.md` §11.4's existing pipeline:**
- Coverage threshold enforcement (85% API / 70% mobile-dashboard
  business logic) as a failing check, not just a report
- Schemathesis (or equivalent) API contract testing added as a CI
  job alongside the existing OpenAPI drift check

---

## 14.8 What This Document Deliberately Does Not Cover

- **Penetration testing / third-party security audit** — belongs
  in `security.md`'s pre-launch checklist as a separate line item,
  not duplicated here; this document covers functional/QA testing,
  not adversarial security testing
- **App Store / Play Store review-specific testing** (e.g.,
  confirming the payment classification framing in `prd.md` §7
  doesn't trigger reviewer scrutiny) — that's a submission-process
  concern, tracked in `infrastructure.md`'s release workflow, not a
  test-suite item
- **Performance/load targets for the general-traveler or
  enterprise tiers** — those segments don't have the same
  fixed-date surge pattern as Hajj season and can have their load
  testing scoped later, once real usage data from the Hajj pilot
  exists to model against

---

## 14.9 Voice / WebRTC Verification — US-14 Gap Closure

Before US-14, this document had no voice, WebRTC, call-quality, CallKit, or
ConnectionService guidance. That omission was materially different from the
explicit real-device requirements for push/geofencing in §14.3. Voice tests now
have two evidence tiers; a mocked SDK/webhook suite is necessary but cannot be
reported as pilot-ready calling evidence.

**Required automated evidence in the feature PR:**

- Dial-pad number entry, contextual contacts-permission request, zero-minute
  PSTN disablement, app-to-app exemption, low-minute warning, offline banner,
  last-20 history rendering, and exact connectivity-loss copy/navigation.
- Telnyx token/eligibility contract tests, including unverified PSTN denial and
  unverified app-to-app allowance.
- Ed25519 webhook tests proving missing, malformed, stale, and incorrectly
  signed requests receive `401 invalid_webhook_signature` before JSON is
  trusted; authentic malformed JSON receives `400 invalid_webhook_payload`.
- Duplicate hangup idempotency plus a real-Postgres concurrent/rapid-hangup test
  at a sub-minute balance. The final value must be exactly zero, no call log may
  contain a negative charge, and the next PSTN eligibility/token request must
  be blocked.

**Required real-device / real-network evidence before an HTO pilot (not
substitutable with simulator screenshots):**

- One actual Telnyx-account PSTN call per platform over cellular/eSIM data,
  confirming the recipient sees the verified Nigerian CLI and the call reaches
  Telnyx's signed webhook endpoint.
- Call quality on at least 4G, degraded/packet-loss cellular data, and a forced
  mid-call network drop; compare the in-app indicator with audible behavior and
  confirm connected seconds only are billed.
- Native call UI/audio routing on physical iOS (CallKit) and Android
  (ConnectionService), including background/lock-screen behavior, microphone,
  mute, speaker, and Bluetooth routes.
- Contextual Contacts permission on both platforms, including denial and a
  later Settings re-enable.

**US-14 implementation evidence boundary:** simulator/emulator component flows,
mocked Telnyx SDK state, and cryptographically signed mocked webhooks may be
completed in CI. They do **not** prove actual media quality, carrier CLI
presentation, real Telnyx routing, or native lock-screen call UI. The repository
currently has no `apps/mobile/ios` project directory, so iOS AppDelegate/
PushKit/CallKit autolinking cannot be built locally until that platform project
is generated; this is a pre-pilot blocker, not a reason to hand-roll CallKit.

**Native-module evaluation (2026-07-16):** Telnyx's old
[`@telnyx/react-native`](https://www.npmjs.com/package/@telnyx/react-native)
1.1.2 is deprecated and explicitly redirects users to the native iOS/Android
SDKs. Telnyx's maintained
[`@telnyx/react-voice-commons-sdk`](https://github.com/team-telnyx/react-native-voice-commons)
1.0.0 (released 2026-06-14) wraps the official native voice bridge and includes
CallKit/ConnectionService, push, lifecycle, mute/speaker, and call-state
handling; it is used for US-14. Device contacts use maintained
[`react-native-contacts`](https://github.com/morenoh149/react-native-contacts)
with `READ_CONTACTS`/Contacts-framework autolinking. No custom WebRTC, CallKit,
ConnectionService, or contacts native bridge is justified or implemented.

**CLI-verification hardening (AC-14.1/AC-14.10/AC-14.11, data-model.md
§6.40, `docs/verified-cli-scoping.md`):** strict-TDD category (auth) per
§14.1 -- `test_caller_identity.py` and `test_verified_numbers.py` were
written alongside the `VerifiedCallerIdentity` state machine, not after.
Required automated evidence in the feature PR:

- Phone-possession verification is decoupled from the account login
  number: a user may start verification for a Nigerian number other than
  the one they signed in with (AC-14.10), and the resulting
  `VerifiedCallerIdentity.phone_number` is what PSTN calls use as caller
  ID, not `users.phone_number`.
- Consent capture is a distinct, required step after phone verification
  (`consent_required` -> `active`); attempting consent before
  confirmation, or confirming with the wrong code, is rejected without
  advancing state.
- Revocation and lost-SIM reporting immediately flip PSTN eligibility back
  to `cli_not_verified` (AC-14.11) without needing to touch an in-flight
  call.
- Re-verifying a different number automatically revokes the previous
  `active` identity for the same user (at most one `active` CLI per user);
  a number already `active` on a different account is rejected
  (`number_already_verified_elsewhere`) rather than silently reassigned.
- CLI-verification-specific rate limiting is exercised independently of
  the general OTP rate limiter.
- The code-confirmation step is separately guarded against brute-forcing the
  SMS code itself: repeated wrong codes against one `identity_id` lock out
  further confirm attempts for `CLI_VERIFICATION_CONFIRM_LOCKOUT_SECONDS`,
  mirroring `OTPService`'s own attempts/lockout pattern rather than relying
  only on the coarser per-user `start_verification` rate limit.
- The retired `users.verified_cli` login-OTP shortcut no longer grants CLI
  rights: a fresh login does not itself unlock PSTN calling.
- `MockIdentityProvider` never reports a real identity match regardless of
  input, and `NIN_VERIFICATION_ENABLED`/`STRICT_NIN_MSISDN_MATCH_REQUIRED`
  default off -- both are founder/legal decisions per
  `verified-cli-scoping.md` §4, not engineering defaults.

**Mobile (Screens 22a-22d, `frontend-mobile.md`'s new per-screen
specification):** no prior spec existed for these screens, so
`apps/mobile/src/screens/CliVerification/*.test.tsx` is this
feature's first test coverage, not a revision of existing tests.
Covers: number-entry validation disabling submit until a valid
Nigerian number is entered (mirroring, not reusing, Phone Number
Entry's narrower login-number pattern -- AC-14.10 accepts any
Nigerian mobile number); a wrong code showing an inline error without
clearing the input; a rate-limited confirm response disabling further
submission; consent capture; and Screen 22d's three states (no
identity, mid-verification resume, active with revoke/lost-SIM
confirmation via the same custom `<Modal>` pattern as `SosSentScreen`'s
cancel confirmation and `DeviceCompatibilityWarningModal`, never a
native `Alert`). Dial Pad's `cli_not_verified` banner and its "Verify
now" action are covered in `DialPadScreen.test.tsx`. All four screens
are registered in `screenshotHarness/registry.tsx` *and* have a
corresponding `maestro/screens/cli-*.yaml` flow, so `claude-review.yml`'s
rendered-screenshot check actually captures them (a registry entry
alone isn't enough for CI to reach the screen); the Manage screen
(22d) makes a real `getCliStatus` request the harness doesn't mock,
so its flow asserts on the localized title test ID and captures the
loading state rather than a populated one there.

---

## 14.10 Home Package Balance Verification — US-17

US-17 must test the two distinct low-balance rules rather than applying one
percentage formula to both resources:

- data is healthy at exactly 20%, warning below 20%, and exhausted at zero;
- PSTN voice is healthy at exactly 5 minutes, warning below 5 minutes, and
  exhausted at zero, regardless of the percentage of purchased minutes left;
- `GET /packages/{id}/status` returns the immutable purchase snapshots
  (`data_gb_total`, `pstn_minutes_total`) with both remaining values, so the
  data denominator is never inferred from the first balance a device observes;
- the Home refresh timer performs a real status fetch at 60 seconds, while a
  failed/offline refresh retains both cached balances;
- the Home queued-events indicator is tested with check-in and SOS rows pending
  at the same time, and reports their combined count.

---

## 14.11 Amendment — Screenshot-Generation CI

Closes the gap flagged in §14.2's visual-compliance row and in
`claude-review.yml`'s own header comment: Claude's mobile review
workflow could only read code/diffs, never see an actual rendered
screen. `apps/mobile/screenshotHarness/` and
`.github/workflows/ci.yml`'s `screenshot-mobile-android` /
`screenshot-mobile-ios` jobs now generate real device/simulator
screenshots — see `apps/mobile/screenshotHarness/README.md` for the
harness design and how to add a new target.

**Why a harness instead of driving the real app:** `apps/mobile` has
no navigation library, no deep-linking, and no mock-server layer, so
there was no way to make the real running app land on an arbitrary
screen in CI. The harness instead mounts each target screen directly
with fixture props — the same approach the screen's own Jest/RNTL
tests already use — with a `global.fetch` override standing in for
the backend on the few screens that fetch on mount. A single APK/IPA
build serves every registered target; Maestro selects the target at
runtime via a picker screen, not per-screen rebuild.

**Currently covered** (`apps/mobile/maestro/screens/*.yaml`, 13
targets): OTP verification, PIN unlock, PIN setup, activation code
entry, package selection, eSIM QR code, eSIM activation (Android
automatic path and iOS manual-guide path, captured separately —
demonstrating the real platform divergence `frontend-mobile.md`
documents), activation success, SOS confirm, SOS sent, dial pad, and
active call.

**Explicitly out of scope, not faked:**

- **The native CallKit (iOS) / ConnectionService (Android) incoming-
  call UI.** This is OS-level chrome outside the app's own view
  hierarchy, only reachable via a real Apple PushKit VoIP push or a
  real FCM-triggered Headless JS task — neither is triggerable
  headlessly in CI on any tooling (Detox, Maestro, or otherwise),
  real device or simulator. The `active-call` target captures
  `ActiveCallScreen` (the in-app UI after a call connects) mounted
  directly with a fixture call session instead — a real, useful
  screen to review, but not a substitute for seeing the native call
  UI.
- **`EsimActivationFlow`'s real device-eSIM-slot detection**
  (`services/esimActivation.ts`) — an emulator/simulator can't
  meaningfully answer whether a device has an eSIM slot, so the
  harness mounts the flow's two presentational child screens
  directly instead of the real network+native-check container.
- **The rest of the screen inventory** (`frontend-mobile.md` §8.1
  lists 29+ screens; 13 are covered above) — the harness and Maestro
  flows are built to make adding one cheap (one registry entry, one
  YAML file), not to close every screen in this pass.
- **Per-PR iOS coverage.** `screenshot-mobile-ios` runs nightly plus
  on-demand (`workflow_dispatch`) only, not on every PR —
  `macos-15` GitHub-hosted runners bill at roughly 10x an
  `ubuntu-latest` minute, and this is testing infrastructure, not
  the safety-critical path. `screenshot-mobile-android` does run on
  every mobile-touching PR. Re-evaluate the iOS cadence if
  iOS-specific visual regressions start slipping through between
  nightly runs.

**Where the screenshots land:** both jobs upload full-resolution
PNGs as CI artifacts (`mobile-screenshots-android` /
`mobile-screenshots-ios`) and additionally render resized inline
previews directly in the job's Actions Summary tab, so a screen can
be visually checked without downloading anything.

**Verification history on this amendment:** the first real run
against live GitHub Actions infrastructure surfaced two genuine bugs
that no amount of local review would have caught — `takeScreenshot`
output landing in Maestro's own `--test-output-dir` tree rather than
the process's working directory (the collection step was silently
finding nothing), and 7 of the 13 registered screens failing to
render in time on-device due to a mix of causes: the harness's own
`fetchMock.ts` using `new Response(...)` (unreliable in the React
Native runtime), native hooks (`useNetworkQuality`,
`ensureAndroidCallingReady`) blocking on a real device, the picker
list needing `scrollUntilVisible` for lower items, and two PIN
screens' testID-based assertions being fragile on-device (now
text-based instead). All were root-caused from real failure logs and
fixed, not patched around — every run since (both platforms) has
passed 12/12 flows (`esim-activation-ios`/`esim-activation-android`
are platform-exclusive, so 12 run per platform out of the 13
registered targets) with real, independently-inspected screenshots
matching the harness's fixture data. Treat this the way `testing-qa.md`
treats PR #41 in §14.2: a concrete example of why CI passing on
first write is not the same as CI passing for real.

---

## 14.12 Amendment — Bilingual Screenshot Matrix

Each applicable Maestro flow now captures English and French after waiting for
the harness to confirm the selected runtime locale. The platform completeness
gate is therefore 32 PNGs (16 applicable targets × 2 locales), named with
`-en`/`-fr` suffixes. Existing Android per-PR and iOS nightly/on-demand cadence
is unchanged.

Review must explicitly check French expansion/wrapping, inaccessible actions,
SOS hierarchy, and the Android-automatic/iOS-manual eSIM divergence. The guide
frame is covered; final localized OS walkthrough imagery remains the content
gate documented in `localization.md` §6.

---

## 14.13 Amendment — Product Reset, Revised TDD Categories and Current Failures

**Recorded 8 September 2026 by build chunk 01. Registered story: US-27.**
Documentation only — no test, threshold or CI configuration changed. **No
coverage requirement above is lowered.**

### 14.13.1 Revised strict-TDD categories

§14.1's table is superseded by this one. The change is a consequence of the
product reset: SOS is scheduled for retirement, the remaining check-in scope
is a proposed default, and new categories also require explicit coverage.

| Feature category | TDD requirement |
|---|---|
| Authentication, sessions, recovery (`US-29`) | **Strict TDD required.** Unchanged in substance from §14.1. |
| Payments and idempotency (`US-32`, `US-33`, `US-34`) | **Strict TDD required.** Unchanged in substance from §14.1. |
| Tenant isolation and object-level authorization (`US-29`, `US-39`) | **Strict TDD required.** New. A cross-tenant read is a breach, not a bug; negative tests come first. |
| Order and provisioning idempotency, incl. accepted-but-response-lost (`US-32`, `US-35`) | **Strict TDD required.** New. This is the most expensive failure mode in the product and it is not reachable by manual testing. |
| Safety-transition tests during feature retirement (`US-30`) | **Strict TDD required.** New and time-limited. Removal must not orphan queued work or rebind it to the wrong account. |
| Ledger entry correctness and concurrency (`US-32`) | **Strict TDD required.** New. |
| Carrier usage ingestion and reconciliation (`US-36`) | TDD recommended — correctness depends on real supplier behavior; see §14.13.3. |
| eSIM provisioning device behavior (`US-35`, `US-38`) | TDD recommended — see the physical evidence requirement in AC-35.5. |
| Dashboard and consumer CRUD surfaces | TDD recommended. |
| UI polish, copy, styling | No TDD expectation. |

Check-in and SOS (`US-15`, `US-16`, `US-24`) retain strict TDD while any affected
path is supported or being transitioned. Changes to queues, retries and dispatch
must run the applicable full §14.4 offline/chaos suite, plus the account-switch,
restart and delayed-callback scenarios in AC-30.4. Declaring retirement in a
specification does not remove these obligations.

Chunk 04 must map each obsolete scenario to evidence that its feature, supported
old clients and jobs can no longer execute that path before retiring the test.
Remaining paths keep their applicable tests. Account isolation, history
preservation and safe shutdown remain required throughout the transition.

### 14.13.2 PostgreSQL is mandatory for database and concurrency behavior

Backend constraint, locking, isolation and concurrency checks run against
PostgreSQL, not an SQLite substitute. Mobile outboxes use SQLite: exercise their
actual persistence, migrations and restart behavior separately, including the
account-switch scenarios. This rule does not replace the mobile storage engine.

### 14.13.3 Mocks are not external evidence

A mock passing itself proves nothing about a vendor. Provider work needs a
documented contract check against current official documentation with the date
recorded, and the physical evidence in AC-35.5 for native voice. No screenshot
proves a native call. Do not add tests that mirror the implementation or chase a
coverage number.

### 14.13.4 Current failures — observed, not fixed

Observed 2026-09-08 against `develop` @ `6790c74`; full record in
[`implementation/BASELINE.md`](./implementation/BASELINE.md).

| Item | Status |
|---|---|
| `tests/test_auth_api.py::test_otp_request_and_verify_contract` | **Failing now.** `ExpiredSignatureError` → `InvalidRefreshTokenError` → `OTPError`. Owned by chunk 02, closed by AC-42.1. |
| API suite otherwise | 335 passing, coverage 87.13% against an 85% threshold. |
| iOS screenshot job | **Intermittent.** Failed 2026-09-07, succeeded 2026-09-08 with 32 PNGs on the same commit. Owned by chunk 02, closed by AC-42.2. |
| Mobile / dashboard / Docker jobs | Passing. |
| Staging deploy | Skipped on scheduled runs by the push-only condition; an API failure would also block an eligible push deployment. |

The historical "0/32 iOS screenshots" figure describes the 2026-09-07 run only.
It is **not** a current fact, and neither it nor the 32 images observed on
2026-09-08 carries into the redesigned matrix. §14.11 and §14.12's screenshot
matrices are re-cut against the reset screens in chunk 08 and enforced as a
release gate in chunk 27.

---

## 14.14 Amendment — Screenshot Matrix Validation and the iOS Driver Timeout

**Recorded 8 September 2026 by build chunk 02. Registered story: US-42
(AC-42.1, AC-42.2).**

### 14.14.1 The auth clock defect, diagnosed and fixed

`tests/test_auth_api.py::test_otp_request_and_verify_contract` failed on
`develop` from at least 2026-09-01 with `OTPError: invalid_refresh_token`,
raised from a PyJWT `ExpiredSignatureError`. It was not a flaky test and no
code had changed.

`TokenService.issue` mints tokens against an **injected** clock, and
`TokenService.decode_access` deliberately validates `exp` against that same
injected clock (`options={"verify_exp": False, "verify_iat": False}` plus a
manual comparison), because PyJWT's own checks always use real wall-clock time
regardless of the `now` they are handed. Two places did not follow that rule:

- `POST /auth/token/refresh` passed `datetime.now(timezone.utc)` instead of the
  application clock.
- `TokenService.rotate` left PyJWT's `exp` verification enabled.

The test clock is pinned to 2026-07-13, so a refresh token carried `exp` around
2026-08-12. The test passed when written and began failing the moment real time
passed that date — a July-versus-September mismatch that no rerun could clear.

Both paths now use the injected clock, matching `decode_access`,
`get_current_user` and `get_current_organization`. **Production expiry is
unchanged**: in production the injected clock *is* wall-clock
(`app.main.utc_now`), and `rotate` now enforces expiry twice — against the
token's own `exp` claim and against the stored refresh-token row — both compared
to `now`. `tests/test_auth_token_clock.py` pins valid, expired and exact-boundary
cases, plus revocation-on-rotation and signature tampering, so relaxing PyJWT's
check cannot silently relax expiry or authenticity.

### 14.14.2 The screenshot gate is a matrix, not a count

§14.12 stated the completeness gate as "32 PNGs (16 applicable targets × 2
locales)", and both CI jobs enforced it as `test "${#screenshots[@]}" -eq 32`.
A count is weaker than it looks. It accepts:

- 32 copies of one screen;
- a set where an expected screen is missing and an unrelated file makes up the
  number;
- zero-byte, truncated or non-PNG files;
- a degenerate 1×1 capture.

`apps/mobile/scripts/validateScreenshots.js` replaces it. The expected set is
**derived from the Maestro flows themselves** — each `takeScreenshot:` name is
one expected image, and a flow's `tags:` decide which platform runs it, matching
Maestro's `--exclude-tags` selection. The validator then requires exact set
equality and decodes every expected PNG, checking chunk CRCs and pixel data as
well as dimensions. Files are limited to 64 MiB and 25 million pixels before
decoding. The `yaml` parser accepts ordinary quoted names, inline tags and
comments. Dynamic names and nested runFlow/repeat/retry commands fail explicitly
until the matrix supports them; they cannot silently omit captures.

Two consequences worth stating plainly:

- **No count is hardcoded anywhere.** Adding or removing a `takeScreenshot:`
  changes the gate. When chunk 08 redefines the screen matrix and chunk 27
  enforces it for release, neither needs to update a magic number. The derived
  matrix currently comes to 32 per platform, which is how the previous hardcoded
  figure was confirmed correct rather than assumed.
- **It is not a visual regression test.** There are no committed baselines, so
  the validator cannot tell a correct screen from a wrong one that is
  structurally valid. Pixel comparison belongs with the redesigned matrix, not
  here; inventing baselines now would either accept anything or reject every
  legitimate UI change.

Negative coverage lives in `apps/mobile/scripts/validateScreenshots.test.js`:
empty directory, absent directory, missing image substituted by an unrelated PNG
at the same count, zero-byte image, non-PNG content, truncated write, and a 1×1
capture — run against both platform matrices.

### 14.14.3 The iOS screenshot job was flaky, not broken

The 2026-09-07 and 2026-09-08 nightlies ran the same application commit
(`6790c74`) with opposite outcomes. The logs give the reason directly:

| Run | XCUITest driver | Outcome |
|---|---|---|
| [2026-09-07](https://github.com/block-sig-hash/damdam/actions/runs/34094962267) | `IOSDriverTimeoutException: iOS driver not ready in time` after ~2m36s | 0 flows ran, 0 screenshots, job failed |
| [2026-09-08](https://github.com/block-sig-hash/damdam/actions/runs/34198388517) | ready in ~64s | 16/16 flows passed, 32 screenshots |

The app built and the simulator booted in both. Slow XCUITest cold start is a
plausible explanation, but these logs cannot distinguish it from a hung driver.
The job now sets
`MAESTRO_DRIVER_STARTUP_TIMEOUT: "300000"` — the remedy Maestro's own error
message names — at roughly 4.7× the observed healthy startup, still bounded so a
genuinely wedged driver fails rather than consuming the job's runtime.

This is a mitigation with a real limit: **it has not been observed passing a
previously-failing run, because that requires macOS CI, which was not available
during chunk 02.** It remains an evidence gap until a nightly run exercises it.
The Android job is left unchanged — its emulator path has not shown this failure,
and adding an unneeded timeout there would be speculative.

### 14.14.4 Documentation links are now a CI check

`ci.yml` gains a `Docs — Link validation` job running
`docs/implementation/tools/check-docs-links.sh` on documentation changes. The
implementation packet routes every chunk through relative links between chunk
files, review records, the story map and the specs; a broken link there drops an
assignment or an acceptance criterion silently. The checker covers relative file
links only — anchors and external URLs are out of its scope.

### 14.14.5 Automated Claude review is supplemental

`.github/workflows/claude-review.yml` is an advisory first-pass filter, not
chunk acceptance. Since the working split changed (`AGENTS.md`), Claude is the
implementer, so that workflow reviewing a Claude-authored PR is Claude reviewing
its own work. Acceptance requires the independent Codex review recorded in
`docs/implementation/reviews/NN.md`. The workflow's prompt now says so in its
posted comment and is forbidden from declaring a PR accepted or ready to merge.

### 14.14.6 Reproducible local toolchain, and what cannot be reproduced locally

Chunk 02's assignment requires that a missing platform prerequisite is never
reported as an application failure. These are the requirements to reproduce each
CI job locally, and the point at which local reproduction stops.

**API — fully reproducible locally.**

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt -r requirements-dev.txt
docker run -d --name dd-pg -e POSTGRES_USER=damdam_test -e POSTGRES_PASSWORD=damdam_test \
  -e POSTGRES_DB=damdam_test -p 55432:5432 postgres:16-alpine
export DATABASE_URL='postgresql+psycopg://damdam_test:damdam_test@localhost:55432/damdam_test'
export TEST_DATABASE_URL="$DATABASE_URL"
.venv/bin/alembic upgrade head   # required first: the *_postgres.py suites assume the schema
.venv/bin/pytest --cov=app && .venv/bin/ruff check . && .venv/bin/mypy app
```

Two failure modes here are environment, not application, and must not be
reported as defects:

- `sqlalchemy.exc.ArgumentError: Could not parse SQLAlchemy URL` in the
  `*_postgres.py` suites means `TEST_DATABASE_URL` is unset or malformed. Note
  that `export A=... B=$A` in one statement does **not** work — `$A` expands
  before `A` is assigned. Export them separately.
- Widespread `*_postgres.py` failures with a valid URL usually mean
  `alembic upgrade head` was not run first.

**Mobile — reproducible except for capture.** `npm ci && npm test && npm run lint
&& npm run type-check` runs anywhere. `scripts/validateScreenshots.js` needs only
Node plus the declared `yaml` and `pngjs` development dependencies (`npm ci`
first). Neither adds native binaries or changes the API image dependencies. Actually *producing*
screenshots needs an Android emulator with KVM, or macOS with Xcode; neither is
available in a typical Linux development container.

**Not reproducible without the corresponding platform access:**

| Evidence | Requires | Chunk 02 status |
|---|---|---|
| iOS screenshot capture, and confirmation of the driver-startup timeout | macOS runner with Xcode 16.1+ | **not run** — evidence gap, not a passing result |
| Android screenshot capture | Linux host with KVM | not run |
| Multi-arch `linux/arm64` image build | QEMU + buildx, long emulated build | see the independent review for current build evidence; no API dependency changed |
| Signed builds, store submission | Apple/Google credentials (D6) | out of scope for chunk 02 |
| Staging or production deployment | deployment secrets, push to a deploy branch | out of scope; deployment is push-only by design |

A missing prerequisite in this table is recorded as **NOT RUN with its reason**.
It is never recorded as a pass, and never as an application defect.

### 14.14.7 Independent review corrections

The shared decoder now applies expiry, issued-at and not-before to the same
application clock for consumer tokens, organization access and organization
email verification. Future dates and malformed/nonfinite claims are rejected;
production still uses UTC wall-clock time. Refresh rotation locks its PostgreSQL
row and checks stored ownership, expiry and revocation before replacing it.

`tests/test_auth_clock_postgres.py` checks clocks before and after real time,
invalid dates, stored expiry, concurrent reuse and organization verification
against isolated PostgreSQL schemas. Existing SQLite unit suites remain in the
repository; they are not the evidence for database locking. The signature-
tampering regression changes actual signature bits, not unused base64 padding.

The screenshot tests additionally reject corrupt or absent IDAT data with an
otherwise intact header/end, and cover YAML quoting and unsupported nested
flows. Their Jest environment is Node so the parser resolves its Node export.
Only the PNG fixture's CRC32 calculation receives a bitwise lint exception.

Changing `ci.yml` selects all four existing application/build path filters,
including dashboard. Dashboard checks therefore apply to this chunk even though
its application source is unchanged. Review results and remaining native CI
requirements are recorded separately in the chunk's independent review record.
