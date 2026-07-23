/**
 * US-12 AC-12.2/12.3 — bundled directly in the app (not fetched), so this
 * content is always available offline at zero data cost. See
 * data-model.md §6.20 for why this replaced a country-keyed DB table.
 *
 * Only Saudi Arabia (`SA`) is in scope for MVP, so this is a flat list,
 * not keyed by destination country — see §6.20 for the "add a table when
 * there's a second country to justify it" reasoning.
 */

export interface EmergencyPhrase {
  key: string;
  arabic: string;
  /** Latin transliteration, for a pilgrim attempting to say the phrase
   * aloud — the Arabic script itself is the primary content, for showing
   * to a local reader; this is a secondary aid, not a replacement. */
  transliteration: string;
}

export const EMERGENCY_PHRASES: readonly EmergencyPhrase[] = [
  { key: 'help', arabic: 'ساعدني', transliteration: 'sa-i-dnee' },
  { key: 'thank_you', arabic: 'شكراً', transliteration: 'shuk-ran' },
  { key: 'where_is', arabic: 'أين...؟', transliteration: 'ay-na...?' },
  {
    key: 'i_dont_understand',
    arabic: 'لا أفهم',
    transliteration: 'la af-ham',
  },
  {
    key: 'i_need_a_doctor',
    arabic: 'أحتاج إلى طبيب',
    transliteration: 'ah-taj i-la ta-beeb',
  },
] as const;
