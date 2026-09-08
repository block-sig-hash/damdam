# Module ownership

Opened by [chunk 01](chunks/01-scope-and-specifications.md) on 8 September 2026.

Two different things are called "ownership" in this repository, and chunk 01
separates them deliberately:

1. **Agent ownership** — who writes code and who reviews it. There is now one
   rule for the whole repository: **Claude implements, Codex independently
   reviews and may refactor.** It is stated in [`../../AGENTS.md`](../../AGENTS.md)
   and is not subdivided by area.
2. **Module ownership** — which specification defines a module's contract and
   which chunk is allowed to change it. That is what this file records.

The chunk's acceptance criteria define its scope; the table names primary
delivery responsibility, not exclusive file ownership. Necessary integration
changes are allowed across modules: for example, chunk 04 retires shared dispatch
and navigation paths, chunk 05 introduces cross-module schema, and chunk 09 owns
immutable quote behavior before order orchestration in chunk 11. Explain and
test those changes in the handoff. Split unrelated new features into a later
chunk instead of using integration work to widen the scope.

## Target module boundaries

The launch architecture is a **modular monolith**. Providers sit behind internal
interfaces and are never called from route handlers or UI components. There is
no microservice split and no runtime plugin marketplace.

| Module | Responsibility | Contract spec | First chunk to own it |
|---|---|---|---|
| Identity | Accounts, credentials, sessions, recovery methods — independent of any carrier number | `prd.md` §10, `api-spec.md`, `security.md` | 06 |
| Organizations | Memberships, invitations, roles, teams, cost centers, tenant scope enforcement | `prd.md` §10, `api-spec.md` | 07 |
| Catalog / Eligibility | Products, supported markets, networks, devices, supplier SKU mappings, voice origins and destinations, price and rate versions | `data-model.md`, `api-spec.md` | 09 |
| Commerce (Orders) | Immutable quotes, order items, payer, recipient, selling entity, tax treatment, order state machine, durable recovery | `data-model.md`, `api-spec.md` | 11 |
| Payments | Processor routing, payment attempts, webhooks, refunds, disputes, settlement reconciliation | `api-spec.md`, `security.md` | 12 |
| Ledger | Immutable balanced entries, currency-specific accounts, funding, reservations, consumption, releases, compensating adjustments | `data-model.md` | 10 |
| Connectivity | Device, eSIM profile, carrier line, assigned number, service entitlement, activation request — each a separate resource | `data-model.md`, `api-spec.md` | 15 |
| Usage / Charging | Supplier usage ingestion, dedup cursors, tariff versions, reconciliation status, spending controls, suspension | `data-model.md` | 16, 17 |
| Notifications | Transactional and operational messaging, delivery state, locale resolution | `localization.md`, `api-spec.md` | 18 |
| Support / Audit | Internal operations, exception queues, audited adjustments, exports | `security.md`, `api-spec.md` | 25 |

### Rules that hold across every module

- **Provider adapters stay behind their module's interface.** A provider
  advertises capabilities — native voice, supported numbers, top-up, reuse,
  suspension, usage latency, spending enforcement. A data-only adapter cannot
  satisfy a native-voice plan.
- **Payment, provisioning, installation, activation and connectivity states stay
  separate.** A paid order may be pending provisioning; installation does not
  prove network attachment.
- **An unknown supplier outcome triggers reconciliation against the same
  operation reference** — never a second purchase, and never a fallback to
  another vendor.
- **Money carries an explicit ISO currency and correctly scaled amounts.** Rates
  and metered usage use exact decimal precision with documented rounding. No
  cross-currency balance addition.
- **Disabling a module blocks new actions but still permits refunds and
  reconciliation** of existing liabilities.

## Existing code, mapped to target modules

Inventory of `6790c74`. "Reuse" means the code or its abstraction survives;
"retire" means the launch product does not include it.

| Existing path | Disposition | Target module | Owning chunk |
|---|---|---|---|
| `apps/api/app/auth/`, `app/otp/` | Reuse primitives; replace HTO-shaped access checks | Identity, Organizations | 06, 07 |
| `apps/api/app/manifests/` | Generalize CSV parsing and bulk order concepts; drop licence and pilgrimage assumptions | Organizations, Commerce | 22, 23 |
| `apps/api/app/payments/`, `app/pricing/` | Reuse adapter boundary; replace NGN-only amounts | Payments, Ledger | 10, 12 |
| `apps/api/app/packages/` | Generalize into catalog and entitlement | Catalog, Connectivity | 09, 15 |
| `apps/api/app/esim/providers.py` | Reuse provider boundary and pending-order safeguards; existing adapters are issue-only and are **not** evidence of a live integration | Connectivity | 15 |
| `apps/api/app/voice/` | Retire the app/WebRTC path as the launch mechanism; keep billing concepts | Connectivity, Usage | 04, 15 |
| `apps/api/app/checkins/`, `app/sos/`, `app/profile/` (family) | Retire agreed scope; check-in follows the product-default record, with the migration sequence in `IMPLEMENTATION-PLAN.md` §7 Phase 1 | — | 04 |
| `apps/api/app/notifications/`, `app/i18n/` | Reuse; retire feature-specific dispatch with its feature | Notifications | 04, 18 |
| `apps/api/app/audit/`, `app/admin/`, `app/reports/`, `app/retention/` | Reuse and generalize | Support / Audit | 25 |
| `apps/api/app/activation/` | Reuse; rebind redemption to the intended recipient | Connectivity, Organizations | 18, 23 |
| `apps/mobile/src/navigation/`, `screens/` | Replace the SOS / check-in / CLI / departure structure with Home / Plans / My Line / Account | — | 18–21 |
| `apps/mobile/src/services/voiceGateway.ts`, `callKit.ts` | Remove from the launch dependency graph | — | 04 |
| `apps/mobile/src/theme/`, `components/` | Reuse against the revised design system | — | 08, 18 |
| `apps/mobile/src/i18n/`, `content/` | Reuse the English/French foundation; revise copy | Notifications | 08, 18 |
| `apps/dashboard/app/manifests/`, `sos-alerts/` | Generalize manifests to people/bulk orders; retire SOS surfaces | Organizations | 04, 22, 23 |
| `apps/dashboard/app/admin/`, `reports/` | Split tenant-facing reporting from internal operations | Support / Audit | 24, 25 |
| `scripts/`, `.github/workflows/` | Reuse; re-baseline rather than rewrite | — | 02, 26, 27 |

## Revised user journeys

The product-level narrative, with acceptance criteria, is in
[`../prd.md`](../prd.md) §10.3. The routing summary:

| Journey | Chunks | Story |
|---|---|---|
| Consumer: browse → check eligibility → sign up → quote → pay → provision → install → select native line → use → top up | 09, 12, 13, 18, 19, 20 | `US-37`, `US-38` |
| Consumer recovery: restore account/service records; reinstall, transfer or replace a profile only through a supported carrier procedure | 06, 20, 21 | `US-29`, `US-38` |
| Enterprise: create organization → invite administrators → import people → bulk quote → fund → order → assign → employee installs → reconciled spend → offboard | 07, 22, 23, 24 | `US-39`, `US-40` |
| Internal operations: exception queue → supplier reconciliation → refund or adjustment → audited record | 14, 25 | `US-41` |

Two boundaries hold in every journey: dashboard provisioning never installs an
eSIM silently on an unmanaged phone — the employee installs and consents unless
a separately supported managed-device workflow exists; and a personal/work payer
selection in the app never overrides which native SIM line the handset uses for
a call.
