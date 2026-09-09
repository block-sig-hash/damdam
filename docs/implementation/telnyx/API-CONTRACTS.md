# Telnyx API contracts — documented shapes, idempotency and lookup

Produced by [chunk 03](../chunks/03-telnyx-feasibility.md) (US-35). Sources
fetched **8 September 2026**. Every endpoint and field below is copied from
official documentation and linked. **Nothing here was called.** No endpoint,
field or status value has been invented; where the documentation is silent this
file says so.

Base URL: `https://api.telnyx.com/v2`. Auth: `bearerAuth` (API key).

## 1. Endpoints relevant to the reset product

### 1.1 eSIM purchase — the provisioning entry point

`POST /actions/purchase/esims` — [reference](https://developers.telnyx.com/api-reference/sim-cards/purchase-esims.md)

Request (`ESimPurchase`), verbatim from the published OpenAPI:

| Field | Type | Required | Notes |
|---|---|---|---|
| `amount` | integer, min 1 | **yes** | "The amount of eSIMs to be purchased." |
| `sim_card_group_id` | uuid | no | Defaults to the account's default group |
| `tags` | string[] | no | "Searchable tags associated with the SIM cards" |
| `product` | string | no | `"whitelabel"` to use a custom SPN |
| `whitelabel_name` | string | no | SPN "displayed as the mobile service name by operating systems of smartphones"; letters, numbers and whitespace only |
| `status` | enum `enabled`\|`disabled`\|`standby` | no, default `enabled` | Status the SIMs are left in |

Response **`202`**: `{ data: SimpleSIMCard[], errors: Error[] }`.

Note carefully what this contract is **not**:

- **It has no idempotency key.** There is no `Idempotency-Key` header, no
  `idempotency_key` body field, and no client-supplied operation id.
- **It is quantity-based, not item-based.** You ask for *N* eSIMs; you cannot
  name them, and there is no per-item client reference on the request.
- **It can partially succeed.** The 202 body carries both `data` and `errors`,
  so a request for 10 may yield fewer than 10 plus errors.

### 1.2 SIM card lookup — the reconciliation path

`GET /sim_cards` — [reference](https://developers.telnyx.com/api-reference/sim-cards/get-all-sim-cards.md)

Documented filters (deepObject `filter[...]`):

| Filter | Notes |
|---|---|
| `filter[iccid]` | "A search string to partially match for the SIM card's ICCID" |
| `filter[msisdn]` | Match the SIM's MSISDN |
| `filter[status]` | Array of `enabled`, `disabled`, `standby`, `data_limit_exceeded`, `unauthorized_imei` |
| `filter[tags]` | "If the SIM card contains **all** of the given `tags` they will be found" |
| `filter[sim_card_group_id]` | uuid |
| `include_sim_card_group` | boolean |
| `sort` | `current_billing_period_consumed_data.amount` or its `-` inverse |

`SimpleSIMCard` fields: `id`, `record_type`, `status`, `type` (`physical`\|`esim`),
`iccid`, `imsi`, `msisdn`, `sim_card_group_id`, `tags`, `data_limit`,
`current_billing_period_consumed_data`, `actions_in_progress`,
`esim_installation_status`, `eid`, `authorized_imeis`, `voice_enabled`,
`version`, `resources_with_in_progress_actions`, `created_at`, `updated_at`.

### 1.3 Lifecycle actions — all asynchronous

| Action | Endpoint |
|---|---|
| Enable | `POST /sim_cards/{id}/actions/enable` |
| Disable | `POST /sim_cards/{id}/actions/disable` |
| Standby | `POST /sim_cards/{id}/actions/set_standby` |
| Delete | `DELETE /sim_cards/{id}` (irreversible; `report_lost=true` for uninstallable eSIMs, also irreversible) |
| Register physical | `POST /actions/register/sim_cards` |

> "All state changes return `202` with a SIM Card Action — they are not instant.
> Poll the action status or list actions to confirm completion."
> — [sim-lifecycle](https://developers.telnyx.com/docs/iot-sim/sim-lifecycle.md)

Statuses: user-controlled `enabled` / `disabled` / `standby`; transitional
`registering`, `enabling`, `disabling`, `setting_standby`; system-imposed
`data_limit_exceeded`, `unauthorized_imei`, `blocked`, `abolished`.

A SIM **must** have a `sim_card_group_id` before it can be enabled or set to
standby (error `70007`).

### 1.4 Action tracking

| Purpose | Endpoint |
|---|---|
| List SIM card actions | `GET /sim_card_actions` |
| Get one action | `GET /sim_card_actions/{id}` |
| List bulk actions | `GET /bulk_sim_card_actions` |
| Get bulk action | `GET /bulk_sim_card_actions/{id}` |

Bulk actions carry per-SIM results — "some may succeed while others fail".

### 1.5 Voice (beta)

| Action | Endpoint |
|---|---|
| Enable voice on a SIM | `POST /sim_cards/{id}/actions/enable_voice` (optional `connection_id`) |
| Disable voice | `POST /sim_cards/{id}/actions/disable_voice` |
| Bulk enable/disable voice | `POST /sim_cards/actions/bulk_enable_voice` / `bulk_disable_voice` (by SIM card group) |
| List/get/update assigned number | `GET|PATCH /mobile_phone_numbers[/{id}]` |
| Mobile voice connections | `GET|POST|PATCH|DELETE /mobile_voice_connections[/{id}]` |

Mobile phone number settings include `call_forwarding`, `call_recording`,
`caller_id_name_enabled`, `cnam_listing`, `noise_suppression`,
`inbound_call_screening`, `connection_id`, **`customer_reference`**, `tags`,
`inbound`, `outbound`.

Connection settings: `webhook_event_url`, `webhook_event_failover_url`,
`webhook_timeout_secs`, `inbound`, `outbound`, `active`.

**Caveat.** The VoLTE overview says "API reference and detailed configuration
docs coming soon" while these endpoints are already listed. Request and response
schemas for the voice actions were **not** found in the fetched OpenAPI export.
Treat the voice contract as **named but not fully specified**, and do not
implement against assumed field shapes.

### 1.6 Usage — data only

| Purpose | Endpoint |
|---|---|
| Start a detail-record report | `POST /wireless/detail/records/reports` |
| Poll the report | `GET /wireless/detail/records/reports/{id}` (download via `report_url` pre-signed URL) |
| Recent sessions for one SIM | `GET /sim_cards/{id}/wireless_connectivity_logs` |

Wireless Detail Records are **per data session**, with `sim_card_id`,
`start_time`/`stop_time`, `radio_access_technology`, `mobile_country_code`,
`mobile_network_code`, `apn`, `ipv4`/`ipv6`, `cell_id`.

**Not documented:** retention period, latency between usage and record
availability, whether records can be restated, and — critically — **any unique
record identifier suitable for deduplication.** `SimpleSIMCard.current_billing_period_consumed_data`
is a *cumulative* counter, not an event stream.

**No voice detail records / CDR endpoint for mobile voice was found.**

### 1.7 Documented error codes

[api-errors](https://developers.telnyx.com/docs/iot-sim/api-errors.md): `70000`
consumption reached data limit; **`70001` "There aren't enough available SIM
cards"**; `70002` invalid data format; `70003` operator preference priorities out
of sequence; `70004` OTA update in progress; `70005`/`70006` group deletion
constraints; `70007` SIM has no group; `70008` public IPs unavailable.

`70001` matters: **an eSIM purchase can fail for supplier inventory.** Any
provisioning flow must treat that as a real, retryable-later outcome distinct
from a client error, and must not present it to a paying customer as success.

## 2. Idempotency and lookup — the finding-4 analysis

Original finding 4 requires that an accepted-but-response-lost provisioning
attempt reconciles against the original supplier and never buys a second
profile. Assessed against the documented contract:

| Requirement | Documented support | Verdict |
|---|---|---|
| Client-supplied idempotency key on purchase | none | **NOT AVAILABLE** |
| Server-side dedup of identical purchases | not documented | **UNKNOWN** |
| Client reference echoed on created SIMs | `tags[]` (batch-level, free-form strings) | **PARTIAL** |
| Lookup by client reference | `GET /sim_cards?filter[tags][]=...`, matching SIMs carrying **all** given tags | **AVAILABLE** |
| Lookup by supplier identifier | `filter[iccid]`, `filter[msisdn]`, `GET /sim_cards/{id}` | **AVAILABLE** |
| Async operation tracking | SIM Card Actions and Bulk SIM Card Actions | **AVAILABLE for lifecycle actions** |
| Async tracking for the *purchase* itself | purchase returns `202` with the created SIMs inline, not an action id | **NOT AVAILABLE** |

### 2.1 The reconciliation pattern this supports

Because `tags` are client-supplied on purchase **and** filterable on lookup, a
unique per-attempt tag is a usable reconciliation key built entirely from
documented fields:

1. Persist an operation reference (our own uuid) **before** dispatch — this is
   already required by `prd.md` AC-32.4.
2. Purchase with `tags: ["damdam-op-<operation_reference>"]` (plus any
   `sim_card_group_id`, `product`/`whitelabel_name`, `status`).
3. On a lost response, timeout or crash, **do not retry the purchase.** Query
   `GET /sim_cards?filter[tags][]=damdam-op-<operation_reference>` and compare
   the count returned against the `amount` requested.
4. Classify: full count → accepted, adopt the SIMs; partial → partially
   accepted, reconcile the shortfall as its own decision, never as a blind
   retry. A zero result permits a retry with the **same** tag only after Telnyx
   has confirmed the lookup's post-purchase consistency and required settling
   window. Until then, zero is outcome-unknown and requires manual review.

### 2.2 Why this is reconciliation, not idempotency — state it plainly

- A retry sent **before** the lookup still double-purchases. The tag makes a
  duplicate *detectable*, not *impossible*. The safeguard must therefore live in
  our order state machine, not in the supplier call.
- **Tag search semantics and consistency are undocumented.** Whether a
  just-created SIM is immediately visible to a tag filter is unstated. A lookup
  racing provisioning could return zero for a purchase that did land — the worst
  possible answer, because it reads as "safe to retry".
  **This must be proven against the live API before chunk 15 relies on it, and
  until then the conservative branch is to stop for manual reconciliation.**
- Tags are free-form strings with no documented uniqueness constraint; nothing
  stops two operations sharing a tag by accident. Use a uuid, never a
  human-meaningful value.
- `filter[tags]` is `AND` across the supplied list, which is what we want, but a
  SIM may also carry unrelated tags.

### 2.3 Open contract questions for D1

1. Is any idempotency mechanism available on `POST /actions/purchase/esims`,
   even undocumented?
2. Are tags on newly purchased eSIMs immediately consistent for `filter[tags]`?
3. Is there a rate limit or quota on eSIM purchase, and what is the documented
   response?
4. What are the request/response schemas for the voice action endpoints?
5. Is there any voice CDR or usage endpoint at all?
6. Do Wireless Detail Records carry a stable unique id, and can they be restated?

## 3. What the harness does with this

`apps/api/tools/telnyx_probe/` encodes these shapes as typed contracts and
exercises them against **scrubbed fixtures derived from the documented schemas**.

It proves our request construction and response parsing match the published
contract. **It proves nothing about Telnyx's actual behaviour.** Every fixture
is labelled `SIMULATED`, and the probe refuses to run against a live endpoint
without explicit authorization flags. See
[`../../../apps/api/tools/telnyx_probe/README.md`](../../../apps/api/tools/telnyx_probe/README.md).
