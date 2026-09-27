# Chunk 29 pilot evidence forms — blank templates

Copy these forms into a restricted pilot record after authorization. Enter
`PASS`, `FAIL`, `BLOCKED` or `NOT APPLICABLE` for every applicable row. Blank
rows are not passing evidence. Store raw artifacts in an approved restricted
location and put only opaque locators here. Do **not** store activation codes,
ICCID/IMSI, full telephone numbers, payment tokens, private audio, API keys or
customer records in the repository.

## Approval and build record

| Field | Value |
|---|---|
| Pilot record ID / date / lead / independent reviewer | |
| Founder/release-owner approval reference, scope and expiry | |
| Carrier/merchant/legal-market approval references | |
| Maximum authorized spend/currency and stop authority | |
| EAS organization/project ID and approved account reference | |
| Source SHA, config hash, app version/build, EAS CLI/profile | |
| iOS build ID / IPA checksum / Apple team/certificate/profile comparison | |
| Android build ID / AAB checksum / upload-certificate SHA-256 comparison | |
| Same-head iOS simulator / Android emulator CI run and artifact locators | |
| TestFlight / Play internal group approval; invitation and install evidence | |
| Signing/privacy/entitlements reviewer, date and verdict | |

## Physical device and offer record — copy per platform/market/offer

| Field | Value |
|---|---|
| Scenario ID, tester consent and artifact locator | |
| Build/source/config; device model/OS/eSIM support | |
| Country, visited network, date/time zone, dual-SIM/default data | |
| Approved market, offer, quote/rate version, currency/tax/seller | |
| Purchase / merchant capture / order / ledger / receipt correlation IDs | |
| Supplier operation and profile/install correlation IDs (opaque only) | |
| Installation method, device-reported result and retry/failure behavior | |
| Wi-Fi-off cellular traffic amount/time; device and supplier data counters | |
| Supplier event/ingest time, displayed usage, lag and accepted threshold | |
| Top-up, hard carrier cap and observed enforcement (or not offered) | |
| Native Nigeria mobile/landline result with DamDam closed | |
| SIM/CLI, two-way audio, DTMF, duration, interruption/recovery | |
| Carrier CDR/rate/invoice vs ledger/merchant amount and variance | |
| Inbound/caller ID only if sold; separate internet-call gate | |
| Defects, financial/privacy stop, owner, fix SHA and retest result | |
| Tester / finance / release-owner review and dates | |

## Enterprise run — copy per approved organization

| Field | Value |
|---|---|
| Organization pilot ID, admin/employee consent, tenant/MFA evidence | |
| Roster valid/duplicate/rejected counts; cross-tenant access check | |
| Approved funding, merchant/ledger/receipt correlation and variance | |
| Bulk order count, partial failures, allocations, duplicate check | |
| Employee physical install, supplier status and usage/spend report | |
| Offboarding access, carrier suspension, refund/balance and audit | |
| Defects, owner, stop decision, fix SHA and retest | |
| Admin / finance / support / release-owner reviews and dates | |

## Final gate reconciliation — never infer from another row

| Mandatory gate | Status | Evidence locator / blocker / reviewer |
|---|---|---|
| Approved source and both signed EAS cloud artifacts | | |
| Exact-head iOS simulator and Android emulator CI | | |
| Consenting physical iOS and Android internal installs | | |
| Real approved eSIM provision and physical installation | | |
| Real Wi-Fi-off cellular data and supplier usage reconciliation | | |
| Real native-dialer Nigeria call with DamDam closed where offered | | |
| Merchant, carrier and ledger reconciliation within approved tolerance | | |
| Enterprise pilot and offboarding where offered | | |
| D1–D6, V01 B1–B5 and blocking findings disposition | | |
| Release-owner final decision, date and exact candidate SHA | | |

Any `BLOCKED`, `FAIL` or blank mandatory row means **no release readiness**.
