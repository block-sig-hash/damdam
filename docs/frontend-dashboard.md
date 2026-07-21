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

**Implementation note (§9.7 amendment):** the cross-manifest roster
this section describes is now built at `/home`
(`apps/dashboard/app/home/page.tsx`), reusing the same risk-sort/
highlight/search logic `/manifests/[id]` already used (`lib/
pilgrimRisk.ts`), called with no `manifest_id` filter so it
aggregates across every manifest the organization owns —
`GET /hto/pilgrims` already supported this (api-spec.md §7.8), the
only backend gap was that `HtoPilgrimSummary` had no field to label
which manifest a row belonged to, closed by adding `manifest_id`/
`manifest_name` (data-model.md §6.38). `/manifests/[id]` is
unchanged — it remains the single-manifest view, useful when an
operator has already navigated to a specific manifest. Two
interactive elements below are **not** implemented, disclosed rather
than silently dropped: "Sort column headers" (no clickable-header-sort
pattern exists anywhere else in this dashboard to follow; the
default risk-sort is the only ordering) and "Row click → Pilgrim
Detail" (Screen 10, Pilgrim Detail, does not exist yet — see §9.1;
`/sos-alerts` has the same pre-existing dangling link for the same
reason).

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

**Data displayed:** Failed `sos_notifications` rows — pilgrim
name, channel, failure reason, SOS timestamp, retry count.

**Interactive elements:**
- "Retry" per row
- Bulk retry (select multiple, retry all) — worth including since
  a systemic outage (e.g., WhatsApp API down for an hour) could
  produce many failed rows at once, and one-by-one retry would be
  painful during exactly the kind of incident where speed matters

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

Three screens this spec described but the dashboard didn't yet have
a frontend for are now built, closing gaps against backend support
that (for two of the three) already existed:

**Failed Notification Queue (Screen 16)** —
`apps/dashboard/app/admin/sos-notifications/page.tsx`. Pure frontend
work; `GET /admin/sos-notifications/failed`, `POST .../{id}/retry`,
and `POST .../retry-bulk` (api-spec.md §7.10) were already fully
implemented and tested. Both retry actions refetch the list rather
than optimistically removing the retried row(s) — a row only
disappears once the backend confirms it (status reset off `failed`,
`admin_queued_at` cleared), so a retry that fails again immediately
still shows as failed.

**Cross-Manifest HTO Home (Screen 4)** —
`apps/dashboard/app/home/page.tsx`, replacing the previous narrower
unresolved-SOS-only banner described as a known gap in Screen 4's own
spec text above before this amendment. `GET /hto/pilgrims` already
aggregated across manifests when called with no `manifest_id`
(`HtoPilgrimService.list_pilgrims`'s filter was always optional) —
the one real backend gap was that `HtoPilgrimSummary` had no field
to say *which* manifest a row belonged to, needed for the
"manifest/batch" column this section's spec always called for.
Closed by adding `manifest_id`/`manifest_name` to `HtoPilgrimSummary`
(data-model.md §6.38, api-spec.md §7.8) — no migration, this is a
response-shape addition over existing columns, not a schema change.
Two originally-specified interactive elements are deliberately not
built, disclosed above under Screen 4 rather than silently dropped:
column-header sorting (no precedent pattern in this codebase) and
row-click-to-Pilgrim-Detail (that screen, #10 in §9.1, doesn't exist
yet).
