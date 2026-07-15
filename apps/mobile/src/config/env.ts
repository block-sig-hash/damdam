/**
 * process.env.API_BASE_URL is expected to be wired up via
 * react-native-config (or an equivalent per-environment .env setup)
 * once the rest of the app's build configuration exists — this file
 * is intentionally the single seam that changes when that happens.
 */
export const API_BASE_URL: string = process.env.API_BASE_URL ?? 'http://localhost:8000/v1';

/**
 * DamDam's own support WhatsApp number, E.164 without the leading
 * "+". docs/data-model.md's `emergency_content.support_whatsapp_number`
 * is the eventual destination-specific source of truth (US-12, not
 * yet built) — this is the same "single seam" placeholder pattern as
 * API_BASE_URL above until that endpoint exists.
 */
export const SUPPORT_WHATSAPP_NUMBER: string =
  process.env.SUPPORT_WHATSAPP_NUMBER ?? '2348000000000';
