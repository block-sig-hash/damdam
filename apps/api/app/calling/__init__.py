"""Outbound internet calling — authorization, lifecycle and provider boundary.

Separate from `app/voice/`, which holds the retired app-calling feature and the
historical `call_logs` rows that chunk 04 deliberately kept. `LEGACY-REUSE.md`
classifies that module component by component: five primitives are reused, eight
are refactored before use and seven are rejected outright. Rebuilding here
rather than editing there is what keeps the rejected seven from coming back by
accident — a copied credential model, package-minute billing and the
verified-CLI eligibility path are all one careless import away in a shared
module, and none of them survives contact with this chunk's threat model.
"""
