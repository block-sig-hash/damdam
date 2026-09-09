# Retention and backfill plan for retired-feature data

Produced by [chunk 04](../chunks/04-safe-feature-retirement.md), subchunk 04E
(US-30), on **9 September 2026**.

**This plan is a dry run. Nothing in chunk 04 executes it.** No production
deletion has been performed, no historical migration has been dropped, and no
table has been altered. `apps/api/scripts/retirement_dry_run.py` reports what
each step would affect; it opens a read-only session, counts rows and prints a
report, and a test asserts that running it changes no row.

## Why this is a plan and not an action

Two separate reasons, and both must clear before any of it runs.

1. **The check-in disposition is still a proposed default.**
   [SCOPE-DISPOSITION.md](../SCOPE-DISPOSITION.md) gates irreversible removal of
   remaining welfare data on a founder decision that has not been recorded.
   Retiring the *behavior* is reversible — every commit in chunk 04 can be
   reverted and the data is still there. Deleting the rows is not.
2. **The data is personal data under an approved retention policy**, not
   incidental leftovers of a feature. Deleting it belongs to that policy, at its
   defined periods, with its audit trail — not to a feature removal that happens
   to be nearby.

## What chunk 04 left behind

| Table | Contents | Disposition |
|---|---|---|
| `check_ins` | Welfare records with coordinates | **Gated on the founder decision.** |
| `check_in_notifications` | Delivery state for the above | Follows `check_ins`. |
| `sos_alerts` | Alert records with coordinates | Removal authorized; still on the 3-year policy period. |
| `sos_notifications` | Delivery state for the above | Follows `sos_alerts`. |
| `family_contacts` | Names and phone numbers of **third parties** | Removal authorized; see below. |
| `destination_geofences` | Configuration, not personal data | Retain until chunk 09's catalog supersedes it. |
| `verified_caller_identities` | Deferred, not retired (D2) | Do not delete without a D2 decision. |
| `caller_id_consents` | Consent evidence | Keep for the statutory period even if identities go. |
| `voice_credentials` | SIP credentials for retired app calling | Revoke provider-side **before** deleting rows. |

`call_logs` is **not** on this list. Call history is financial history and is
explicitly retained.

**`family_contacts` deserves separate attention.** It holds names and phone
numbers of people who never used DamDam and never agreed to anything — they were
nominated by someone else. They are the group with the weakest relationship to
the service and the strongest claim to erasure, and the feature that justified
holding their data no longer exists. This is the one row set where the argument
for prompt deletion is stronger than the argument for waiting.

## The existing sweeps still run, and that is deliberate

`app.retention.null_checkin_locations` (02:00 daily) and
`app.retention.delete_sos_alerts` (02:10 daily) were **not** removed with the
features. Retiring a feature must not switch off data minimization for the data
it leaves behind: coordinates keep being nulled at their retention date and SOS
alerts keep aging out at three years, with the same audit trail as before.

That means the retired data is already shrinking on the approved schedule
without any decision being taken. Waiting for the founder is therefore not the
same as holding the data indefinitely.

## Sequence, when it is authorized

Each step is independently reversible up to the point named, and each requires
its own authorization. Run the dry run first and record the counts.

1. **Record the decision.** Append the founder's check-in disposition to
   [DECISIONS.md](../DECISIONS.md) using the format that file defines. Without
   this, steps 3 and 5 do not start.
2. **Revoke provider-side voice credentials** before deleting
   `voice_credentials`, so no orphaned SIP identity is left registered with
   Telnyx. Deleting the rows first loses the identifiers needed to revoke them.
3. **Delete `family_contacts`**, with an audit record per row, under the
   existing retention machinery rather than an ad-hoc script.
4. **Let the sweeps finish `sos_alerts`** rather than bulk-deleting, unless the
   decision is to erase early. The audit trail is better and the code exists.
5. **Delete `check_ins` and `check_in_notifications`** only after step 1.
6. **Drop the tables — later, and not here.** Schema removal follows the
   migration sequence in [IMPLEMENTATION-PLAN.md](../IMPLEMENTATION-PLAN.md) §7
   Phase 1, after compatibility requirements end. Chunk 04 adds no migration and
   drops nothing.

## Device-local data

The mobile queues were removed in 04C, but **`damdam-safety.sqlite` is still on
every device that ran a build containing them.** It may hold unsent rows and the
`<table>_quarantine` tables 04A created, both of which contain timestamps and
coordinates.

Nothing in the app reads or writes that file any more —
`apps/mobile/src/featureRetirement.test.ts` fails if anything does. It was
deliberately not deleted: erasing a user's data from their device is exactly the
irreversible step gated above, and doing it silently during an app upgrade is
worse than doing it deliberately later.

When the decision is recorded, deleting the file belongs in the same app release
as the surrounding cleanup, with the deletion attempted once and failure treated
as non-fatal.

## What was not counted

The dry run reports what is in whatever database it is pointed at. **No
production database was queried while writing this plan** — there is no
production deployment in the queried history, and the staging environment is
missing its four required secrets (D6/chunk 26). The counts that matter for the
founder decision have therefore not been taken yet; the tool to take them now
exists.
