# Claude implementation handoffs

One file per chunk, named `NN.md`, written by Claude at the end of a chunk using
[`../HANDOFF-TEMPLATE.md`](../HANDOFF-TEMPLATE.md).

A handoff is a **request for review, not an acceptance**. It records the exact
base and head SHA, working-tree status, changed behavior, acceptance evidence,
the checks actually run with their real results, migration notes, and every
unresolved gate and known limitation. Incomplete checks are recorded as
incomplete.

Handoffs are sanitized: no API keys, real activation codes, customer records or
private payment payloads.
