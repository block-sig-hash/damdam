# Telnyx contract/probe harness — non-production

Built by [chunk 03](../../../../docs/implementation/chunks/03-telnyx-feasibility.md)
(US-35). **This is not part of the running application.**

It lives outside `app/` on purpose: nothing in a route, worker or service can
import it, and it is excluded from the application coverage target. It exists so
that the Telnyx contracts we will eventually build against are written down,
executable and reviewable **before** any supplier access exists.

## What it is evidence of

| Class | This harness |
|---|---|
| **DOCUMENTED** | Every field, enum and error code in `contracts.py` is transcribed from official Telnyx documentation fetched 2026-09-08 and cited in [`API-CONTRACTS.md`](../../../../docs/implementation/telnyx/API-CONTRACTS.md) |
| **SIMULATED** | Everything the fixture mode does. Fixtures are shape-only reconstructions from published schemas, each labelled `"_fixture": "SIMULATED"` |
| **OBSERVED** | Nothing yet. Live mode exists but has never been run — there is no Telnyx account |

**A passing run proves our parsing and our reconciliation decisions are
self-consistent. It proves nothing about Telnyx coverage, pricing, VoLTE
production readiness or device behaviour.** D1 stays OPEN.

## Usage

```bash
cd apps/api
python -m tools.telnyx_probe.probe --mode fixtures
```

Live mode is read-only and hard-gated. It requires `TELNYX_API_KEY` in the
environment **and** `--i-have-authorization`, and refuses without both:

```bash
python -m tools.telnyx_probe.probe --mode live --i-have-authorization --tag damdam-op-<uuid>
```

There is deliberately **no code path in this package that can POST to
`/actions/purchase/esims`**, enable, disable or delete a SIM. Live mode performs
one `GET /sim_cards` and nothing else. Adding a write path is a separate change
that needs its own review and an explicit spending decision.

## Files

| File | Purpose |
|---|---|
| `contracts.py` | Transcribed request/response shapes, SIM statuses, documented error codes |
| `reconcile.py` | The finding-4 decision: what an unknown purchase outcome permits next |
| `probe.py` | CLI — offline fixture mode, hard-gated read-only live mode |
| `fixtures/*.json` | Scrubbed, `SIMULATED`-labelled shape reconstructions |

Tests: `apps/api/tests/test_telnyx_contract_probe.py`, which run in normal CI.

## Deliberate omissions

- **No idempotency key**, because Telnyx does not document one. Inventing a
  plausible field is exactly the failure this harness exists to prevent.
- **No coverage, market or price data.** None is published; none is guessed.
- **No voice request/response schemas.** The VoLTE overview says its API
  reference is "coming soon"; the action endpoints are named but their bodies
  are not published, so they are not modelled here.
- **No credentials, ICCIDs, EIDs, MSISDNs or activation codes**, in code,
  fixtures or output. Live mode truncates ICCIDs and withholds error bodies.

## The one thing to read before relying on this

`reconcile.py`'s `lookup_is_trusted` parameter. Telnyx does not document whether
a just-purchased eSIM is immediately visible to `filter[tags]`. If it is not, an
empty lookup is indistinguishable from "the purchase never landed" — and acting
on that would double-purchase, which is precisely the defect finding 4
describes. Until that is proven live, callers must pass `False`, and an empty
result escalates to manual reconciliation instead of retrying.
