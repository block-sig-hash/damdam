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

**Interactive elements:**
- Filter by manifest (dropdown)
- Search by name/phone
- Sort column headers
- Row click → Pilgrim Detail
- Manual refresh button alongside the 60s auto-refresh indicator

**States:**
- *Loading:* skeleton table
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

## 9.4 Navigation Structure

**HTO operator sidebar:** Home | Manifests | SOS Alerts | Reports
| Settings

**Admin sidebar** (only visible to admin-role accounts, completely
separate navigation from the HTO view — not a toggle within the
same nav, reducing risk of an admin accidentally operating in the
wrong context): Approvals | Payment Confirmation | Notification
Queue | Device Compatibility

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
