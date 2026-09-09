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
| [API-CONTRACTS.md](API-CONTRACTS.md) | The documented parked-call route, server-originated fallback and the controls each still needs |
| [COST-MODEL.md](COST-MODEL.md) | Symbolic all-component worksheet; exact fee/CDR counts and Nigeria rates remain unknown |
| [LEGACY-REUSE.md](LEGACY-REUSE.md) | Every retained and 04D-removed voice component judged reuse / refactor / reject, with paths |
| [GO-NO-GO.md](GO-NO-GO.md) | **GO for provider-neutral V02 preparation, NO-GO for live calling.** Five blockers, an interface proposal and negative tests |
| [ENQUIRY-DRAFT.md](ENQUIRY-DRAFT.md) | **UNSENT** supplier enquiry, each question tied to a blocker |

## The findings that shape the route

A Telnyx WebRTC credential or JWT authenticates an endpoint; no per-destination
token scope is documented. Telnyx does document **Park Outbound Calls**, where
an ordinary client-originated call waits for backend instructions before a PSTN
leg is created. Emergency calls bypass that parking gate. V01 therefore selects
the parked route for preparatory work while keeping live calling disabled until
credential containment, bounded stopping and actual billing are proven. See
[API-CONTRACTS.md](API-CONTRACTS.md).

## Separate from the carrier track

[`../telnyx/`](../telnyx/) holds chunk 03's **carrier/eSIM** evidence and is not
modified by this chunk. WebRTC documentation is not evidence of carrier
coverage, and nothing here changes D1's carrier position.
