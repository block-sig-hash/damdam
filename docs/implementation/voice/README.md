# Internet-calling feasibility — chunk V01 evidence

Produced by [chunk V01](../chunks/V01-internet-voice-feasibility.md) (US-44) on
**9 September 2026**, against the **internet** track of gate **D1**, which
remains **OPEN**.

Everything in this directory is a **documentation review**. No Telnyx account
exists, no API call was made, no SDK was installed, no message was sent and no
call was placed.

| File | What it is |
|---|---|
| [CAPABILITY-MATRIX.md](CAPABILITY-MATRIX.md) | Dated matrix separating internet from carrier capability, each tagged DOCUMENTED / ACCOUNT-CONFIRMED / PHYSICALLY-TESTED / UNSUPPORTED / UNKNOWN |
| [API-CONTRACTS.md](API-CONTRACTS.md) | The chosen route topology and why, plus commands, events, signature validation, idempotency limits and termination bounds |
| [COST-MODEL.md](COST-MODEL.md) | All-leg worksheet. Two legs are evidenced; **Nigeria rates are not** and stay symbolic |
| [LEGACY-REUSE.md](LEGACY-REUSE.md) | Every retained and 04D-removed voice component judged reuse / refactor / reject, with paths |
| [GO-NO-GO.md](GO-NO-GO.md) | **GO for V02 documented work, NO-GO for live calling.** Five blockers, a V02 interface proposal and a 15-row negative test matrix |
| [ENQUIRY-DRAFT.md](ENQUIRY-DRAFT.md) | **UNSENT** supplier enquiry, each question tied to a blocker |

## The one finding that shapes everything else

A Telnyx WebRTC credential or JWT authenticates an **endpoint**. No
per-destination scope on the token is documented. So the client must never be
the party that chooses the destination — the backend originates both legs and
bridges them. See [API-CONTRACTS.md §2](API-CONTRACTS.md).

## Separate from the carrier track

[`../telnyx/`](../telnyx/) holds chunk 03's **carrier/eSIM** evidence and is not
modified by this chunk. WebRTC documentation is not evidence of carrier
coverage, and nothing here changes D1's carrier position.
