# Mobile App Design System
# DamDam — Version 1.0

This is the visual and interaction vocabulary for `apps/mobile`.
Per `AGENTS.md`'s "Who implements what," Codex builds every mobile
screen except the named exceptions (SOS Confirm/Sent, onboarding)
strictly against the tokens and patterns below — no improvised
spacing, color, or component choices. Gaps get flagged in the PR
description as a design-system omission, not guessed at.

**Who this is for:** Nigerian Hajj/Umrah pilgrims, majority
mid-range Android (Tecno, Infinix, Samsung A-series), meaningful
iOS minority, ages 40–70, first-or-second international trip, may
have limited comfort with app-based purchases, using the app
outdoors in Saudi Arabia in direct desert sunlight (`prd.md` §3.1).
Every decision below is made against that user, not against what
looks current in a design portfolio. Concretely, that means:
hairline borders instead of shadow-only elevation (shadows wash out
in direct sun and on the color-limited displays common to this
device tier), a floor on touch-target and text size well above
typical fintech defaults, icon+label pairing wherever an icon would
otherwise carry the full meaning, and calm/deliberate motion over
anything that reads as trendy or throwaway. `voltagent/awesome-
design-md`'s Wise, Expo, and Coinbase documents were read for tone
(trust through restraint, technical legibility, institutional
calm) — nothing here is copied from them; DamDam's constraints
(older users, sunlight, safety-critical actions, a pilgrimage
context that should feel respectful rather than "fintech-startup
flashy") point in a distinct direction.

---

## 15.1 Required sections

### 1. Color tokens

**Primary — Horizon Teal.** A deep blue-teal, not pure green:
green is reserved entirely for the "healthy/success" semantic so it
never has to compete with the brand color for meaning. Reads as
calm and trustworthy without leaning into generic fintech blue.

| Token | Hex | Usage |
|---|---|---|
| `primary-700` | `#073E45` | Pressed/active state, text-on-tint emphasis |
| `primary-500` | `#0B6B66` | Default — primary buttons, active tab icon, links, focus ring |
| `primary-100` | `#E3F1F1` | Selected-state fill, subtle highlight backgrounds |

**Accent — Desert Gold.** Used sparingly and *only* as small,
static, non-alert surfaces: the "Recommended" tier badge, Family-
tier accents, onboarding illustration highlights. Never used for a
banner, never used as body text color, and never used at full
saturation across a large area — this keeps it from ever being
mistaken for the Warning semantic in a glance, which matters in a
safety-critical app.

| Token | Hex | Usage |
|---|---|---|
| `accent-500` | `#C68A2E` | Badge fills (paired with `gray-900` text, never white) |

**Semantic.** Directly drive the low-data/low-minutes states in
`frontend-mobile.md` §8.3 and the eSIM/sync status badges.

| Token | Hex | Usage |
|---|---|---|
| `success-700` | `#167A52` | Text/icon on white — "Active," "Synced," healthy progress fill |
| `success-500` | `#1E8A5F` | Large fills, icons ≥20px, progress-bar fill at ≥20% remaining |
| `success-100` | `#E4F5EC` | Banner/badge tint background |
| `warning-500` | `#D9531E` | Icon/left-border/progress-bar fill, 5–19% remaining |
| `warning-100` | `#FBEAE0` | Banner/badge tint background |
| `error-700` | `#C0392B` | Text/icon on white, exhausted/failed states, destructive buttons |
| `error-100` | `#FBE7E4` | Banner/badge tint background |
| `info-500` | `#3B7DBF` | Icon/left-border for neutral informational banners ("Ready to activate," eSIM-incompatible notice) |
| `info-100` | `#E7F0F9` | Banner/badge tint background |

**Neutral / grayscale.**

| Token | Hex | Usage |
|---|---|---|
| `gray-900` | `#14181A` | Primary text, icons |
| `gray-700` | `#445050` | Labels, secondary headings |
| `gray-600` | `#5A6666` | Minimum-size secondary/caption text (see contrast note below) |
| `gray-500` | `#728080` | Large-text-only secondary content, disabled text, placeholders |
| `gray-300` | `#C4CACA` | Default borders, dividers, disabled fills |
| `gray-200` | `#DDE1E1` | Card borders, progress-bar track, tab-bar top border |
| `gray-100` | `#EDEFEF` | Neutral banner fill (e.g. "queued events," non-alarming) |
| `gray-50`  | `#F7F8F8` | Screen background |
| `white`    | `#FFFFFF` | Card/surface background, text on filled buttons |

**Contrast confirmation (WCAG AA, computed against white unless
noted).** Body text must clear 4.5:1; large text (≥18px, or ≥14px
bold) and icons/UI components must clear 3:1.

| Pair | Ratio | Verdict |
|---|---|---|
| `gray-900` on white | 17.9:1 | Body text ✓ |
| `gray-600` on white | 5.95:1 | Body text ✓ (floor for secondary text) |
| `gray-500` on white | 4.11:1 | Large text / icons only, not body |
| `primary-500` on white | 6.35:1 | Body text ✓ |
| `success-700` on white | 5.33:1 | Body text ✓ |
| `success-500` on white | 4.33:1 | Large text / icons only, not body |
| `error-700` on white | 5.44:1 | Body text ✓ |
| `warning-500` on white | 4.04:1 | Large text / icons only, not body |
| white on `primary-500` (filled button) | 6.35:1 | ✓ |
| white on `error-700` (destructive button) | 5.44:1 | ✓ |

**The rule this produces:** `warning-500` and `success-500` do not
reliably clear body-text contrast on white, so semantic alerts
never render as colored text on a white background. Every banner
and badge uses a light tint background (`*-100`) + `gray-900` body
text + the full-saturation color only on the icon and a left
border/accent. This is a hard rule, not a style preference — it's
the only pattern in this palette that stays legible outdoors and
under AA at every semantic color simultaneously.

---

### 2. Typography scale

**Font: Inter**, bundled as a local asset (not fetched at runtime —
this app is offline-first, so a network-dependent font is a
non-starter). SIL Open Font License 1.1: free for commercial use,
no runtime attribution required. Chosen over the platform system
fonts (Roboto/San Francisco) deliberately: DamDam screenshots
circulate in HTO WhatsApp groups and between family members
comparing what they're seeing, so visual consistency between the
iOS and Android builds outweighs native-font familiarity here (see
Platform adaptation rules, below). Inter also ships true tabular
figures, which matters for the data/minutes numerals on Home
Dashboard and Package Details staying vertically aligned as they
count down.

Weights used: **Regular (400), Medium (500), Semibold (600), Bold
(700)** only. No Light/Thin weight anywhere in the system — hairline
weights lose legibility on mid-range display panels in direct
sunlight.

Minimum readable size is set well above typical fintech defaults
given the 40–70 demographic: **14px is the absolute floor for any
text in the app**, reserved for non-critical metadata only, and no
interactive or primary-content text ever goes below 16px.

| Token | Size / Line-height | Weight | Usage |
|---|---|---|---|
| `display` | 32 / 40 | 700 | Rare, high-impact moments only (Purchase Success, SOS Sent headline) |
| `heading-1` | 28 / 36 | 700 | Screen titles |
| `heading-2` | 22 / 30 | 600 | Section headers, package tier name on cards |
| `heading-3` | 18 / 26 | 600 | List item titles, card subheadings |
| `body-large` | 17 / 26 | 400 (600 for emphasis) | Default reading text, all button labels |
| `body` | 16 / 24 | 400 | Secondary paragraph text |
| `caption` | 14 / 20 | 500 | Timestamps, helper text, legal fine print — the system floor, never used for anything tappable or primary |
| `numeral` | 24 / 28 | 700, tabular-nums | Data GB / minutes-remaining readouts, OTP/PIN digits |

Line-heights are set at 1.4–1.53× across body sizes (above the
1.4× WCAG 1.4.8 guidance), a deliberate margin given the
demographic rather than the minimum-compliant value.

**Bilingual / RTL content (first introduced in US-12):** Inter is
bundled as a local Latin-only asset (§2, above) with no Arabic
glyphs, and the app has no font-swap infrastructure. Rather than
build one for a single Arabic phrasebook, any Arabic-script text
**does not** set `fontFamily: 'Inter'` — it inherits the platform
system font (San Francisco / Roboto), both of which cover Arabic
natively, and sets `writingDirection: 'rtl'` + `textAlign: 'right'`
explicitly rather than relying on Unicode bidi auto-detection,
since a short standalone phrase (not embedded in a longer LTR
paragraph) is exactly the case auto-detection handles least
reliably. Size/weight tokens from the table above still apply —
this is a font-family and direction exception only, not a
separate type scale. If Arabic content grows beyond a short
phrase list, revisit bundling an Arabic-covering face rather than
continuing to special-case system fonts per instance.

---

### 3. Spacing & layout scale

Base unit: **4px**. All padding/margin values are multiples of it —
Codex should never hand-pick an arbitrary pixel value.

| Token | Value |
|---|---|
| `space-1` | 4px |
| `space-2` | 8px |
| `space-3` | 12px |
| `space-4` | 16px |
| `space-5` | 20px |
| `space-6` | 24px |
| `space-8` | 32px |
| `space-10` | 40px |
| `space-12` | 48px |
| `space-16` | 64px |

**Layout conventions:**
- Screen horizontal padding: `space-5` (20px)
- Card internal padding: `space-4` (16px)
- Vertical gap between sections on a screen: `space-6` (24px)
- Vertical gap between list items: `space-3`–`space-4` (12–16px)

**Touch targets:** minimum **48×48dp on both platforms** — this
overrides iOS HIG's native 44pt minimum; the demographic constraint
(older users, larger fingers, possibly outdoors/gloved in transit)
takes precedence over platform-default sizing. Primary safety/hero
actions ("I'm okay," "Get connected," package tier cards) use
64dp-minimum height, not just the 48dp floor.

---

### 4. Component patterns

**Buttons**
- *Primary:* filled `primary-500`, white `body-large` (600) text,
  `12px` corner radius, 48dp min height (64dp for hero CTAs),
  full-width by default.
- *Secondary:* `2px primary-500` border, `primary-500` text,
  transparent/white fill, same sizing as Primary.
- *Destructive:* filled `error-700`, white text — for ordinary
  irreversible actions (e.g. removing a saved contact in Settings).
  Not used for the SOS button itself, which is a named exception
  styled directly by Claude in `SosConfirm`/`SosSent`.
- *Tertiary/text:* `primary-500` text, no fill or border — low-
  emphasis actions like the Package Selection "What's included"
  accordion trigger.
- *Disabled:* `gray-300` fill/border, `gray-500` text — deliberately
  kept legible rather than faded to near-invisible, since disabled
  buttons in this app (e.g. Dial Pad's Call button with zero
  minutes) need to still read as "a button that's currently off,"
  paired with an explanatory tooltip/caption per `frontend-
  mobile.md` §8.3.
- *Press feedback:* 8% black scrim + 0.98 scale, 100ms, no easing
  curve — near-instant, tactile.

**Cards / status displays**
- White fill, `1px gray-200` border always present. Shadow
  (`elevation-1`, 0/2px blur, 8% black) is additive and only added
  to cards that are themselves tappable, as an affordance hint —
  never relied on alone, since shadow-only elevation can wash out
  in direct sunlight or on limited-gamut mid-range panels.
- `16px` corner radius (one step larger than the `12px` button
  radius — a consistent two-tier radius system across the app).
- `space-4` (16px) internal padding.
- **Package status card** (Home Dashboard): tier name in
  `heading-2`, data-remaining and PSTN-minutes-remaining each as a
  labeled progress bar (below), eSIM status badge pinned top-right.
- **Progress bar:** `gray-200` track, 8px height, fully rounded
  ends. Fill color follows the same thresholds as the banners:
  `success-500` at ≥20% remaining, `warning-500` at 5–19%,
  `error-700` at <5%/exhausted. Fill transitions animate per the
  Motion section.
- **Status badge/pill:** fully rounded, `caption` (600) text, `*-100`
  tint fill + `*-700`/`gray-900` text (never full-saturation fill
  with white text — pills are small enough that AA on a light tint
  is the reliable option). "Not activated" = `gray-200`/`gray-700`;
  "Ready to activate" = `info-100`/`info-500`+icon; "Active" =
  `success-100`/`success-700`; "Recommended" = `accent-500` fill +
  `gray-900` text (the one pill allowed a saturated fill, since gold
  is reserved exclusively for this non-alert context).

**Form inputs**
- 52dp min height — taller than the button floor, since typing
  precision matters more than tap precision for this demographic.
- Label always sits above the field as static `caption` (600)
  `gray-700` text — never a floating label that shrinks on focus,
  which produces illegibly small text for low-vision users.
  Placeholder text (`gray-500`) is reserved for format hints (e.g.
  `080XXXXXXXX`) and is never the field's only label.
- Border: `1.5px gray-300` default, `2px primary-500` on focus,
  `2px error-700` on validation error. Errors always pair an inline
  `caption` (600) `error-700` message *and* an error icon below the
  field — never color alone (WCAG 1.4.1).
- **OTP / PIN entry:** six (or four, for PIN) separate boxes,
  48×56dp each, `numeral` scale digits, auto-advance on entry — the
  same box pattern reused for both so it only has to be learned
  once.

**Banners / alerts**
Full-width, left-aligned icon + `body` `gray-900` message, optional
trailing action link. Always tint-background + full-saturation
icon/left-border, per the contrast rule in §1 — never colored text
on white.
- `info-100` fill / `info-500` icon+border — neutral information
  (e.g. eSIM-incompatible persistent notice).
- `warning-100` fill / `warning-500` icon+border — data/minutes
  5–19% remaining.
- `error-100` fill / `error-700` icon+border — exhausted/failed
  states.
- `gray-100` fill / `gray-700` icon+text, no colored border — the
  offline queued-events indicator specifically, which is
  deliberately neutral in tone (a non-empty queue isn't a problem
  by itself, and shouldn't read as one).
- Dismissible banners get a top-right `×`, 44dp tap target
  (generous invisible padding around a small glyph). Persistent,
  safety-relevant banners (eSIM-incompatible notice) have no
  dismiss control.
- Banners stack directly below the screen header, above content;
  never overlap the bottom tab bar or the SOS button's tap area.

**Bottom tab bar**
- Four items — Home / Call / Safety History / Settings — **always
  icon (24px) + label (`caption`, 500)**, never icon-only. This is
  a hard rule for this component specifically, given the literacy/
  tech-confidence constraints called out in `prd.md` §3.1.
- 64dp height + safe-area inset. White/`gray-50` fill, `1px
  gray-200` top border (a hairline, not a shadow, for the same
  sunlight-visibility reason as cards).
- Active: `primary-500` icon+label. Inactive: `gray-500` icon+label.
- No unread/notification badge dots on the tab bar for MVP —
  unexplained red dots test poorly with low-tech-confidence users;
  anything that needs surfacing gets an explicit banner instead.

---

### 5. Iconography

**Library: Phosphor Icons**, MIT-licensed, `phosphor-react-native`.
Default weight is **Bold**, not Regular/hairline — a heavier stroke
holds up better in direct sunlight and on limited-gamut mid-range
displays; Regular weight is reserved for large (32px+) decorative
or empty-state illustrations only, where a thin stroke isn't
fighting for legibility at small sizes.

| Size | Usage |
|---|---|
| 16px | Inline with `caption` text |
| 20px | Inline with `body`/`body-large` text (default) |
| 24px | Standalone tap targets, tab bar icons |
| 32px | Feature/empty-state icons |
| 48px+ | Named-exception screens only (SOS) — out of scope here |

Icons inherit surrounding text color by default (`gray-900` or
`primary-500` for active states); semantic icons (banner/badge)
take their semantic color per §1.

**Icon+text rule:** any icon that triggers a navigation or
destructive action must always be paired with a visible text label.
Icon-only is permitted *only* for a small allowlist of universally
unambiguous actions — close (`×`), back (chevron), dismiss — never
for anything that changes app state or costs money. This is the
direct mitigation for the "may have limited English reading
fluency" note in `frontend-mobile.md` §8.5: the app is English-only
for MVP (`prd.md` NG8), so icon+label pairing is the compensating
control, not a nice-to-have.

---

### 6. Motion & interaction conventions

- **Screen transitions** (push/pop, tab switch): 200ms,
  `cubic-bezier(0.2, 0.0, 0.0, 1.0)` (ease-out). Fast enough not to
  feel sluggish on mid-range Android hardware, slow enough to read
  as deliberate rather than abrupt — an abrupt cut reads as "cheap"
  in a trust-critical app.
- **Modals:** present via slide-up + fade, 250ms ease-out; dismiss
  200ms ease-in.
- **Micro-interactions** (button press, toggle, checkbox): 100ms,
  no easing curve — near-instant.
- **SOS hold-to-confirm countdown ring** (Screen 26): 3000ms,
  **linear** timing specifically, not eased. A safety countdown
  should let the user predict exactly how much time remains at a
  glance; easing would distort that. `gray-200` track, `error-700`
  fill sweeping clockwise from 12 o'clock, constant color throughout
  (no color-shift mid-countdown — a shifting color could itself read
  as a state change). Center label counts `3 → 2 → 1` in `display`-
  scale tabular numerals synced to the ring. A haptic tick fires
  each full second, with a stronger completion haptic and an
  *immediate* transition to SOS Sent Confirmation with no fade
  delay — the local write is synchronous before the transition per
  `frontend-mobile.md` §8.3, and the animation must not introduce
  perceived latency on top of that.
- **Loading / skeleton pattern** (one reusable component, reused
  everywhere rather than invented per-screen): rounded-rect
  placeholders shaped like the real content (a card skeleton is a
  card-shaped gray block with two inner bars for title/subtitle,
  not a full-screen spinner). Shimmer: 1200ms linear repeating,
  diagonal sweep `gray-100 → gray-200 → gray-100`. Per the
  offline-first pattern (`prd.md` §5.6), a skeleton only appears
  when there is genuinely zero cached data — first-ever load. A
  background refresh of already-cached content uses a small 20px
  spinner at the top of the list instead; it never replaces visible
  real data with a skeleton.
- **Reduced motion:** when the OS-level "reduce motion" setting is
  on, all 200–250ms transitions collapse to a 50ms cross-fade and
  shimmer is removed. The SOS countdown's 3-second *duration* is
  exempt — it's a literal safety timer, not decorative motion, and
  never changes; only its visual polish (the shimmer/gradient, if
  any were applied) is affected.

---

### 7. Platform adaptation rules

DamDam intentionally looks close to identical on iOS and Android —
screenshots circulate between pilgrims, family, and HTO operators
who don't know or care which platform the other person is on, so
gratuitous divergence is a liability here, not a feature. Platform
adaptation is scoped narrowly to things users would find *wrong* if
they didn't diverge:

| Concern | Rule |
|---|---|
| Navigation header | Native per-platform: iOS large-title collapsing header on tab-root screens (Home) + standard title/back-chevron on stack screens with native edge-swipe-back enabled; Android standard Material app bar, no custom swipe-back gesture (Android back is system-level, not per-screen) |
| System-level confirmations | Native dialogs (`UIAlertController` / Android `AlertDialog`) for OS permission prompts only (contacts, location, notifications) |
| Product-level confirmations | Always a custom in-app modal styled to this system (SOS Cancel Confirmation, Device Compatibility Warning) — never a native alert, so it never looks like a different app mid-flow |
| Typography | Inter bundled on both platforms — no fallback to Roboto/San Francisco (see §2) |
| Iconography | Phosphor on both platforms — no SF Symbols / Material Symbols substitution |
| Touch targets | 48dp minimum on both, overriding iOS's native 44pt default (see §3) |
| Haptics | Native APIs per platform (Android `Vibration`, iOS Haptic Engine), tuned to equivalent *perceived* intensity rather than copy-pasted duration values — the SOS completion haptic should feel comparably weighty on both, not identical on paper |
| Status bar | Dark content/icons on both platforms for virtually every screen, since the app is predominantly light-background |
| Safe area | `react-native-safe-area-context` uniformly, respecting notch/Dynamic Island (iOS) and gesture-nav bar (Android) |
| Native call UI / native dialer | CallKit (iOS) vs. ConnectionService (Android) for in-app calls, and the SOS Sent screen's "Call now" invoking the device's native dialer rather than the app's VoIP layer — both already specified in `frontend-mobile.md` §8.7; not duplicated here beyond this cross-reference |

---

## 15.2 Non-goals for this document

- Does not cover the HTO/Admin dashboard — that's explicitly
  "functional, not polished" per `frontend-dashboard.md` §9.5 and
  doesn't need this level of design rigor
- Does not re-implement the per-screen functional specs already in
  `frontend-mobile.md` §8.3 — this document covers the *visual
  vocabulary*, not screen-by-screen behavior, which stays in
  `frontend-mobile.md`

---

## 16. Amendment — Localized Layout

Components accommodate English and French without fixed text heights or
single-line assumptions. Buttons may grow vertically while preserving the
48dp target; cards, banners, SOS controls, and guide steps wrap at word
boundaries. Do not reduce the documented type scale to make French fit.

Visual review uses both locale matrices from `localization.md` §6. A component
whose French text clips, overlaps, hides an action, or weakens the SOS visual
hierarchy fails design review even when its unit tests pass.

---

## 15.3 Amendment — Product Reset Requires a Revised Design System

**Recorded 8 September 2026 by build chunk 01. Registered story: US-27.**
Documentation only — no token, pattern or component change here. **Chunk 08 owns
the revision.**

`prd.md` §10 resets the product from a Hajj-pilgrim app to a global consumer and
enterprise/government product. Two consequences for this document:

- **The SOS and emergency patterns above are retired** along with the feature.
  The reassurance-under-emergency design problem they solved no longer exists in
  this product; do not carry those patterns forward into new screens looking for
  a use.
- **The system must now cover two audiences**, a consumer mobile app and an
  enterprise/government dashboard, rather than a single pilgrim app with a
  functional operator dashboard behind it.

What carries forward unchanged: the token, typography, spacing and component
foundations; accessibility requirements; and complete English/French support
including layout behavior under longer French strings.

Two governance changes:

- **Who builds against it has changed.** The old split — Claude produces the
  system, Codex implements screens against it, Claude reviews the render — is
  superseded. Claude implements every screen and Codex independently reviews and
  may refactor (see `AGENTS.md`). The design system is still a **prerequisite**
  for screen work, and chunk 08 is a dependency of chunks 18–24.
- **The screenshot matrix is re-cut here.** Chunk 08 defines the reset
  screen/locale matrix; chunk 27 enforces a complete, nonempty manifest for it as
  a release gate. Neither the historical 0/32 nor the 33 images observed on
  2026-09-08 carries forward — both describe the old screen set.
