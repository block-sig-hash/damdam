# Chunk 30 release handoff — preparatory NO-GO dossier

Prepared 24 September 2026 for review. **Decision: NO-GO.** This is neither a
production release candidate nor an authorization to merge, distribute,
purchase, deploy or submit an app. The candidate SHA is intentionally **unset**:
the accepted preparatory chunk 29 head is `d7fe6d26c06705afc490ab4e13ebba9dbfa83e37`,
but final source/configuration, signed builds and physical evidence do not yet
exist. Do not create a release tag or sign a production signoff from this branch.

## Candidate identity and capability manifest

| Inventory at preparatory base | Observed value | Still required |
|---|---|---|
| Native application versions | Android `versionCode 1` / `versionName 1.0`; iOS build `1` / marketing `1.0` | Release owner approves monotonic build numbers and records final artifact versions |
| Database source revision | Alembic `0044_operator_actions` | Record applied staging/production revision, populated upgrade and restore evidence |
| Build configuration | `apps/mobile/eas.json` has local version source and production AAB profile; no approved EAS project/credential identity | Approve EAS project, profile, team/upload certificate, native configuration and artifact comparison |
| Runtime configuration | No approved production redacted manifest or SHA-256 | Freeze and hash exact deployment configuration, routes, flags, secrets references and seller/market matrix |

The three release channels are **not proposed as enabled**. Carrier eSIM,
mobile internet calling and browser internet calling each require a reviewed
`ENABLED`/`DISABLED` decision in the eventual
[release signoff template](../../release-signoffs/TEMPLATE.md). A disabled
channel requires a passing server-side negative eligibility test; a draft
flag or missing provider account is not proof of denial. At least one channel
must be enabled for an actual release. Until then, this dossier makes no
customer-facing offer or market claim. D1–D6 and V01 B1–B5 are not waived by
one channel's simulated tests.

## Evidence reconciliation before freezing a real candidate

| Gate | Current finding | Closure evidence and accountable role |
|---|---|---|
| Independent findings and exact-head checks | Chunk 27–29 preparatory reviews accepted; open combined journeys and cloud signing compatibility remain | Engineering owner closes findings, reruns affected checks on final SHA, records review disposition and CI run IDs |
| WAL-G CI test dependency | **BLOCKED** on chunk 30 runs: pinned Quay MinIO server/client images return `unauthorized`/no manifest, so the PITR job is not green | CI/operations owner restores a trusted reproducible S3-compatible fixture and reruns the real archive/PITR drill; do not skip or infer a pass from chunk 29 |
| EAS iOS/Android signed cloud builds | **BLOCKED**: no approved project/signing identities; Android EAS-shaped callback encountered Gradle 9.3.1 `storeFilePath` finalization | Release owner approves credentials; mobile engineer proves compatible signing route, builds same SHA, compares AAB/IPA hashes and signing identities independently |
| Automated native CI | Prior chunk 29 SHA `e1ff1de` passed Android emulator and iOS simulator 36 flows/72 PNGs each; not evidence for a later final SHA | CI owner runs both jobs on exact frozen SHA and records both artifact IDs, flow results, source/config comparison |
| Internal physical distribution | **BLOCKED**: no approved TestFlight/Play identities or consenting testers | Release owner authorizes groups/track; named testers install signed builds on actual iOS/Android devices and record build/device/OS |
| Real carrier eSIM, data and native calls | **BLOCKED**: no live pilot access, spend limit or physical results | Pilot lead follows [chunk 29 runbook](29-PILOT-RUNBOOK.md); record real install, Wi-Fi-off data/usage and native-dialer call with app closed, per approved offer/device/network |
| Internet calling | V01–V05 preparatory software only; no live SDK/media/route/cost proof | Separate approved route, device/browser, audio, DTMF, identity, cutoff and charge evidence before enabling either channel |
| Merchant, enterprise and operations | D1–D6 open; no approved seller/processor/pilot organization, settled pilot or representative staging restore | Founder/commercial/finance owners approve scope; pilot and operations owners record reconciled scenarios and tested rollback |

The exact-head signoff validator requires EAS and native-CI source SHAs, both
signed cloud artifacts, both physical internal installs, a config-compatibility
assessment, cleared blocking findings and approved pilot limits. Its Ed25519
signature proves the release owner signed the text; it cannot attest that a
remote artifact is real. The release owner verifies each immutable locator and
the source, runtime configuration, capability/route manifest, package/bundle
identity and build number across CI, EAS, internal installs, pilot and target
deployment. Any mismatch needs a new candidate and affected retests. Changes
to payment, carrier or calling behavior require repeating relevant physical
pilot evidence, not simply re-signing old results. CI, EAS and generic device
labs do not replace real eSIM/data/native-call evidence.

## Findings and launch checklist still open

- Chunk 28 has not demonstrated one combined checkout-to-refund journey,
  historical enterprise money accounting, import-to-offboard/report, combined
  V02–V05 failure behavior, deployed old-client compatibility or a populated
  staging migration rollback. Keep these as open findings until fixed and
  retested, or obtain an explicit scoped release decision that does not mask
  a mandatory signoff scenario.
- Chunk 26's local PITR and role tests do not prove production role adoption,
  representative restore/rollback, provider outage or exactly-once external
  notification delivery. Define incident containment for possible duplicate
  notifications before a live pilot.
- The [production checklist](../IMPLEMENTATION-PLAN.md#10-production-launch-checklist)
  remains open for legal entity, approved seller/merchant, carrier agreement,
  markets/devices, real consumer and enterprise journeys, reconciliation,
  hard spending controls, disclosures, accessibility/localization, production
  configuration, signing and monitoring. D1–D6 ownership is in that plan;
  V01 B1–B5 remain separately open in the
  [calling amendment](../VOICE-EXPANSION.md).
- Chunk 27's trusted release-status GitHub App, protected release environment,
  externally provisioned release-owner key, strict required status and merge
  queue are not bootstrapped. Local validator success cannot promote code.

## Operator ownership, stop rules and rollback draft

Names, contacts, backup contacts, response windows and thresholds are **not
assigned or approved**. The release owner must fill and exercise the following
in a restricted operations record before a pilot or production cutover:

| Role to assign | Required decision and recorded evidence |
|---|---|
| Release/incident commander and backup | Approve candidate/market/capability scope, on-call route, severity policy, stop authority and communication tree |
| Carrier and payments incident responders | Define provider escalation, fulfillment suspension, charge/provisioning correlation and adverse-event containment |
| Finance/refund owner and backup | Approve original-payer/currency refund path, supplier–ledger–merchant variance threshold, dispute owner and daily reconciliation |
| Support/privacy owner and backup | Approve customer response window, escalation to engineering/security, redaction/retention and disclosure correction process |
| Database/deployment/rollback owner and backup | Prove staging migration rehearsal, pre-cutover restore point, compatible old-client/worker behavior, rollback/roll-forward command set and decision time |

Before exposure, the founder approves a written maximum pilot spend, eligible
markets/offers/testers, provisioning success and latency limits, call setup/drop
and cost limits, usage/reconciliation delay, payment-failure and support-response
thresholds. Values are deliberately blank, not implicitly infinite. The
incident commander stops new sales/provisioning/call authorizations on any
duplicate charge/profile, unexplained ledger variance, missing carrier usage,
unbounded call exposure, privacy leak, unsupported route, unsafe migration or
breached approved threshold. Preserve masked correlation IDs and supplier
receipts; continue reconciliation/refunds and existing-call liability handling
even when new sales are disabled. Finance owns customer remediation.

The rollback rehearsal must first establish a restorable database and artifact
snapshot, migration compatibility and feature-flag/route denial behavior.
Prefer disabling new eligibility and rolling forward when a downgrade would
discard financial or audit data; do not assume Alembic downgrade is safe. Any
binary rollback must demonstrate compatibility with the current schema,
queued workers and already provisioned lines. A production rollback is an
authorized incident action by the named owner, not a command to execute from
this document.

## Reviewable rollout and store asset checklist

1. Assign people and approvals; close D1–D6/B1–B5 for the channel actually
   proposed. Record product, legal, privacy, merchant and provider signoffs.
2. Reconcile open findings; freeze a new exact source SHA, version numbers,
   schema revision, config hash and capability manifest. Run full CI, both
   native jobs, migration/restore rehearsal and independent review.
3. With separate release-owner authorization, verify signed EAS builds and
   internal tracks; obtain physical install and pilot reports using the
   [blank evidence forms](29-PILOT-EVIDENCE.md). Compare all hashes and
   configuration before asking the release owner to sign the immutable
   signoff. Any failure returns to step 2.
4. Prepare, review and localize store title/description, supported markets and
   devices, accurate screenshots, support/privacy/terms/refund URLs, data-safety
   and payment declarations, entitlements/permissions, age/telecom disclosures
   and reviewer notes. The [draft privacy worklist](27-SIGNING-PRIVACY.md)
   is not counsel/store approval. No upload or invitation is authorized here.
5. Only after a signed, verified signoff and separately authorized promotion,
   use a staged rollout with named on-call/finance/support owners, live alert
   routing, explicit stop thresholds, reconciliation cadence and rollback
   decision time. Do not infer launch approval from a merged PR.

The final decision is **NO-GO until every mandatory gate has real compatible
evidence and no blocking finding remains**. The release owner may later create
a real candidate and signoff; this document is only the reviewable handoff.
