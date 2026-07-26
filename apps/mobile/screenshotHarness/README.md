# Screenshot harness

Testing infrastructure only — see `docs/testing-qa.md`'s
"Amendment — Screenshot-Generation CI" for the full rationale. This
directory is never imported by production code; it's only reachable
when `index.js` sees `SCREENSHOT_HARNESS_MODE=true` inlined at build
time, which only CI's `screenshot-mobile-android`/`screenshot-mobile-ios`
jobs (`.github/workflows/ci.yml`) ever set.

## Why this exists

`apps/mobile` has no navigation library, no deep-linking, and no
dev flag to jump to an arbitrary screen — `App.tsx` drives a real
session-gated flow (`useSessionGate`) that requires a real backend
and a real onboarding journey to reach most screens. There's also no
mock-server layer (no MSW/nock) anywhere in the app. Rather than
build all of that just to take a screenshot, this harness mounts each
target screen directly with fixture props (the same approach the
screen's own Jest/RNTL tests already use) and, for the few screens
that fetch on mount, replaces `global.fetch` with a small canned-
response router (`fetchMock.ts`) instead of running a real backend.

## How it's structured

- `fixtures.ts` — canned data (pricing tiers, eSIM profile, call
  history, a fake `VoiceCallSession`, etc.)
- `fetchMock.ts` — installs a `global.fetch` override that answers
  the handful of endpoints target screens call on mount. Anything not
  explicitly routed gets a 404, so a screen missing a fixture fails
  loudly (visible error banner) instead of spinning forever.
- `registry.tsx` — the map of `target key -> { label, render() }`.
  **This is the one file you edit to add a new screenshot target.**
- `ScreenshotHarnessApp.tsx` — the harness's root component: a picker
screen listing every registered target (`testID="harness-target-<key>"`)
and explicit English/French locale controls, which renders the selected
screen in place once tapped.

## Adding a new screen

1. Add an entry to `HARNESS_REGISTRY` in `registry.tsx` with a
   `render()` that mounts the screen with fixture props. If the
   screen fetches on mount, add a matching route to `fetchMock.ts`.
2. Add a Maestro flow at `apps/mobile/maestro/screens/<key>.yaml`:
   ```yaml
   appId: com.damdam.app
   ---
   - launchApp
   - tapOn:
       id: "harness-locale-en"
   - assertVisible:
       id: "harness-locale-active-en"
   - tapOn:
       id: "harness-target-<key>"
   - assertVisible:
       id: "<some-testID-on-the-real-screen>"
   - takeScreenshot: <key>-en
   ```
   If the screen has no `testID` of its own, `assertVisible` can
   match visible text instead (see `sos-confirm.yaml` for an example).
   Every flow must then relaunch the harness, select
   `harness-locale-fr`, repeat the assertion, and capture
   `<key>-fr`. CI requires 32 non-empty images per platform (16
   platform-applicable targets × 2 locales).
3. If the screen renders differently per platform in a way worth
   capturing separately (like the eSIM activation flow), add
   `tags: [android-only]` / `tags: [ios-only]` to the flow file — see
   `esim-activation-android.yaml` / `esim-activation-ios.yaml`. Flows
   with no platform tag run in both CI jobs automatically.

No rebuild-per-screen is needed: one APK/IPA build serves every
registered target, since screen selection happens at runtime via the
picker, not at build time.

## What's explicitly out of scope

**The native CallKit (iOS) / ConnectionService (Android) incoming-call
UI itself is not capturable here, and isn't capturable by any CI
approach** — it's OS-level chrome rendered outside the app's own view
hierarchy, only reachable via a real VoIP push (Apple PushKit) or a
real FCM-triggered Headless JS task (`callKit.ts`), neither of which
can be triggered headlessly in CI without a live push/telecom event.
The `active-call` target instead captures `ActiveCallScreen` — the
in-app UI a pilgrim sees *after* answering — mounted directly with a
fixture `VoiceCallSession`. That's a real, useful screen to visually
review; it is not a substitute for seeing the native call UI, and
this harness makes no attempt to fake one.

The `esim-activation-prompt-android` / `esim-activation-guide-ios`
targets similarly bypass `EsimActivationFlow`'s real container (which
calls a native SIM-manager check via `services/esimActivation.ts`)
and mount its two presentational child screens directly — real device
eSIM-slot detection isn't something an emulator/simulator can
meaningfully answer either.
