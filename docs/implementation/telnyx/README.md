# Telnyx carrier feasibility — chunk 03 evidence

Produced by [chunk 03](../chunks/03-telnyx-feasibility.md) (US-35) on
**8 September 2026**, against gates **D1** and **D2**, both of which remain
**OPEN**.

Everything in this directory is a **documentation review**. No Telnyx account
exists, no API call was made, no message was sent, no order was placed and no
device was tested.

| File | What it is |
|---|---|
| [CAPABILITY-MATRIX.md](CAPABILITY-MATRIX.md) | Dated matrix separating eSIM data, native VoLTE, assigned number, messaging, device support and roaming — each tagged DOCUMENTED / ABSENT / SIMULATED / OBSERVED |
| [API-CONTRACTS.md](API-CONTRACTS.md) | Transcribed request/response shapes, statuses and error codes, plus the idempotency and lookup analysis for finding 4 |
| [GO-NO-GO.md](GO-NO-GO.md) | Per-market decision. **Every proposed market is NO-GO for now**, with the conditions that would change that |
| [ENQUIRY-DRAFT.md](ENQUIRY-DRAFT.md) | **UNSENT** supplier enquiry covering production/resale access, same-eSIM voice and data, Nigeria call costs and spending controls |

The executable harness is at
[`../../../apps/api/tools/telnyx_probe/`](../../../apps/api/tools/telnyx_probe/),
with tests in `apps/api/tests/test_telnyx_contract_probe.py`.

## How to read the evidence classes

| Class | Meaning |
|---|---|
| **DOCUMENTED** | Quoted from a current official Telnyx page, linked and dated |
| **ABSENT** | Not found after searching — an open question, never a "no" |
| **SIMULATED** | Reproduced from published schemas in our fixtures; proves our parsing only |
| **OBSERVED** | From a real API call or device. **This class is empty.** |

A green harness run is not supplier evidence. Coverage, pricing, VoLTE
production terms and handset behaviour can only come from Telnyx and from
chunk 29's physical proof.
