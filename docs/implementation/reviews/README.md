# Codex review records

One file per chunk, named `NN.md`, written by Codex after an independent review
using [`../REVIEW.md`](../REVIEW.md).

A review record must name the exact head SHA that was reviewed and tested, the
findings with severity and evidence, the fixes and refactors actually made, the
checks actually run, the external gates still open, and one of
**ACCEPTED**, **CHANGES_REQUIRED** or **EXTERNAL_BLOCKED**.

Changing code after the recorded SHA invalidates the affected evidence. A review
record carries forward only while the relevant code and configuration are
unchanged.

Only a review record may set a chunk to ACCEPTED in
[`../STATUS.md`](../STATUS.md). Claude never marks its own work accepted.

_No review has been recorded yet._
