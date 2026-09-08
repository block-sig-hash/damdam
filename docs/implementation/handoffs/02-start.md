# Start chunk 02 — Claude Code prompt

Use the local checkout and accepted branch below. The review fixes are in
`36e9bf36a2827d108633730ff0899edbd17b97ef`; the accepted branch tip additionally
contains the independent review/status record and this prompt.

```text
Implement DamDam chunk 02 only (US-42).

Repository: /tmp/damdam-review-20260907
Accepted predecessor branch: chunk/01-scope-and-specifications
Required reviewed content: 36e9bf36a2827d108633730ff0899edbd17b97ef

Inspect the working tree and read AGENTS.md, docs/README.md,
docs/implementation/reviews/01.md, STATUS.md, BASELINE.md, and
docs/implementation/chunks/02-ci-baseline.md before editing.

Start a new branch chunk/02-ci-baseline from the current accepted
predecessor branch tip, including its review-record commit.
Do not start from origin/develop or Claude's old 3e99cef handoff head.
Preserve unrelated work and record the actual base SHA.

Complete the chunk's full scope:
1. Reproduce the auth API failure and fix the inconsistent test clock.
   Test valid/expired tokens and boundaries without weakening production
   JWT expiry or changing production behavior merely to satisfy the test.
2. Diagnose the intermittent iOS capture failure. CI already checks for
   exactly 32 PNGs; September 8 produced 32 PNGs plus one XML report.
   Strengthen validation to the exact expected screen/locale matrix and
   nonempty valid images. Test empty output, a missing image replaced by
   an unrelated PNG at the same count, and empty/corrupt expected images.
   Cover both platform matrices; keep the existing screen scope until
   the redesign chunks update it.
3. Wire documentation-link validation into docs-triggered CI. Make the
   automated Claude review supplemental to independent Codex acceptance.
   Preserve required check names and existing release-promotion behavior.
4. Run the applicable required API, mobile, dashboard, contract and build
   checks. Report unavailable macOS/signing/CI access as evidence gaps;
   do not fabricate native results or lower thresholds/disable checks.

Scheduled CI intentionally cannot deploy staging: deployment is push-only.
Do not change that policy as a fix for skipped scheduled deployments.
Do not implement chunk 27's release validator or begin another chunk.

Return and commit the HANDOFF-TEMPLATE.md report as
docs/implementation/handoffs/02.md, with exact base/content/head SHAs,
test commands/results, CI evidence, changed files and remaining gaps.
Set READY_FOR_REVIEW only for completed scope; Codex reviews before
acceptance. Keep work local: no push, merge, deployment, store submission,
outgoing messages or live purchases unless separately authorized.
Preserve a fresh local bundle outside /tmp for the completed branch.
```
