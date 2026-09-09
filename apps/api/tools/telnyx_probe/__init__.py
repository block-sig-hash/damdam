"""Non-production Telnyx contract/probe harness (chunk 03, US-35).

This package is NOT part of the running application. It is deliberately outside
`app/` so it cannot be imported by a route, a worker or a service, and so it is
excluded from the application coverage target.

It exists to encode the *documented* Telnyx Wireless contracts and to let us
exercise our request construction, response parsing and reconciliation
decisions against scrubbed fixtures — before any supplier access exists.

See `README.md`, and `docs/implementation/telnyx/API-CONTRACTS.md` for the
sources every shape here is copied from.
"""
