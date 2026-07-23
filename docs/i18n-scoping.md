# Internationalization Scoping — English and French
# DamDam — Version 0.1 · Audit date: 23 July 2026

## 1. Decision summary

English/French support is a **multi-week product and engineering
workstream**, not a few days of string replacement.

The current production sources contain:

| Surface | Audited localizable source units | Source groups |
|---|---:|---:|
| Mobile app | **299** | 21 screen/flow groups + 6 shared/runtime groups |
| Dashboard | **287** | 15 route/layout groups + 2 shared/runtime groups |
| Frontend total | **586** | 44 groups |
| Backend API response text | **102** | 92 top-level success/error sites + 10 serialized validator messages |

The 586 figure is the number of frontend source sites that must be
migrated and reviewed. It is not an estimate and it is not a claim that
there will be 586 unique catalog keys: repeated actions such as “Try
again” should share keys after extraction.

There is currently no i18n library, locale resolver, locale field,
translated resource file, or locale-aware route in either frontend.
The backend also has no recipient locale and explicitly sends Meta
WhatsApp templates with language code `en`.

A sensible first release should:

1. infer English/French from the device or browser;
2. present an explicit language choice before signup and retain a
   settings-level override;
3. store the selected locale for each actual message recipient;
4. bundle both mobile catalogs so SOS, check-in, eSIM help, and the
   emergency phrasebook remain usable offline; and
5. keep stable API error codes while translating frontend display copy
   and backend-originated notifications in their own layers.

Locale must not be derived from `destination_country`. Cameroon is the
clearest counterexample, and the existing country field describes trip
destination rather than reading language.

## 2. Audit method and counting rules

The audit covered production `.ts`, `.tsx`, JavaScript, and Python
sources under `apps/mobile`, `apps/dashboard`, and `apps/api`. Tests,
comments, CSS class names, test IDs, API paths, internal state-machine
values, and developer-only exception/log text were excluded.

A **localizable source unit** is one message a translator would receive:

- adjacent JSX fragments plus their interpolation are one unit;
- conditional wording variants are separate units;
- an identical literal repeated within one screen/flow group is counted
  once;
- the same literal in different groups is counted once in each group,
  because both source sites must be migrated;
- accessibility labels/hints, placeholders, browser/native permission
  copy, notification fallbacks, and pre-filled WhatsApp copy are
  included;
- the five English labels in the Arabic phrasebook are included, while
  Arabic script and Latin transliterations are not English-string
  counts; and
- raw API/status values rendered to users are called out separately
  because they are not always English literals in the rendering file.

The non-production screenshot picker contains another **14 English
harness labels** (13 target labels plus “Screenshot harness”). They are
excluded from the 299 mobile production total, but the harness itself
needs locale support for bilingual visual QA.

## 3. Current mobile state

### 3.1 Exact production inventory

| Screen, component, or runtime group | Units | Representative scope |
|---|---:|---|
| Activation Code Entry | 11 | headings, instructions, field/accessibility copy, preview labels, validation/failure copy |
| Activation Success | 12 | redeeming/error/success states, package summary labels, actions |
| Active Call | 11 | connection and quality states, call type, mute/speaker/end actions |
| Dial Pad | 20 | balance/offline/errors, keypad accessibility, contacts, recent calls, call actions |
| eSIM Activation Flow | 3 | container-level activation/load failures |
| eSIM Activation Guide + guide content | 23 | screen copy plus 9 instruction/caption pairs across Android and iOS |
| eSIM Arrival Prompt | 5 | arrival notification copy and automatic/manual actions |
| Device Compatibility Warning | 4 | warning title/body and actions |
| eSIM QR Code | 16 | loading/queued/ready states, QR accessibility, detail labels, install/save actions |
| eSIM Setup Intro | 8 | compatibility paths plus the pre-filled WhatsApp support message |
| Home eSIM Activation Banner | 4 | title/body/action/dismiss accessibility |
| Home Dashboard | 31 | check-in/SOS, queue plurals, dates, balances, support and calling |
| OTP Verification | 13 | helper/countdown/resend states and mapped failures |
| Package Selection | 28 | tier contents, family-size modal, pricing states, plurals and accessibility |
| Phone Entry | 6 | title/helper/field/action and fallback failure |
| PIN Setup | 10 | two stages, guidance, actions and validation failures |
| PIN Unlock | 12 | PIN/OTP recovery states, lockout and attempt plurals |
| Retail Purchase | 16 | checkout, failure, polling timeout, success and receipt copy |
| Returning Pilgrim | 13 | OTP login helper/countdown/resend states and mapped failures |
| SOS Confirm | 5 | emergency instruction, hold control, accessibility copy |
| SOS Sent | 10 | pending/sent states, call/cancel actions and confirmation dialog |
| Emergency Essentials component | 4 | section/contact/phrase headings |
| Bundled emergency phrasebook | 5 | English labels paired with Arabic and transliteration |
| Shared OTP input | 1 | default accessibility label |
| Onboarding navigator placeholders | 5 | interim handoff titles/notes |
| Native CallKit/ConnectionService copy | 9 | incoming call fallback and Android calling-account permission/channel copy |
| Local API-client fallbacks consumed by UI | 14 | auth, activation, eSIM, payment, PIN, pricing and voice network/default failures |
| **Mobile total** | **299** | |

Important non-literal mobile content:

- `PricingTier.name` is server data displayed directly. The client also
  assumes the English names `Starter`, `Basic`, `Standard`, and
  `Family`. These need stable tier codes plus translated display names,
  not translated database identifiers.
- Some client hooks display the backend's `message` field directly.
  A French UI could therefore show an English API error unless the
  client maps `error` codes to local keys.
- the payment WebView accepts a `message`/`reason` query parameter from
  the payment result URL and renders it. Provider-controlled English
  must not bypass the catalog.
- dates use `toLocaleString` without the selected app locale, and queue
  plurals are assembled manually in English.

### 3.2 Installed dependencies

`apps/mobile/package.json` contains no `i18next`,
`react-i18next`, `react-native-localize`, Expo localization package, or
equivalent. The app is bare React Native 0.86; Expo Dev Client is
present, but Expo localization is not.

### 3.3 Existing documentation

- `prd.md` explicitly makes multilingual support an MVP non-goal:
  **NG8, “Multi-language support (English only for MVP)”**.
- `design-system.md` documents only a narrow bilingual/RTL exception
  for US-12. Arabic phrase text uses the platform font and explicit
  `writingDirection: 'rtl'`; the rest of the app is described as
  English-only.
- `frontend-mobile.md` specifies English label + Arabic script + Latin
  transliteration for the five offline phrases. It also specifies
  English arrival, SOS, and eSIM-guide copy.
- No mobile spec defines locale selection, locale persistence, French
  typography/layout behavior, translation catalogs, or a locale field.
- `data-model.md` has `users.destination_country` (default `SA`) and a
  per-package destination snapshot, but no `locale` on users,
  organizations, family contacts, manifests, or sessions.

## 4. Current dashboard state

### 4.1 Exact production inventory

| Route, layout, or runtime group | Units | Representative scope |
|---|---:|---|
| Admin device compatibility | 20 | filters, outcomes, table, refresh/loading/errors |
| Admin HTO operator approvals | 22 | statuses, confirmations, rejection form, email state, actions |
| Admin manifest payment confirmation | 14 | search, confirmation prompt, ageing, invoice/payment actions |
| Admin pricing tiers | 16 | errors, price-change prompt/direction, tier type and edit actions |
| Admin failed SOS notifications | 21 | refresh/retry states, selection accessibility and table headings |
| HTO Home | 30 | risk/SOS summary, search/filter, table/statuses and empty states |
| Root layout metadata | 2 | title and description |
| Login | 7 | headings, fields, state and error |
| Manifest order/grouping | 29 | family groups, tier selection, totals, order/payment states |
| Manifest detail | 25 | risk/SOS summary, search, table/statuses and empty states |
| New manifest/upload/validation | 34 | upload, validation summary, row issues, table and confirmation |
| HTO registration | 16 | confirmation, form, NAHCON review copy and state |
| Reports | 18 | report scope/date sentence, filters, generation and errors |
| SOS Alerts | 18 | push opt-in, filters, alert states, map accessibility and actions |
| Email verification | 9 | loading/success/error and approval state |
| Shared dashboard API fallbacks | 4 | generic, authentication and administrator-session errors |
| Push foreground/service-worker fallbacks | 2 | fallback SOS notification titles |
| **Dashboard total** | **287** | |

Important non-literal dashboard content:

- several enum values are capitalized or uppercased and displayed
  directly (`pending`, `approved`, `rejected`, SOS status, notification
  channel, eSIM status, and order status);
- API-provided `failure_reason`, manifest validation errors, and API
  `message` values are rendered directly;
- `Intl.NumberFormat("en-NG")` is hardcoded for NGN, while other dates
  call `toLocaleString()` without a selected locale;
- `<html lang="en">` is static; and
- tier and package names arrive as English server data.

These dynamic values require explicit display maps or localized server
data even though they are not all counted as hardcoded JSX literals.

### 4.2 Installed dependencies

`apps/dashboard/package.json` contains Next.js 16, React, and Firebase.
It contains no `next-intl`, `next-i18next`, `i18next`,
`react-i18next`, or equivalent.

### 4.3 Existing documentation

`frontend-dashboard.md` defines the screens and English copy/states but
contains no localization plan, locale selector, locale route, or locale
field. `design-system.md` is explicitly a mobile design system and does
not fill that gap for the dashboard.

## 5. Backend and outbound-content audit

### 5.1 API responses

The API's standard error shape includes a human-readable `message`.
Production code currently contains **102 potentially user-visible
English response sites**:

| Kind | Count | Location/behavior |
|---|---:|---|
| Exception-handler messages | 87 | 80 explicit code-to-message entries, 2 validation-handler messages, and 5 SOS code-to-English transformations |
| Success `message` responses | 5 | OTP sent (two routes), PIN set, verification email sent, email verified |
| Serialized validator messages | 10 | phone, OTP, email/blank-field, activation code, coordinates, profile update and voice-number validation |
| **Total** | **102** | |

These are separate from the 586 frontend units. Today both frontends
can display API `message` strings, so translating only the frontends
would still leak English.

Recommended rule: `error` remains the stable contract; first-party
clients map it to local keys. The English `message` can remain a
backward-compatible fallback until the API has a documented
`Accept-Language` contract. Pydantic validator text needs machine codes
before it can be translated reliably.

### 5.2 Email, WhatsApp, SMS and push

The backend has four distinct localization paths:

1. **Resend email:** five implemented email families—SOS,
   verification, approval, invoice, and retail receipt. SOS has
   triggered/cancelled variants. Subjects and HTML bodies are composed
   directly in English in `app/notifications/providers.py`.
2. **Meta WhatsApp:** eight template families—operator approval, eSIM
   ready, family nomination, package activation, receipt, check-in, SOS
   triggered, and SOS cancelled. The template language is hardcoded as
   `{"code": "en"}`. Template bodies live in Meta rather than this repo,
   so French variants require Meta template configuration/approval as
   well as code changes.
3. **Termii/Twilio and fallback SMS:** Termii's OTP body is hardcoded in
   English. Check-in fallback SMS has one English template; SOS fallback
   SMS has triggered and cancelled variants. The provider-neutral OTP
   and notification interfaces currently accept no locale.
4. **Push:** server SOS push has triggered/cancelled English variants;
   mobile arrival copy is English; dashboard foreground/service-worker
   fallbacks are English.

There are also two client-generated, pre-filled English WhatsApp
support messages (eSIM support and balance add-on support).

No notification dispatch context carries the pilgrim, family contact,
operator, or admin locale. This is the principal backend architecture
gap.

## 6. Proposed architecture

### 6.1 Locale model and resolution

Use BCP 47 language tags constrained initially to `en` and `fr`.
Country-specific variants can be introduced later without renaming
keys.

Resolution order:

1. an explicit saved user/operator choice;
2. a pre-account invitation or organization default;
3. device/browser locale (`fr-*` resolves to `fr`, otherwise `en`);
4. final fallback `en`.

Recommended persisted fields:

- `users.locale` — non-null `en | fr`, backfill existing rows to `en`;
- `organizations.locale` — controls dashboard default and messages to
  the HTO operator;
- `admin_users.locale` if admin preference must persist across browsers;
- `family_contacts.locale` — selected during nomination because the
  family contact, not the pilgrim, is the recipient; and
- `manifest_pilgrims.locale` or an optional manifest CSV `locale`
  column, defaulting to the organization locale, because package
  activation WhatsApp is sent before the pilgrim has an account.

The auth/profile response and secure mobile `PersistedSession` should
carry `locale`. The dashboard can use a signed/authenticated cookie for
rendering and synchronize it to the organization/admin preference.
Unauthenticated OTP/HTO registration requests need a locale parameter
because no stored recipient exists yet.

Any implementation of these fields requires a numbered
`data-model.md` amendment and synchronized `api-spec.md` changes.

### 6.2 How the user sets it

Use **both inference and selection**:

- On first launch, infer from the device/browser and preselect it.
- Show a visible `English | Français` choice before Phone Entry on
  mobile and at HTO registration/login on web.
- Persist the choice on account creation and expose it later in
  settings/profile.
- Existing accounts start in English until they opt into French.
- An activation link may carry a non-authoritative `lang=fr` hint so
  the pre-account screen opens correctly; the user can still change it.

The existing code does **not** currently set `destination_country` in a
signup screen; it defaults to `SA`, and packages snapshot it at
purchase. Locale should be account/recipient preference, not a package
snapshot. Destination remains a separate content/commerce dimension.

### 6.3 Mobile catalogs and lookup

Suggested layout:

```text
apps/mobile/src/i18n/
  index.ts
  locale.ts
  locales/
    en/
      common.json
      auth.json
      home.json
      esim.json
      safety.json
      payments.json
    fr/
      common.json
      auth.json
      home.json
      esim.json
      safety.json
      payments.json
```

Use semantic keys, not English source text:

```text
common.actions.continue
auth.otp.helper.sentTo
home.checkIn.queued
home.queue.pendingEvents
esim.activationGuide.ios.addEsim
safety.sos.sent.pending
safety.phrases.needDoctor.label
```

Interpolation and pluralization must be first-class; English string
concatenation such as `"{count} events waiting to send"` and
`"check-ins and SOS alerts"` will not translate safely.

Recommended dependencies:

- `i18next` + `react-i18next`: justified by 299 mobile source units,
  plural rules, interpolation, fallback behavior, and testable runtime
  language switching. A hand-rolled lookup is small initially but
  becomes safety risk around plurals and missing keys.
- `react-native-localize`: justified for reliable device locale and
  locale-change detection in a bare React Native app. It should only
  choose the initial/default locale; saved user choice wins.

All translation JSON must be bundled in the binary. No network fetch is
acceptable for check-in, SOS, PIN unlock, activation help, or emergency
content.

### 6.4 Dashboard catalogs and lookup

Use the same namespace/key conventions under
`apps/dashboard/messages/en` and `fr`.

`next-intl` is the recommended dashboard dependency because the app
uses the Next App Router and needs locale-aware server metadata,
`<html lang>`, client components, plurals, dates, and currency. It is
not needed for SEO locale routes: this is an authenticated operational
dashboard, so a locale cookie/provider is sufficient. If avoiding the
dependency is a hard constraint, a typed dictionary/context can work,
but it must still implement key parity, interpolation, plural rules,
and `Intl` formatting; that is material custom infrastructure at 287
source units.

Replace raw enum rendering with explicit maps such as
`status.approval.pending`, and call `Intl.DateTimeFormat(locale)` /
`Intl.NumberFormat(locale, {currency: "NGN"})` consistently.

### 6.5 Backend translation boundary

Keep provider abstractions vendor-neutral and add a translation/rendering
layer above them:

```text
domain event + recipient locale + structured variables
  -> NotificationRenderer
  -> localized subject/body or provider template selection
  -> EmailSender / WhatsAppSender / SMSNotificationSender / PushSender
```

Do not put French conditionals in route handlers or provider adapters.
The renderer should own email/SMS/push catalogs and return fully
rendered content. Meta WhatsApp selection should map
`(event, locale)` to an approved template name/language code. OTP
providers should accept locale through `OTPService`; each adapter can
then use the provider's supported locale mechanism or a localized
custom body.

Backend time formatting should use recipient locale and an explicit
time zone. The current `%d %b %Y` English month abbreviations and fixed
`WAT` strings are not locale-safe.

## 7. Work that is not string swapping

### 7.1 Arabic phrasebook and offline content

The phrasebook is not an i18n catalog today; it is a bundled content
object with English label, Arabic, and transliteration. For a French
UI, translate only the label to French while preserving reviewed Arabic
and transliteration. Keep destination content separate from interface
locale: a French-speaking pilgrim travelling to Saudi Arabia still
needs Arabic phrases.

The SOS screens should expose this component as required by AC-12.4.
French safety phrasing needs human review for clarity under stress, not
literal or machine translation.

### 7.2 eSIM activation guides and screenshots

This is both engineering and asset production:

- instruction/caption text needs French;
- screenshots containing OS text need French-device-language versions;
- the pending real-device Android library (Tecno, Infinix, itel,
  Samsung Galaxy A) therefore needs English and French captures;
- iOS needs separate English and French Settings-flow captures; and
- screenshot-to-instruction matching must remain correct as OS wording
  changes.

The CI harness currently validates exactly 12 screenshots in each
platform job and has no locale dimension. Running the existing target
set in both locales would make that **24 per platform**, with locale in
target/artifact names and completeness checks. Visual review must
include French expansion, truncation, and accessibility labels.

### 7.3 SOS, emergency and legal review

SOS/check-in copy, push/email/WhatsApp/SMS fallbacks, cancellation
wording, and “help is coming” claims are safety-sensitive. French
versions should be reviewed by a native speaker familiar with Senegal,
Ivory Coast, and Cameroon usage.

No current mobile or dashboard screen contains a privacy policy, Terms
of Service acceptance, or other legal/consent block. This is not a
translation saving: `security.md` still lists privacy policy and Terms
of Service work as pre-launch legal actions. If those notices are
introduced for the expansion, their French versions need local counsel
review, including the family-contact notification basis and emergency
service limitations. This report does not determine country-specific
legal sufficiency.

### 7.4 Market expansion beyond language

The current product is Nigeria-specific in ways French translation does
not solve:

- phone validation and identity assume Nigerian numbers;
- caller ID, pricing, currency, support copy, and tier benefits refer to
  Nigeria/NGN;
- HTO onboarding and approval require a NAHCON licence;
- SMS/WhatsApp recipient fields have Nigeria-oriented length and flow
  assumptions; and
- destination remains Saudi Arabia-only in the current product model.

Senegal (`+221`), Ivory Coast (`+225`), and Cameroon (`+237`) therefore
need a separate market-expansion audit for identity, payments,
operator licensing, support, and regulatory requirements. Cameroon
also makes explicit user language choice mandatory; country inference
alone cannot choose between English and French.

### 7.5 Layout, formatting and accessibility

French copy is often longer. Test every fixed-width button, modal,
dashboard table heading, SOS control, eSIM step card, and native
permission message for wrapping/truncation. Also cover:

- locale-aware plural categories and sentence order;
- dates, month names, decimal/group separators and currency;
- accessibility labels/hints and screen-reader language;
- search/filter/status display maps;
- App Store/Play Store listing copy and notification permission text;
  and
- fallback behavior while offline or when a key is missing.

## 8. Delivery plan and estimate

### 8.1 Engineering slices

| Slice | Rough effort |
|---|---:|
| Locale schema/API/session design and migrations | 2–3 engineer-days |
| Mobile runtime, extraction of 299 units, formatting and tests | 5–7 engineer-days |
| Dashboard runtime, extraction of 287 units, formatting and tests | 4–6 engineer-days |
| Backend error-code cleanup and localized notification renderer | 4–6 engineer-days |
| Locale-aware signup/profile/manifest/family-contact flows | 3–5 engineer-days |
| Screenshot harness matrix, visual/accessibility regression | 3–5 engineer-days |
| French translation, native-speaker review and copy corrections | 3–5 specialist-days |
| Activation-guide image production and legal/vendor review | external; potentially 1–3 calendar weeks |

Some slices overlap, but the work is still approximately **3–4
engineering weeks for one engineer**, or **4–6 calendar weeks
end-to-end** once translation review, Meta template approval, activation
assets, and safety/legal review are included.

A frontend-only proof of concept could be shown in a few days, but it
would not constitute French support: API errors, OTP, family
notifications, SOS channels, activation links, and screenshots would
remain English.

### 8.2 Suggested release gates

1. English/French catalog key parity fails CI on missing keys.
2. No first-party screen renders API `message` or raw status enums
   without a localized mapping.
3. Both locale suites cover signup, OTP/PIN, purchase, eSIM setup,
   check-in and SOS pending/sent/cancelled states.
4. Offline launch in each saved locale proves catalogs and emergency
   content are bundled.
5. Notification tests assert locale selection for all eight WhatsApp
   families, five email families, OTP, check-in/SOS SMS and push.
6. Android and iOS screenshot artifacts contain both locale matrices
   and pass truncation/design review.
7. Native-speaker safety-copy review and required legal review are
   recorded before release.

## 9. Recommendation

Greenlight this as a dedicated i18n foundation feature, not a copy-only
ticket. The smallest credible scope is English/French UI plus
recipient-locale persistence and all transactional/safety channels.
Defer only the broader country-market changes to a separate workstream;
do not defer SOS, OTP, activation, or family-notification localization
if the product is presented as French-supported.
