# Retirement inventory — chunk 04, before any behavior change

Produced by [chunk 04](../chunks/04-safe-feature-retirement.md) (US-30) on
**9 September 2026**, against base `12582f101e4ca7e6a6c6d55d93470444b7ec7cd3`
(`origin/develop` carrying accepted chunks 01 and 02).

The assignment requires this inventory **before** changing behavior. It is a
static inspection of the checked-out code. Where a fact can only come from a
running deployment, it is recorded as unknown rather than guessed.

## 1. What is being retired, and on whose authority

| Scope | Authority | Status |
|---|---|---|
| Family contacts | User's explicit decision (plan §1) | **Authorized** |
| Offline SOS | User's explicit decision (plan §1) | **Authorized** |
| Arrival geofencing | Follows the Hajj/destination reset | **Authorized** |
| Launch external-CLI verification | Deferred by the user (D2) | **Authorized to remove from the launch dependency graph** |
| WebRTC / CallKit / VoIP-push app calling | Not the launch mechanism (plan §1) | **Authorized to remove where unused** |
| Remaining check-in / welfare workflow | Plan §1 "recommended scope interpretation" | **PROPOSED, not confirmed.** Owner: founder/product |

Per [SCOPE-DISPOSITION.md](../SCOPE-DISPOSITION.md), reversible inventory,
isolation and migration preparation may proceed for the check-in workflow, and
the authorized family/SOS removal may proceed. **Irreversible removal of
remaining welfare data, or a launch promise about that service, waits for the
founder's confirmation.** Chunk 04 does not execute that deletion.

## 2. Server-side surface

### 2.1 Routes registered in `app/main.py`

| Router | Prefix | Endpoints |
|---|---|---|
| `checkin_router` | `/v1` | `POST /checkins`, `GET /me/checkins`, `GET /webhooks/meta/whatsapp`, `POST /webhooks/meta/whatsapp` |
| `sos_router` | `/v1` | `POST /sos`, `POST /sos/{alert_id}/cancel`, `GET /hto/sos-alerts`, `POST /hto/sos-alerts/{alert_id}/resolve`, `POST /hto/push-subscriptions` |
| `profile_router` | `/v1` | `DELETE /account`, `POST`/`PATCH /family-contact`, `GET /emergency-contact` |
| `voice_router` | `/v1` | `GET /voice/eligibility`, `POST /voice/token`, four CLI verification endpoints, `POST /voice/cli/revoke`, `POST /voice/cli/lost-sim`, `GET /voice/cli/status`, `POST /webhooks/telnyx/call-events`, `GET /me/calls` |

`DELETE /account` inside `profile_router` is **retained** — account deletion is a
current product requirement (`US-38` AC-38.4) and must survive this chunk.

### 2.2 Modules

| Module | Lines | Disposition |
|---|---|---|
| `app/checkins/` | 669 | Retire (welfare — pending confirmation for data deletion) |
| `app/sos/` | 906 | Retire |
| `app/profile/family_contacts.py`, `emergency_contact.py` | part of 422 | Retire |
| `app/profile/device_tokens.py`, `routes.py` (`DELETE /account`) | part of 422 | **Retain** |
| `app/voice/` | 1638 | Split: CLI verification and WebRTC credentials retire; call/billing concepts retained for chunk 15 |
| `app/notifications/` | 614 | **Retain** the service; retire feature-specific dispatch |
| `app/retention/` | 328 | **Retain**; its check-in/SOS sweeps change with the features |

### 2.3 Tables

`check_ins`, `check_in_notifications`, `sos_alerts`, `sos_notifications`,
`family_contacts`, `verified_caller_identities`, `caller_id_consents`,
`voice_credentials`, `destination_geofences`.

Retained: `device_tokens`, `call_logs` (financial/audit history), and every
order, payment and audit table.

**No table is dropped by chunk 04.** Schema removal follows the migration
sequence in `IMPLEMENTATION-PLAN.md` §7 Phase 1 and happens only after
compatibility requirements end.

### 2.4 Scheduled jobs (`app/worker.py`)

| Task | Schedule | Disposition |
|---|---|---|
| `app.checkins.enqueue_due_fallbacks` | every 30s | Retire with the feature |
| `app.checkins.enqueue_pending` | every 30s | Retire with the feature |
| `app.sos.enqueue_pending` | every 10s | Retire |
| `app.sos.enqueue_due_fallbacks` | every 10s | Retire |
| `app.sos.dispatch`, `app.sos.sms_fallback` | on demand | Retire |
| `app.retention.null_checkin_locations` | 02:00 daily | Changes with the feature |
| `app.retention.delete_sos_alerts` | 02:10 daily | Changes with the feature |
| `app.esim.enqueue_due`, other `app.retention.*` | various | **Retain** |

**These beat entries are the highest-risk item in the whole retirement.** Four
of them poll every 10–30 seconds. If routes or models are removed while a worker
still runs the old schedule, the worker crashes in a loop or — worse — keeps
dispatching notifications for a feature the product no longer offers. Dispatch
must be disabled **before** removal, not with it.

### 2.5 Notification channels

`app/notifications/service.py` exposes `EmailSender`, `WhatsAppSender` and
`SMSNotificationSender`. Check-in and SOS dispatch use WhatsApp with an SMS
fallback; `check_in_notifications` and `sos_notifications` track delivery state.
The senders are shared infrastructure and are **retained**; only the
feature-specific dispatch paths retire.

## 3. Client-side surface

### 3.1 Mobile

| Path | Disposition |
|---|---|
| `src/screens/SosConfirm`, `SosSent` | Retire |
| `src/screens/CliVerification` | Retire |
| `src/screens/ActiveCall`, `DialPad` | Retire as app-calling UI (native dialer replaces them) |
| `src/services/checkInOutbox.ts`, `sosOutbox.ts` | **Isolate first, retire second** — see §4 |
| `src/services/checkInLocation.ts`, `checkInBackground.ts`, `arrivalPrompts.ts` | Retire |
| `src/services/deviceContacts.ts` | Retire |
| `src/services/callKit.ts`, `voiceGateway.ts` | Retire from the launch dependency graph |
| `src/api/checkInClient.ts`, `sosClient.ts`, `familyContactClient.ts`, `emergencyContactClient.ts`, `cliClient.ts`, `voiceClient.ts` | Retire |
| `src/services/sessionStore.ts` | **Retain and change** — see §4 |

### 3.2 Dashboard

`app/sos-alerts/` retires. `app/admin/sos-notifications/` retires.

### 3.3 Native permissions

`apps/mobile/android/app/src/main/AndroidManifest.xml` currently declares
`ACCESS_FINE_LOCATION`, `ACCESS_BACKGROUND_LOCATION`, `READ_CONTACTS`,
`RECORD_AUDIO`, `MODIFY_AUDIO_SETTINGS`, `FOREGROUND_SERVICE`,
`FOREGROUND_SERVICE_PHONE_CALL`.

`apps/mobile/ios/DamDam/Info.plist` declares
`NSLocationWhenInUseUsageDescription`,
`NSLocationAlwaysAndWhenInUseUsageDescription` (both referencing check-in and
Saudi-arrival detection), `NSContactsUsageDescription`,
`NSMicrophoneUsageDescription`, and `UIBackgroundModes` including `voip`.

Every one of those exists for a feature being retired. `US-30` AC-30.5 requires
they be gone from release builds. `WRITE_EMBEDDED_SUBSCRIPTIONS`,
`POST_NOTIFICATIONS`, `INTERNET`, `ACCESS_NETWORK_STATE` and the euicc/telephony
features are **retained**.

## 4. Finding 1 — the account-isolation defect, confirmed by inspection

This is the defect the original review reported and the reason the plan says to
ship isolation before further release.

**Confirmed in the checked-out code:**

1. `NitroCheckInOutbox.initialize()` (`services/checkInOutbox.ts:41`) creates
   `checkin_outbox` with columns `client_generated_id`, `timestamp`,
   `latitude`, `longitude`. `NitroSOSOutbox.initialize()`
   (`services/sosOutbox.ts:35`) creates `sos_outbox` with the same four columns.
   **Neither table records an owner.**
2. Both open the same device-wide database file, `damdam-safety.sqlite`. It is
   not per-account and is not cleared on sign-out.
3. `pending()` in both files is `SELECT ... FROM <table> ORDER BY timestamp ASC`
   with **no owner predicate**, so it returns every queued row on the device
   regardless of who is signed in.
4. `SOSSyncService.performSync()` (`sosOutbox.ts:139`) and its check-in
   counterpart iterate `pending()` and call `this.send(item)`, where `send` was
   bound to whatever access token was current when the service was constructed.
5. `AuthenticatedApp.tsx:92-124` builds both services inside `useMemo` keyed on
   **`accessToken` only**. No user identity participates in construction,
   filtering or dispatch.
6. `clearSession()` (`sessionStore.ts:81`) only resets the Keychain entry. It
   does **not** clear the outboxes, and it does not stop the 10-second
   `setInterval` started by `SOSSyncService.start()`.
7. `PersistedSession` stores `phoneNumber` but **no user id**, so today the
   client cannot even name the owner of a queued row.

**The failure, precisely:** user A queues a check-in or SOS while offline and
signs out. User B signs in on the same device. The sync timer fires, `pending()`
returns A's rows, and they are POSTed with B's token. The server creates them
for the authenticated user — B — because nothing in the request identifies A.
The record is not merely mis-labelled; it is genuinely created as B's, and no
server-side check can detect it.

Two aggravating variants, both named in AC-30.4:

- **Process restart** — the rows are on disk, so a restart re-reads and re-sends
  them under whoever signs in next.
- **Delayed callback** — a `send()` already in flight when the account switches
  resolves afterwards and calls `remove()` and `onSynced()` against the new
  session's state.

**Server-side scoping does not mitigate this.** `POST /v1/checkins` and
`POST /v1/sos` derive the owner from the bearer token, which is exactly the
mechanism being subverted.

## 5. Unknown without a running deployment

Recorded honestly rather than assumed:

- **How many clients are deployed, and on what versions.** No telemetry was
  consulted. The last recorded staging deployment was 2026-07-28 and there is no
  production deployment in the queried history (`BASELINE.md`), so there may be
  no affected installed base at all — but that is not established.
- **How many `check_ins`, `sos_alerts`, `family_contacts` rows exist**, and
  whether any carry untrustworthy ownership.
- **Whether any queued client-side rows exist in the field.**
- **Whether workers are currently running the beat schedule anywhere.**

These matter for sequencing, not for correctness of the isolation fix. The fix
is safe whether or not an installed base exists; the *removal* sequencing is
what needs these numbers, and chunk 04 must not invent them.

## 6. Proposed subchunks

The full assignment spans two backend module removals, a mobile navigation and
permission change, a dashboard removal, a retention plan and a release-gate
change. Delivered as one diff it would be unreviewable, which the assignment
explicitly warns against. Proposed split:

| Subchunk | Scope | Depends on |
|---|---|---|
| **04A** | Inventory; account isolation and quarantine for both offline queues; strict-TDD safety-transition tests | — |
| **04B** | Disable new enrollment and retired dispatch server-side; explicit retired/upgrade responses for old clients; stop the beat entries | 04A |
| **04C** | Remove mobile screens, services, API clients and native permissions; remove dashboard SOS surfaces; keep the app bootable | 04B |
| **04D** | Remove CLI verification and WebRTC/CallKit/VoIP-push dependencies where unused | 04C |
| **04E** | Dry-run retention/backfill plan; obsolete release-gate changes | 04B–04D |

### What was actually delivered

All five subchunks, in the order above, one commit each.

04B and 04C each grew slightly beyond the split proposed here, in both cases
because the original boundary would have left a feature half-retired:

- **Arrival geofencing** spans both tiers. 04C removes the client, so it also
  retires `GET /packages/{id}/geofence`; removing only the caller would have
  left a live endpoint for a retired feature.
- **The operator welfare roster** is a server projection, not a screen.
  `GET /hto/pilgrims` reported `last_checkin_at` and `sos_status` for every
  person on a manifest. Deleting the dashboard pages alone would have satisfied
  the letter of "remove the SOS surfaces" while leaving exactly the welfare
  tracking [SCOPE-DISPOSITION.md](../SCOPE-DISPOSITION.md) says must not be
  quietly retained, so the fields and the queries behind them went too.

Server-side dead code was removed in the same commit that made it unreachable
rather than left for a later subchunk. Retiring a route while keeping its
service and deleting the tests that covered it would have dropped coverage
below the 85% gate — the choice was between removing the code and weakening the
gate.
