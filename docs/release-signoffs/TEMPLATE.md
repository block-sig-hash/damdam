# Release signoff — reset product

Copy to `docs/release-signoffs/<tested-40-character-commit-sha>.md` only after
the candidate commit and its exact tracked configuration have been tested. Add
the signoff in a later commit; **do not change any other tracked file after the
tested commit**. Add its matching `<tested-sha>.md.sig` sidecar containing a
base64 Ed25519 signature over the exact UTF-8 `.md` bytes (including the final
newline). The release owner signs only after personally verifying every
external evidence reference, physical test and approval against the candidate.
The private key must remain in the approved signing service, never in this
repository, CI or a release artifact. The public key is provisioned separately
as the repository variable `DAMDAM_RELEASE_PUBLIC_KEY_B64` (base64 PEM). The
promotion check reads both files from the PR head and rejects unsigned or
altered evidence, post-test changes, future dates, missing evidence and every
`FAIL`. It also requires the tested SHA to equal the current `staging` head.
Existing historical signoffs and tags are not rewritten.

These are evidence references, not secrets. Refer to immutable build artifacts,
redacted configuration snapshots, signed carrier/merchant approvals, actual
physical-device records, migration/restore reports and incident ownership. A
CI or emulator result is not a physical-device or provider result. The release
owner must verify external references before signing; CI checks the signature,
structure and git ancestry, not the truth of a remote evidence ID.
Every mandatory evidence reference in the fields and tables below must be
exactly `sha256:<64 lowercase hex characters>`: the SHA-256 of an immutable,
restricted evidence record or manifest that binds multiple artifacts. Free-form
prose, approval-status words and bare build IDs are not references. The schema
field must be `applied_revision @ sha256:<64 lowercase hex characters>`.
The release owner still has to inspect the underlying record and confirm the
actual approval, source/configuration and artifacts; a digest alone does not
prove that a test or approval occurred.

- **Commit SHA:** <full tested commit SHA matching filename>
- **Tester name:** <release owner>
- **Date:** <YYYY-MM-DD, UTC>
- **Environment:** production
- **Runtime configuration SHA-256:** <64 hex digits of redacted deployment configuration manifest>
- **Carrier configuration reference:** <immutable carrier evidence ID, or disabled if carrier channel disabled>
- **Merchant configuration reference:** <immutable approved merchant and settlement evidence ID>
- **Schema revision:** <applied_revision @ sha256:64 lowercase hex characters>
- **Accepted dependency commits:** <comma-separated full merge/accepted commit SHAs>
- **Release markets:** <approved selling, visited, origin and destination market evidence ID>
- **Release manifest reference:** <immutable capability/flag/route manifest evidence ID>
- **Mock supplier mode:** disabled
- **Signed Android build evidence:** <signed AAB/APK artifact and signing-certificate evidence ID>
- **Signed iOS build evidence:** <signed IPA/archive artifact and provisioning evidence ID>
- **EAS build source SHA:** <full tested commit SHA shared by both EAS cloud builds>
- **Android EAS signed artifact evidence:** <cloud build ID, AAB hash and independently checked upload-certificate evidence ID>
- **iOS EAS signed artifact evidence:** <cloud build ID, IPA hash and independently checked team/certificate/profile evidence ID>
- **Native CI source SHA:** <full tested commit SHA shared by Android emulator and iOS simulator runs>
- **Native simulator/emulator CI evidence:** <both platform run IDs, flow counts and validated image artifact IDs>
- **TestFlight physical installation evidence:** <approved internal group, consenting device install and build evidence ID>
- **Android internal physical installation evidence:** <approved Play internal track, consenting device install and build evidence ID>
- **Evidence configuration compatibility reference:** <reviewed comparison of build, pilot and production config/capability manifests>
- **Blocking review findings status:** <CLEAR only after independent review and disposition>
- **Blocking review findings evidence:** <accepted review/closed-finding and exact-retest evidence ID>
- **Pilot limits approval evidence:** <founder-approved market, spend, exposure, quality and stop-threshold record ID>
- **Store privacy and payment disclosure evidence:** <reviewed Apple/Google disclosures and terms evidence ID>
- **Incident owner:** <named on-call owner and route>
- **Rollback owner:** <named operator and tested rollback evidence ID>

## Released channels

Declare all three. `ENABLED` requires the corresponding provider, rate,
identity, eligibility and live evidence. `DISABLED` requires a negative test
showing the route cannot be authorized. The last column must be `PASS` for
either enabled eligibility or disabled denial. No channel is enabled by default.

| Channel | Status | Decision evidence | Eligibility/denial result |
|---|---|---|---|
| Carrier eSIM | <ENABLED or DISABLED> | <evidence ID> | <PASS> |
| Mobile internet | <ENABLED or DISABLED> | <evidence ID> | <PASS> |
| Browser internet | <ENABLED or DISABLED> | <evidence ID> | <PASS> |

## Device matrix tested

Use physical supported devices, not an emulator. Include the visited network
and an immutable test report. Additional rows may be described outside this
table; these two are mandatory for this combined mobile release gate.

| Platform | Model | OS version | Visited network | Evidence |
|---|---|---|---|---|
| Android | <model> | <version> | <network> | <evidence ID> |
| iOS | <model> | <version> | <network> | <evidence ID> |

## Critical scenario results

Every common row must be `PASS`. A released channel's rows must be `PASS`;
disabled-channel rows must say `NOT_APPLICABLE`. Any explicit `FAIL` blocks
promotion, even on an otherwise optional row. Link each passing row to an
immutable result against the tested commit and configuration using the
`sha256:<64 lowercase hex characters>` form above.

| Scenario | Result | Evidence |
|---|---|---|
| Identity and recovery | <PASS> | <evidence ID> |
| Purchase, payment and refund | <PASS> | <evidence ID> |
| Enterprise isolation and offboarding | <PASS> | <evidence ID> |
| Supplier timeout, replay and recovery | <PASS> | <evidence ID> |
| Migration and rollback | <PASS> | <evidence ID> |
| Support and incident escalation | <PASS> | <evidence ID> |
| Signed Android and iOS installation | <PASS> | <evidence ID> |
| Store privacy and payment disclosures | <PASS> | <evidence ID> |
| Production mock-mode rejection | <PASS> | <evidence ID> |
| Carrier eSIM install and data | <PASS or NOT_APPLICABLE> | <evidence ID if enabled> |
| Native call to Nigeria with app closed | <PASS or NOT_APPLICABLE> | <evidence ID if enabled> |
| Carrier usage, top-up and limit | <PASS or NOT_APPLICABLE> | <evidence ID if enabled> |
| Mobile outbound call, identity and DTMF | <PASS or NOT_APPLICABLE> | <evidence ID if enabled> |
| Mobile interruption, logout and cutoff | <PASS or NOT_APPLICABLE> | <evidence ID if enabled> |
| Browser outbound call, identity and DTMF | <PASS or NOT_APPLICABLE> | <evidence ID if enabled> |
| Browser refresh, logout and cutoff | <PASS or NOT_APPLICABLE> | <evidence ID if enabled> |

Store submission and production promotion remain separate authorized actions.
This template is not a launch approval, and it must not be filled with fixture
or sandbox evidence in place of a carrier, merchant or physical test.
The EAS and native-CI source SHAs must equal the tested commit. The release
owner must verify that each referenced build/install and physical pilot record
uses compatible configuration and capabilities; the validator checks the
signed reference and SHA fields, not remote artifact contents. A simulator,
emulator, cloud build or generic lab never substitutes for real eSIM install,
Wi-Fi-off cellular data and native-call proof when carrier service is enabled.
Before promotion, an administrator must install the trusted
`pull_request_target` workflow on `main`, require its
`release-signoff/trusted` status, and require a merge queue that revalidates
the merge-group SHA against current staging and UTC time just before merge.
The `release-signoff/trusted` context must be pinned to a dedicated release
GitHub App as its expected source, not the GitHub Actions App. Its status-only
private key and the release-owner public key must live in a protected
`release-signoff` environment restricted to protected `main`/`develop` refs,
with required release-owner approval and no self-approval. Ordinary PR jobs
must not be able to read those values. Strict up-to-date checks and
restrictions on the trusted workflow, environment and branch rules are also
required. Staging must be frozen during the queued
promotion; a status cannot monitor a changing external branch continuously.
The existing legacy status check is not a substitute. Until that bootstrap and D1–D6 approval,
promotion remains blocked even if local validator tests pass.
