# Chunk 27 release preparation — signing, permissions and disclosures

Recorded 23 September 2026 against `develop` merge `247974b`. This is a
repository inventory and an operator procedure, **not** a signed build, store
submission, legal approval or production release. Do not put keystores,
passwords, activation material, customer data or API keys in this directory.

## Build separation and reproducible commands

Android `release` now uses an externally supplied keystore and fails before
building when any `DAMDAM_RELEASE_*` value is missing, the file does not exist,
or the configured certificate matches the checked-in debug certificate even
from a copied keystore path. The independent
`screenshot` build type bundles fixture UI and uses the debug key; it is not
the artifact to publish. It requires `SCREENSHOT_HARNESS_MODE=true`, while a
production release rejects that setting. CI installs
`android/app/build/outputs/apk/screenshot/app-screenshot.apk` for Maestro.

With an authorized signing environment (D6), from `apps/mobile/android`:

```bash
# Supply these through the approved secret manager, not a checked-in file:
# DAMDAM_RELEASE_KEYSTORE_PATH, DAMDAM_RELEASE_STORE_PASSWORD,
# DAMDAM_RELEASE_KEY_ALIAS, DAMDAM_RELEASE_KEY_PASSWORD,
# DAMDAM_RELEASE_CERT_SHA256 (release-owner-approved certificate fingerprint).
./gradlew clean bundleRelease --no-daemon
```

Record the full source SHA, Gradle/Java/Android SDK versions, AAB SHA-256,
signing-certificate SHA-256 and the matching app version. Verify the certificate
against the release owner's approved fingerprint before distributing the AAB.
No key or fingerprint is approved in this repository yet. `assembleRelease`
and `bundleRelease` without the signing environment must fail, not fall back to
the debug key. An emulator screenshot build is not a signed-store build.

## Remaining distribution and device work — user addition, 23 September 2026

- **EAS cloud builds (D6; chunks 27/30):** configure the existing bare React
  Native app's EAS project, profiles and credentials under approved accounts;
  verify iOS and Android cloud builds against the exact source/configuration,
  including the approved distribution certificate, provisioning profile,
  Android upload certificate and resulting artifact hashes. The current
  on-demand EAS workflow is only a probe and no signed cloud result is claimed.
  Never put signing material in the repository or treat an EAS build as a store
  submission.
- **Automated native CI (chunk 27):** run the Android emulator and iOS
  simulator screenshot/journey checks on the candidate, retain validated image
  artifacts and record any runner/driver failure. The Android PR job is
  automatic; iOS is nightly/on-demand. A skipped or timed-out iOS job is not
  passing evidence.
- **Internal distribution (chunk 29):** after signing and approvals, arrange
  TestFlight and an approved Android internal-testing track with named,
  consenting testers who possess supported physical devices. Record build
  versions, invitations, install results, device/OS/network and findings;
  do not invite people or upload builds without the release owner's authority.
- **Hard physical release gate (chunks 29/30):** real eSIM provisioning and
  installation, cellular-data use, and carrier native calling (including a
  Nigeria call with DamDam closed where offered) require the approved carrier,
  market, spend and device evidence. EAS builds, simulator/emulator CI and
  generic device labs cannot substitute for live carrier/merchant proof.

iOS Release references `DamDamRelease.entitlements`, which requests production
APNs and the same associated domains as Debug. Its React Native bundle phase
calls `release-bundle-guard.sh` **after** `.xcode.env` and `.xcode.env.local`
are sourced and refuses `SCREENSHOT_HARNESS_MODE=true` for Release, preventing
late environment overrides from putting fixture UI in
a production archive. A Linux regression executes that guard, but only a macOS
archive verifies the entire iOS build. The iOS screenshot CI path is a
non-distribution Debug simulator build with a forced embedded JS bundle; it
cannot be repurposed as a signed Release artifact. It needs an Apple developer
team, an approved distribution certificate/profile, a macOS/Xcode environment
and verified AASA domains; none is configured here (D6). The repeatable
archive command once those inputs exist is:

```bash
cd apps/mobile/ios
xcodebuild archive -workspace DamDam.xcworkspace -scheme DamDam \
  -configuration Release -destination 'generic/platform=iOS' \
  -archivePath build/DamDam.xcarchive
```

Record Xcode version, source SHA, profile/team and entitlements, archive and
exported IPA SHA-256, certificate fingerprint and install result. The
on-demand EAS workflow is a separate optional build probe, not proof that an
IPA was signed with an approved production identity; its historic comments
about removed incoming-call bridges are obsolete. No iOS archive was run on
this Linux host.

## Actual native declarations and SDK inventory

| Surface | Repository declaration or use | Release implication |
|---|---|---|
| Android permissions | `INTERNET`, `ACCESS_NETWORK_STATE`, `POST_NOTIFICATIONS`, `WRITE_EMBEDDED_SUBSCRIPTIONS` | Verify merged release manifest and Play Data safety; device eSIM write capability is not proven by a manifest declaration |
| iOS permissions/entitlements | No microphone, location, camera or contacts usage key in `Info.plist`; APNs and associated domains entitlements | Verify exported IPA entitlements and APNs/AASA service configuration. Removed Hajj location strings are no longer bundled as permission copy |
| Outbound internet audio | V04's adapter is unavailable; `RECORD_AUDIO` and `NSMicrophoneUsageDescription` are absent | Do not enable mobile internet calling. Add only the SDK-required permission and bilingual purpose copy after real integration and review |
| Notifications | Android Firebase Messaging service and notification permission; iOS APNs entitlement | Push token/device registration and notification categories need store disclosure and live transport/config proof; no incoming-call push bridge is restored |
| Monitoring | Optional PostHog React Native provider; absent project key disables it; AsyncStorage is its custom storage | If enabled, inventory SDK-emitted crash/event identifiers and destinations from the signed binary and update Apple/Google declarations accordingly |
| Local state | AsyncStorage account/line/cache slices, Keychain PIN/session material, per-installation device identifier | Validate account-scoped erasure and secure storage on physical devices; do not describe these as server-side-only data |
| Checkout | Hosted processor page in WebView; conditional Paystack/local NGN routing and no approved global processor | Do not claim native wallet checkout or a live merchant. Obtain store-policy review and D3/D4/D5 decisions before submission |
| Browser calling | V05 browser adapter unavailable; browser microphone is not used for a live call | Browser privacy notice and supported-browser microphone evidence remain pending with SDK/provider integration |

The checked-in `PrivacyInfo.xcprivacy` lists SDK required-reason API categories
and no collected data. That file alone is **not** a complete Apple App Privacy
answer for account, financial, usage, support, device or optional analytics
data. The full app and SDK behavior, including third-party privacy manifests,
must be inspected in the actual signed binary. No label is submitted here.

## Store/privacy/terms draft for counsel and release owner

The current product stores account identifiers and recovery addresses,
membership/organization relationships, order and receipt records, entitlement
and eSIM installation state, provider-derived usage/charges, support requests,
device/session metadata and masked operational logs. It may send push tokens and
optional crash/analytics telemetry. It does not currently request device
location, contacts, camera or microphone. Hosted payment providers handle card
entry; DamDam retains payment references and financial ledger records, not full
card numbers. Cross-border destinations, processors and data retention must be
checked against `security.md` and the signed build before any store form or
consumer terms are finalized.

Unresolved: D1 supplier/route approval, D2 saleable markets/devices, D3 legal
seller and taxes, D4 merchant accounts and store payment treatment, D5 prices,
refund/funding economics and limits, D6 signing, domains, support and physical
devices. Emergency calling and callback limitations require per-mode/market
legal and product review. English/French legal copy and native-speaker review
are not complete. This inventory is a disclosure worklist, not legal advice.

## Screenshot, localization and accessibility evidence

The mobile manifest derives its exact English/French images from Maestro
flows. Chunk 27 adds Home, Account and Receipts, including a nonempty receipt,
on both platforms. Calls setup/active/history are fixture-only captures and
cannot certify live media. Android runs on each affected PR; iOS runs nightly
or on demand. The final mobile images must be visually inspected on the exact
candidate, including clipped French text and activation-secret handling.

The dashboard gallery checks English/French, widths 320/768/1280 and 200%
text, but it is **not** an enterprise journey capture. Actual people/import,
bulk, lines, billing/budgets, offboarding and internal-operations screenshots
remain owed by the browser matrix. Neither a component gallery nor automation
substitutes for VoiceOver/TalkBack, physical installation, keyboard/focus,
screen-reader and large-text review. These remain release gates.

## Promotion evidence and authorization boundary

`docs/release-signoffs/TEMPLATE.md` and
`scripts/validate-release-signoff.sh` now bind a signoff to the current
`staging` commit and
reject tracked changes after it. They require configuration fingerprint,
accepted dependency SHAs, exact channel scope, markets, carrier/merchant
references, physical devices, signed artifacts, scenario PASS evidence and
incident/rollback owners. Disabled channels need negative eligibility proof.
The PR must add a matching Ed25519 signature sidecar over the exact signoff
bytes. The trusted base-branch workflow verifies it against a public key
provisioned outside the PR. The release owner must verify every external
reference before signing; a valid signature is an accountable attestation, not
proof that the provider or device actually worked. The configuration fingerprint
is a signed reference to a redacted
deployment snapshot, not a CI attestation of remote secret state; the release
owner must compare it again before promotion. Store submission and production
promotion are separate authorized actions. Automatic main-push EAS builds and
submissions have been removed. No historical tag is moved.

On 23 September 2026, the GitHub API returned `main` branch protection with
`Validate release signoff artifact` required, admin enforcement enabled,
`strict=false`, no required PR reviews and no repository rulesets. The old
workflow runs PR-head code and is not an adequate trust boundary. D6 therefore
also requires an administrator to install the new base-branch workflow on
`main`, require its `release-signoff/trusted` status on the PR head, enable
strict up-to-date checks and a required merge queue, and restrict
public-key/workflow/branch-rule administration. The status must be pinned to
the dedicated release GitHub App as its expected source: a normal
`GITHUB_TOKEN` status is forgeable by another same-repository workflow. Store
the App's status-only private key, ID and release-owner public key in a
protected `release-signoff` environment restricted to protected `main` and
`develop`, with required release-owner review and self-approval disabled.
Neither that App nor the environment exists yet, so no trusted status can be
posted. A default-branch trusted
`workflow_run` consumer revalidates the merge-group SHA when the queue forms,
so an old green PR-head status cannot mask staging drift or signoff expiry.
The release owner must freeze staging while the promotion is queued and verify
its SHA again at merge; no status can continuously track external state.
The new workflow will fail closed until the public key is provisioned. These
are **not** performed or approved by this implementation. Recheck the server
settings and current staging SHA immediately before any promotion.
