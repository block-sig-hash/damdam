# Release Signoff

Copy this file to `<full-40-character-commit-sha>.md` in this same
directory, fill it in, and commit it as part of the commit set you're
promoting from `staging` into `main`. `scripts/validate-release-signoff.sh`
(run automatically by `.github/workflows/release-promotion.yml` on any
PR targeting `main`) parses this exact structure — see that script's
header comment before renaming headings or field labels here.

- **Commit SHA:** <full 40-character commit SHA being promoted — must
  match this file's own filename exactly>
- **Tester name:** <name>
- **Date:** <YYYY-MM-DD>

## Device matrix tested

Map against the real-device matrix in `docs/pre-pilot-checklist.md`
§6 — use the actual model tested, not a substitute or an
emulator/simulator.

| Platform | Device | OS version |
|---|---|---|
| Android | <device model> | <OS version> |
| iOS | <device model> | <OS version> |

## Critical scenario results

Every row below is required, each with a PASS or FAIL result — not a
subset. Add extra rows for anything else tested, but don't remove or
rename these.

| Scenario | Result (PASS/FAIL) | Notes |
|---|---|---|
<!-- US-30 (chunk 04E) removed every scenario this table used to list:
     incoming-call wake, CallKit lock-screen UI, PushKit delivery, offline
     check-in survival and offline SOS survival all tested features chunk 04
     retired. Chunk 27 re-cuts the release gates and fills this table in;
     chunk 29's physical-device pilot produces the evidence. Never re-add a
     retired scenario to make the gate pass. -->

## HTO usability test signoff

Either write the signoff directly here, or link to a separate linked
artifact that covers it (e.g. `docs/pre-pilot-checklist.md` §7's
usability observation, once it has a real writeup).

<!--
Photo/video evidence of device testing is NOT required yet. It
becomes mandatory the first time someone other than the founder is
authorized to promote to `main`, OR 3 months before the Hajj 2027
pilot launch — whichever comes first. When that trigger hits, add a
required `evidence_links` field to this template and update
scripts/validate-release-signoff.sh to enforce it.
-->
