# Frontend Specification — HTO & Admin Dashboard
# DamDam — Version 0.1 · Next.js · Cloudflare Workers · Web (desktop-first)

One Next.js application, role-conditional routing between the HTO
operator view and the internal admin view, sharing auth patterns
and component library.

---

## 9.1 Screen Inventory

**Auth (shared)**
1. Login
2. HTO Registration
3. Email Verification Landing

**HTO Operator Screens**
4. HTO Home (pilgrim monitoring — default landing post-login)
5. Manifest List
6. Manifest Upload
7. Manifest Validation Preview
8. Manifest Family Grouping
9. Manifest Order & Invoice
10. Pilgrim Detail
11. SOS Alerts (dedicated view)
12. Reports

**Admin Screens** (role-gated, `aud: admin`)
13. Admin Home (navigation hub)
14. HTO Operator Approvals
15. Manifest Payment Confirmation
16. Failed Notification Queue
17. Device Compatibility Log
18. Naira Pricing Management

---

## 9.2 User Flow Diagrams

### Flow: HTO Operator — Manifest to Provisioned Pilgrims

```
Login
  → HTO Home
  → Manifest List → "New Manifest"
  → Manifest Upload (CSV drag-drop)
  → Manifest Validation Preview
    → [invalid rows exist] → shown inline, operator proceeds
      with valid rows only or re-uploads
    → Confirm
  → [optional] Manifest Family Grouping → select rows →
    assign group_size → repeat for multiple families
  → Manifest Order & Invoice → select pilgrims (individuals
    and/or a completed Family group) → select tier → confirm
  → [waits for admin payment confirmation]
  → [payment confirmed] → those pilgrims provisioned,
     WhatsApp activation links dispatched automatically
  → Remaining unordered pilgrims stay available for another
     order (repeat Order step as needed — data-model.md §6.5)
  → HTO Home shows the newly provisioned pilgrims in
     monitoring view
```

### Flow: Admin — Payment Confirmation

```
Login (admin role)
  → Admin Home
  → Manifest Payment Confirmation
  → [search/filter by HTO name]
  → Select pending order → review invoice, verify bank
    transfer externally (manual bank reconciliation)
  → "Confirm payment received" → confirmation dialog
    (irreversible, real-money action) → confirm → triggers
    provisioning job (system-side)
```

### Flow: SOS Response

```
[Push/email/WhatsApp notification received externally]
  → Login (if not already active)
  → SOS Alerts screen (or deep-link directly if session
    active and notification is clicked)
  → View pilgrim detail, location, contact info
  → Take action outside the system (call pilgrim, call Saudi
    authorities, dispatch group leader)
  → Mark "Resolved" once handled
```

---

## 9.3 Per-Screen Specifications

### Screen: HTO Home (Screen 4)

**Purpose:** Default landing screen, the operational nerve centre.

**Data displayed:** Pilgrim table — name, phone, manifest/batch,
tier, eSIM status, last check-in, SOS status. Sorted by risk by
default (unresolved SOS first, stale check-ins next, alphabetical
last).

**Built** — `apps/dashboard/app/home/page.tsx` (§9.7 amendment).
`/manifests/[id]` is unchanged and remains the single-manifest view.

**Interactive elements:**
- Filter by manifest (dropdown)
- Search by name/phone
- ~~Sort column headers~~ — not implemented, see note above
- ~~Row click → Pilgrim Detail~~ — not implemented, see note above
- Manual refresh button alongside the 60s auto-refresh indicator

**States:**
- *Loading:* plain loading text, not a skeleton table — matches
  this dashboard's existing convention elsewhere (§9.5 scope; no
  skeleton-table pattern exists in this codebase to follow)
- *Empty (no manifests yet):* CTA to create first manifest
- *Unresolved SOS present:* red banner at top of page, persistent
  until resolved, **in addition to** the pinned red row —
  deliberately redundant so an operator scrolling past the table
  can't miss an active emergency
- *Stale check-in (>24h):* amber row highlight

**Visual note:** Used by semi-technical operators under potential
stress (SOS response). Prioritise clarity and large touch/click
targets over information density. Avoid dense data-grid patterns
that assume power-user familiarity.

---

### Screen: Manifest Upload (Screen 6)

**Data displayed:** Drag-drop CSV zone or file picker. "Download
CSV template" link — necessary UX so operators have a correctly
formatted example (header row + one example row) to avoid
avoidable validation failures on first attempt.

**Interactive elements:**
- File drop/select
- "Download template" link
- "Upload" button, disabled until a file is selected

**States:**
- *Uploading:* progress indicator
- *Server validation error (malformed file):* distinct from
  row-level errors — this is a file-structure error
- *Success:* proceeds automatically to Validation Preview

---

### Screen: Manifest Validation Preview (Screen 7)

**Data displayed:** "Valid rows" (collapsed, expandable) and
"Issues found" (expanded by default — row number, pilgrim name if
parseable, specific error).

**Interactive elements:**
- "Confirm and proceed" — proceeds with valid rows only
- "Cancel and re-upload" — discards this attempt
- No inline row editing for MVP (operator fixes source CSV and
  re-uploads — a reasonable post-MVP enhancement, meaningful added
  scope now)

**Design consideration:** Duplicate warnings visually differ from
hard errors (yellow vs. red) — duplicates proceed, hard errors do
not.

---

### Screen: Manifest Family Grouping (Screen 8)

**Purpose:** UI for `POST /hto/manifests/{id}/group` — bundling
pilgrims into Family tier packages.

**Data displayed:** Checklist of valid, unordered pilgrims from
this manifest (queried via `GET
/hto/manifests/{id}/unordered-pilgrims`). Running list of already-
created groups below (member names, assigned group_size).

**Interactive elements:**
- Multi-select checkboxes
- "Group selected (N)" → confirms group_size = N, enforced within
  the Family tier's min/max (2–8)
- Created groups editable (add/remove members) or deletable
  (returns members to the ungrouped pool) **before** an order is
  placed against them — not after, since editing post-purchase
  would desync from the paid `group_size`

**Optional step** — an HTO with no families in this batch skips
straight to Manifest Order.

---

### Screen: Manifest Order & Invoice (Screen 9)

**Data displayed:** Pilgrim-selection step **first** (checklist
from the unordered pool — individuals and/or one complete Family
group), **then** tier selection. Family tier is auto-selected and
locked if the selection is a complete Family group; any tier is
selectable if the selection is individuals. Live total calculation
(wholesale rate × applicable pilgrim count).

**Interactive elements:**
- Pilgrim selection checklist
- Tier selection (conditional on selection type, as above)
- "Place order" → generates invoice, moves to awaiting_payment

**States:**
- *Awaiting payment:* persistent status badge on this order until
  admin confirms
- *Payment confirmed:* status updates automatically — worth a
  lightweight polling check specifically on this screen, since
  operators may sit here anxiously waiting

**Repeatable:** After an order is placed, remaining unordered
pilgrims stay in the pool. The operator can return to this screen
to place additional orders against the same manifest (e.g., Basic
tier for 40 individuals now, a Family order for 5 grouped pilgrims
later) — this is the concrete UI expression of the "one manifest,
multiple orders" data model decision (data-model.md §6.5).

---

### Screen: SOS Alerts (Screen 11)

**Purpose:** Dedicated, always-accessible view separate from the
Home table, so an operator can navigate directly here from a
notification without hunting through the main pilgrim list.

**Data displayed:** SOS alerts, active first — pilgrim name/phone,
timestamp, location (static map thumbnail if coordinates
available, avoiding a heavy JS map library dependency for MVP),
manifest/batch context.

**Interactive elements:**
- "Resolve" per alert
- "View pilgrim detail" link
- Filter: Active / Resolved / All

---

### Screen: Reports (Screen 12)

**US-20 implementation assumption:** This screen previously appeared
only in the §9.1 inventory, with no data/elements/states
specification — the same category of gap Screen 17 had in
`frontend-mobile.md` before US-11. Until product/design provides a
fuller per-screen treatment, the minimal implementation uses the
existing dashboard's own established conventions (matching Screens
4–11, not `design-system.md`, which explicitly excludes the
dashboard per its own §15.2 non-goals) and the US-20 acceptance
criteria directly. See `api-spec.md` §7.21 for the backend contract
and a related pre-existing spec discrepancy this also resolves.

**Purpose:** Lets an HTO operator download a per-pilgrim provisioning
CSV for their own records and NAHCON compliance (AC-20.1) — a
generation/export action, not a live monitoring view, so it does not
poll or auto-refresh the way Home and SOS Alerts do.

**Data displayed:** No table on this screen itself — the CSV is the
report; the screen is the controls to shape and request it. A
read-only summary line states which manifest(s) and date range are
about to be exported once both are chosen, so the operator isn't
downloading blind.

**Interactive elements:**
- Manifest selector — dropdown populated from `GET /hto/manifests`,
  defaulting to "All manifests" (maps to an omitted `manifest_id`,
  AC-20.3)
- Date range picker — "From" / "To" date inputs, both optional; an
  empty range downloads the operator's full provisioning history
- "Download CSV" button — disabled while a generation request is in
  flight
- No preview table before download — AC-20.4's ≤30s generation
  window is short enough that a preview step would only slow the
  actual task down, and the CSV headers (AC-20.2) are self-explanatory
  once opened

**States:**
- **Idle** — controls enabled, no request in flight
- **Generating** — shown for the AC-20.4 window; button reads
  "Generating…" and disables, plus a short note ("This can take up
  to 30 seconds for large manifests") so the operator doesn't assume
  the click failed and retry mid-request
- **Downloaded** — the browser's native download completes; the
  screen returns to Idle rather than showing a persistent success
  state, consistent with how `openManifestInvoice`'s PDF download
  already behaves elsewhere in this dashboard
- **Error** — inline message on request failure (e.g. auth expiry),
  same `role="alert"` pattern used on SOS Alerts and other screens;
  controls re-enable so the operator can retry without reloading

---

### Screen: Admin — HTO Operator Approvals (Screen 14)

**Data displayed:** Table of HTO operator registrations, filterable
by approval status (pending/approved/rejected, default pending) —
business name, operator name, email, phone, NAHCON licence number,
email-verified status.

**Interactive elements:**
- Status filter (pending/approved/rejected)
- "Approve" per pending row → confirmation dialog before firing
  (triggers the email + WhatsApp approval notifications, AC-04.5)
- "Reject" per pending row → inline reason field (required) plus a
  confirmation dialog before firing — the reason is stored
  (`organizations.rejection_reason`, `data-model.md` §6.17) but no
  AC requires notifying the operator of rejection, unlike approval

---

### Screen: Admin — Manifest Payment Confirmation (Screen 15)

**Data displayed:** Table of orders in `awaiting_payment` — HTO
business name, manifest name, total NGN, invoice link, days
pending (highlighted if >48h — an internal SLA flag).

**Interactive elements:**
- Search/filter by HTO name (necessary from day one — this is the
  highest-traffic admin screen pre-Hajj-season)
- "View invoice" (opens PDF)
- "Confirm payment received" → confirmation dialog ("This will
  provision packages for N pilgrims and cannot be undone. Confirm?")
  before firing, since this is a real-money, real-provisioning
  action

---

### Screen: Admin — Failed Notification Queue (Screen 16)

**Built** — `apps/dashboard/app/admin/sos-notifications/page.tsx`
(§9.7 amendment).

**Data displayed:** Failed `sos_notifications` rows — pilgrim
name, channel, failure reason, SOS timestamp, retry count.

**Interactive elements:**
- "Retry" per row
- Bulk retry (select multiple, retry all) — worth including since
  a systemic outage (e.g., WhatsApp API down for an hour) could
  produce many failed rows at once, and one-by-one retry would be
  painful during exactly the kind of incident where speed matters
- After either action, the row's continued presence/absence reflects
  a genuine refetch of `GET /admin/sos-notifications/failed`, not an
  optimistic local removal — a retry that fails again quickly (e.g.
  the vendor outage is still ongoing) must still show as failed, not
  silently disappear because the button was clicked

---

### Screen: Admin — Device Compatibility Log (Screen 17)

**Built** — `apps/dashboard/app/admin/device-compatibility/page.tsx`
(§9.7 amendment). No per-screen spec existed for this screen before
now, the same gap Screen 12 (Reports) had before US-20 — filled using
this dashboard's own conventions, same as that precedent.

**Data displayed:** `device_compatibility_log` rows, scoped to
`event_type=compatibility_check` only (`issuance_attempt` rows share
the table but have no device_model/platform/esim_supported to show,
api-spec.md §7.10) — device model, platform, OS version,
compatibility outcome (Compatible/Incompatible), checked-at
timestamp.

**Interactive elements:**
- Filter by platform (iOS/Android/all)
- Filter by outcome (Compatible/Incompatible/all)
- Manual refresh button (no auto-poll, per §9.6)

**States:**
- *Loading:* plain loading text (see Screen 4's note on this
  dashboard's loading-state convention)
- *Empty:* "No device compatibility checks match these filters."

---

### Screen: Admin — Naira Pricing Management (Screen 18)

**Data displayed:** Table of active pricing tiers — tier name,
current Naira price, group-tier flag (`prd.md` §5.9/US-26).

**Interactive elements:**
- "Edit" per row opens an inline/modal price field
- Submitting the new price shows a confirmation dialog with the %
  change from the current price (AC-26.3) — a lightweight,
  admin-facing version of the automated guardrail the original
  FX-cron design would have enforced — before calling `PATCH
  /admin/pricing-tiers/{tier_id}`
- On confirm, the new price is live immediately for new purchases;
  orders already in progress are unaffected (AC-26.2)
- No FX rate input or scheduling control — this screen is
  intentionally just "current price, editable," not a pricing
  calculator

---

## 9.4 Navigation Structure

**HTO operator sidebar:** Home | Manifests | SOS Alerts | Reports
| Settings

**Admin sidebar** (only visible to admin-role accounts, completely
separate navigation from the HTO view — not a toggle within the
same nav, reducing risk of an admin accidentally operating in the
wrong context): Approvals | Payment Confirmation | Notification
Queue | Device Compatibility | Naira Pricing

**Role separation enforcement:** Middleware-level route guards
mean an HTO operator cannot navigate to `/admin/*` routes even by
URL manipulation — returns 403, redirects to HTO Home.

---

## 9.5 Responsive / Device Considerations

Desktop-first, degrading acceptably to tablet width (HTO staff may
check the dashboard on a tablet at an airport departure gate
during a live flight batch). Mobile phone width is explicitly out
of scope for MVP — this is a web dashboard for operational staff
at a desk or counter. If mobile access is needed, the
recommendation is "use the desktop site in a mobile browser," not
a dedicated responsive rebuild.

---

## 9.6 Live-Update Behaviour Summary

| Screen | Update mechanism | Interval |
|---|---|---|
| HTO Home | Polling | 60s |
| SOS Alerts | Polling | 15s (tighter, given urgency) |
| Manifest Order status | Polling | 30s (only while status = awaiting_payment) |
| Admin screens | Manual refresh only | No auto-poll |

---

## 9.7 Amendment — Failed Notification Queue, Cross-Manifest HTO Home, Device Compatibility Log

Screens 4, 16, and 17 now have a frontend built against them.

**Failed Notification Queue (Screen 16)** —
`apps/dashboard/app/admin/sos-notifications/page.tsx`. Frontend only;
the retry endpoints (api-spec.md §7.10) already existed. Retry
actions refetch the list rather than removing rows locally, so a row
that fails again immediately still shows as failed.

**Cross-Manifest HTO Home (Screen 4)** —
`apps/dashboard/app/home/page.tsx` replaces the narrower
unresolved-SOS-only `/home` this section previously described as an
open gap. `GET /hto/pilgrims` already aggregated across manifests
with no `manifest_id` filter; `HtoPilgrimSummary` gained
`manifest_id`/`manifest_name` (data-model.md §6.38) to label each
row's manifest. Column-header sorting and row-click-to-Pilgrim-Detail
are not implemented (Pilgrim Detail, Screen 10, doesn't exist yet;
no sortable-header pattern exists elsewhere in this dashboard).

**Device Compatibility Log (Screen 17)** —
`apps/dashboard/app/admin/device-compatibility/page.tsx` and a new
`GET /admin/device-compatibility-log` endpoint (`apps/api/app/admin/
routes.py`, `DeviceCompatibilityService.list_checks`) — api-spec.md
§7.10 documented this endpoint, but it didn't exist until now.
Scoped to `event_type=compatibility_check` rows; `issuance_attempt`
rows (data-model.md §6.19) share the table but have no
device_model/platform/esim_supported to show. Known gap: the outcome
filter can't isolate a null `esim_supported` value — not fixed here
since compatibility-check rows always populate it in practice (see
comment in `page.tsx`).

---

## 9.8 Amendment — English/French Dashboard

The dashboard uses `next-intl` with a locale cookie and persisted organization
preference. All route copy, loading/empty/error states, status labels,
accessibility text, dates, plurals, and currency formatting support English
and French. API calls send `Accept-Language`; stable API error codes remain the
client contract.

New strings follow `localization.md` §3 and keep catalog parity. Desktop tables
may expand or wrap headings for French; clipping or replacing translated
labels with raw enum values is not acceptable.

---

## 9.9 Amendment — Product Reset Replaces the HTO Dashboard

**Recorded 8 September 2026 by build chunk 01. Registered story: US-27.**
Documentation only — no screen change here.

`prd.md` §10 replaces the tour-operator dashboard with an
**enterprise/government** dashboard. Government is an organization category, not
a separate product; launch claims no universal government certification or
data-residency compliance.

- **Retired:** SOS alert surfaces, check-in rosters and any welfare or
  duty-of-care tracking. The reset must not quietly reintroduce welfare
  monitoring here after removing it from the consumer app.
- **Generalized:** manifests become validated people imports; manifest orders
  become bulk quotes and orders with per-line progress and partial-failure
  recovery; HTO operators become organization members with owner, administrator,
  billing and member roles, and administrator MFA.
- **New:** prepaid funding, approved line budgets, top-ups, invoices, receipts,
  departmental spend exports, activation requests and offboarding.

The "functional, not polished" position in §9.5 no longer determines who builds
it — Claude implements every surface and Codex reviews (see `AGENTS.md`). The
dashboard is still held to the revised design system from chunk 08, and to
rendered-state review including error, loading, empty and both locales.

Boundaries that must hold: dashboard provisioning never installs an eSIM
silently on an unmanaged phone — the employee installs and consents unless a
separately supported managed-device workflow exists; organization credit is not
automatically a shared carrier data pool; and offboarding respects personal
services and carrier ownership rules. Chunks 22, 23 and 24 own the build.
