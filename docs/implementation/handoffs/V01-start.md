# Claude start prompt — V01 internet-voice feasibility

Copy the following into a new Claude Code session on this machine:

```text
Implement DamDam chunk V01 only — US-44.

Repository: /home/iadamu/dev/damdam
Approved planning checkout: /home/iadamu/dev/damdam-wt/voice-plan
Planning branch: docs/multichannel-voice-plan
Accepted application base: 7aeea652e6e12034463dc3c3a3f964975c220f63

Inspect branches and working trees first. The canonical checkout has separate
staging work; preserve it. Resolve the committed planning branch tip, verify it
contains VOICE-EXPANSION.md and V01's assignment, and create your own worktree
and chunk/V01-internet-voice-feasibility branch from that tip. Do not reset the
canonical checkout or start from develop without carrying this approved plan.
If the planning branch is already merged, use the latest accepted develop
containing the same amendment; record your exact base SHA. Do not absorb any
unreviewed application changes from other branches.

Read:
- AGENTS.md and docs/README.md
- docs/prd.md section 11
- docs/implementation/VOICE-EXPANSION.md
- docs/implementation/DECISIONS.md
- docs/implementation/reviews/03.md, 04.md and 05.md
- docs/implementation/chunks/V01-internet-voice-feasibility.md

The founder approved outbound mobile and browser calling alongside separately
verified carrier eSIM calling. Internet calling requires no eSIM. Incoming
app/browser ringing and third-party verified caller ID remain deferred.

Deliver only V01's documented evidence/contract, all-leg Nigeria cost worksheet,
legacy reuse inventory, go/no-go and unsent enquiry. Recheck official sources
and distinguish guarantees from account-specific unknowns. Prove on paper the
server/provider authorization route and termination-control requirements;
do not assume a reusable SDK credential can safely call arbitrary destinations.
Document blockers honestly. Do not restore voice code, install SDKs, modify
staging/CI, revert chunk04, send enquiries or make paid test calls.

Run docs link validation and git diff --check. Commit your scoped work and
return docs/implementation/handoffs/V01.md with exact base/content/head SHAs,
validation, evidence limitations and open questions. Set V01 READY_FOR_REVIEW
for delivered scope and identify any EXTERNAL_BLOCKED remainder. Do not mark
yourself accepted, merge or begin V02. Codex independently reviews/refactors.

V01 may run alongside chunk06 or staging in isolated worktrees. Do not edit
their files or require their incomplete work for this documentation assignment.
```
