# DamDam Localization Guide

> **Current scope:** the September 2026 reset in §9 and
> [PRD §10](prd.md) governs conflicts with earlier text. Use the
> [scope disposition](implementation/SCOPE-DISPOSITION.md) and
> [decision register](implementation/DECISIONS.md) for retained, retired
> and proposed behavior. These are target requirements; existing code and
> supported transition paths remain subject to their applicable checks.

This is the ongoing engineering and release process for English and French
(`en`, `fr`). The original inventory and rationale remain in
[`i18n-scoping.md`](./i18n-scoping.md).

## 1. Locale ownership and resolution

Locale is a recipient preference, not a proxy for nationality, phone country,
destination, or billing country. Resolution order is:

1. saved user, organization, family-contact, or manifest-pilgrim locale;
2. explicit locale supplied during a pre-account flow;
3. device/browser language (`fr-*` resolves to `fr`);
4. English fallback.

Mobile persists `user.locale` in secure session state. Dashboard login
synchronizes `operator.locale` to local storage and the `damdam_locale` cookie.
Activation and verification links may include `lang`, but that hint never
overrides an explicit choice.

## 2. Frontend catalogs

Mobile uses `i18next`, `react-i18next`, and `react-native-localize`:

```text
apps/mobile/src/i18n/locales/{en,fr}/
  common.json auth.json home.json esim.json safety.json payments.json
```

Dashboard uses `next-intl` with `apps/dashboard/messages/{en,fr}.json`.
English is the source-of-truth catalog; French must have exact key parity.
Use plural and interpolation features instead of concatenated fragments.

User-visible enum values, dates, plurals, accessibility labels, placeholders,
errors, and native notification/permission copy are translatable. Brand names,
eSIM, ICCID, SOS, platform names, activation codes, phone numbers, and
user/provider data remain unchanged unless a product spec says otherwise.

## 3. Adding or changing a string

For every new or changed user-facing string:

1. add a semantic English key in the existing feature namespace;
2. add the French value in the same change;
3. use interpolation/pluralization for variables and counts;
4. render through `useTranslation`/`useTranslations`, never a literal fallback;
5. update a real component test for state, action, safety, legal, or
   accessibility copy;
6. run parity, app, type, and lint checks; and
7. include the affected screen in the two-locale screenshot matrix.

Do not pass provider-authored payment text or raw backend enum values to the
UI. Map stable codes/statuses to first-party keys.

## 4. Backend responses and notifications

API `error` values are the stable machine contract. `message` and known
validator descriptions are locale-aware fallbacks selected from
`Accept-Language`. First-party clients still map `error` locally.

`app/i18n/notifications.py` renders structured events before provider dispatch:

- organization locale: HTO email, WhatsApp, invoice, and SOS push/operator;
- family-contact locale: check-in/SOS WhatsApp and fallback SMS;
- user locale: payment receipt and eSIM-ready;
- manifest-pilgrim locale: activation before account creation; and
- OTP challenge locale: explicit pre-account choice, including failover.

Meta templates are externally managed. Configure and approve a French variant
of every family before production. `_FR` settings may choose another approved
name; otherwise the same name is requested with Meta language code `fr`.

## 5. Offline and native content

All mobile catalogs and Arabic emergency phrases are bundled. Arabic speech
text and transliteration remain Arabic; English/French labels, instructions,
and categories come from the safety catalog.

Android `values-fr` and iOS `fr.lproj` own native arrival/call/permission copy.
Native code must not reproduce frontend catalog strings in English.

## 6. Screenshot and layout verification

Every Maestro flow selects and waits for a confirmed harness locale, then
captures `*-en` and `*-fr`. Android and iOS jobs each require 32 PNG artifacts
for the current 16 applicable targets. eSIM targets cover Android’s automatic
prompt and iOS’s manual guide.

The manual guide contains designed screenshot placeholders because source OS
walkthrough images do not yet exist in either language. The harness verifies
the translated guide frame and instructions, but production OS images remain a
content deliverable: capture matching English/French iOS images on the same OS
version, localize visible system UI, add descriptions, and rerun both matrices.

Review French artifacts for truncation, wrapping, button height, table width,
SOS affordance, dynamic type, and screen-reader labels. Artifacts are CI
outputs and are not committed.

## 7. Translation provenance and release gates

The initial French catalogs were drafted with an AI language model and checked
for key parity and runtime rendering; they are substantive translations, not
placeholder markers. This does **not** constitute native-speaker approval.

Before a French-primary launch, record:

- review by a native Francophone reviewer familiar with West African usage;
- safety review for SOS, emergency phrases, check-in, OTP, and activation;
- counsel/product approval for consent, privacy, emergency limitations, family
  notification basis, and market-specific legal notices;
- approval and account-level testing of French Meta/Termii templates; and
- visual approval of both screenshot matrices and final eSIM OS imagery.

French legal or safety text must not be silently edited after approval; link
the approving review in the change.

## 8. Required checks

```bash
cd apps/mobile && npm test && npm run lint && npm run type-check
cd apps/dashboard && npm test && npm run lint && npm run type-check
cd apps/api && pytest --cov=app && ruff check . && mypy app
```

API changes also run OpenAPI drift verification. Mobile pull requests run the
Android bilingual screenshot job; iOS runs nightly or by workflow dispatch.

---

## 9. Amendment — Product Reset and Localized Content Scope

**Recorded 8 September 2026 by build chunk 01. Registered story: US-27.**
Documentation only — no catalog, key or check changed.

`prd.md` §10 resets the product. This guide's process is retained in full:
locale ownership and resolution, catalog conventions, the string-change
workflow, backend and notification localization, screenshot and layout
verification, translation provenance, and the required checks in §8.

What changes is the **content** those processes apply to:

- SOS and family-notification strings are **retired** with
  their features in chunk 04. Remove their keys and their vendor notification
  templates as part of that retirement, so no removed feature can still be
  dispatched by an old worker or client. Remaining check-in/welfare strings
  follow the product-default decision and remain tested while their path is
  supported; do not remove strings from a surviving transition flow.
- New consumer surfaces (Home, Plans, My Line, Account) and the enterprise
  dashboard need complete English and French coverage from the start — this is
  AC-37.6, not a follow-up.
- Locale stays a **recipient preference**, never inferred from country. That
  matters more, not less, in a global product: a plan's selling market says
  nothing about the buyer's language.
- Carrier-specific content — installation guidance, line settings, assigned
  number, usage freshness, charges — is new localized surface area with real
  accuracy risk. Getting an installation step wrong in French is a support
  incident, so these strings need native review, not machine translation.

The completed English/French architecture recorded in `i18n-scoping.md` §10
remains current. Additional languages remain future work.
