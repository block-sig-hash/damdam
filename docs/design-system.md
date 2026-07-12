# Mobile App Design System
# DamDam — Version 0.1 — SCAFFOLD, NOT YET PRODUCED

**Status: this document is a required prerequisite, not yet
written.** Per `AGENTS.md`'s "Who implements what" section, Codex
should not implement any `apps/mobile` screen until this document
exists — the whole point of the design-system approach (Codex
implements against explicit decisions, rather than improvising
taste-based choices) fails silently if this stays empty and Codex
builds ahead of it anyway.

**This should be produced in a dedicated Claude session**, ideally
using Claude's frontend-design capabilities directly against the
screen inventory in `frontend-mobile.md` §8.1 and the specific
demographic/device constraints in `prd.md` §3.1 (mid-range Android,
first-time international travelers, ages 40–70, low tech
confidence) — not filled in mechanically or invented as
placeholder values here.

**Starting seed for the dedicated session:** rather than starting
from a blank page, use [VoltAgent's `awesome-design-md`](https://github.com/voltagent/awesome-design-md)
as stylistic reference — it's a curated library of design-token
documents in an agent-readable format. **Wise** (trust-critical
financial app, global non-power-user audience), **Expo** (React
Native, technically relevant to this stack), and **Coinbase**
(institutional trust through restraint) are the closest reference
points in tone to what DamDam needs. Use these as *inspiration
only, not a template to copy* — the repo's own guidance is explicit
that these are extracted from real brands' actual visual identities
and shouldn't be cloned 1:1; DamDam needs its own distinct system,
diverged hard toward its actual constraints (older users, bright-
sunlight outdoor use in Saudi Arabia, larger touch targets,
safety-critical clarity over trendy minimalism) rather than
adopting any reference wholesale.



---

## 15.1 Required sections (fill in during the dedicated session)

### 1. Color tokens
Primary, secondary, semantic colors (success/warning/error/info —
these map directly to the low-data/low-minutes warning states in
`frontend-mobile.md` §8.3's Home Dashboard spec), neutral/grayscale
scale, and explicit contrast-ratio confirmation for accessibility
given the demographic (older users, possibly low-light outdoor
use in Saudi Arabia).

### 2. Typography scale
Font family (confirm licensing for commercial use), size scale,
weight scale, line-height rules — with explicit attention to
minimum readable size given the demographic skews older.

### 3. Spacing & layout scale
A consistent spacing unit (e.g., 4px or 8px base) and the
multiples used for padding/margin throughout, so Codex has a fixed
vocabulary rather than picking arbitrary pixel values per screen.

### 4. Component patterns
At minimum: buttons (primary/secondary/destructive — the SOS
button's styling is decided in the named-exception screens, but
ordinary buttons elsewhere should be consistent with it),
cards/status displays (the package status cards on Home Dashboard),
form inputs, banners/alerts (the low-data/low-minutes/offline
warning banners), and the bottom tab bar.

### 5. Iconography
Icon set/library choice, sizing rules, and usage conventions
(e.g., when an icon accompanies text vs. stands alone — relevant
given some users may have limited English reading fluency despite
the app being English-only for MVP per `prd.md` NG8).

### 6. Motion & interaction conventions
Transition timing/easing for screen navigation, the SOS hold-to-
confirm countdown animation specifically (referenced in
`frontend-mobile.md` §8.3 as needing a "visual countdown ring"),
and loading-state patterns (skeleton screens are specified in
several places in `frontend-mobile.md` — this section should give
Codex one consistent skeleton pattern to reuse, not a new one per
screen).

### 7. Platform adaptation rules
Where iOS and Android should look identical vs. where each should
follow its native platform conventions (e.g., navigation bar
styling, native alert dialogs vs. custom modals) — relevant given
the dual-platform MVP scope in `prd.md` §1/§6.

---

## 15.2 Non-goals for this document

- Does not cover the HTO/Admin dashboard — that's explicitly
  "functional, not polished" per `frontend-dashboard.md` §9.5 and
  doesn't need this level of design rigor
- Does not re-implement the per-screen functional specs already in
  `frontend-mobile.md` §8.3 — this document covers the *visual
  vocabulary*, not screen-by-screen behavior, which stays in
  `frontend-mobile.md`
