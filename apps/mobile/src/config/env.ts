/**
 * process.env.API_BASE_URL is expected to be wired up via
 * react-native-config (or an equivalent per-environment .env setup)
 * once the rest of the app's build configuration exists — this file
 * is intentionally the single seam that changes when that happens.
 */
export const API_BASE_URL: string = process.env.API_BASE_URL ?? 'http://localhost:8000/v1';

/**
 * DamDam's own support WhatsApp number, E.164 without the leading
 * "+". This constant *is* the source of truth (US-12 AC-12.3 bundles
 * it client-side rather than serving it from an endpoint or table —
 * see data-model.md §6.20, which supersedes an earlier, never-built
 * `emergency_content` table design). Still env-overridable per the
 * same "single seam" pattern as API_BASE_URL above, for per-build
 * config rather than a runtime fetch.
 */
export const SUPPORT_WHATSAPP_NUMBER: string =
  process.env.SUPPORT_WHATSAPP_NUMBER ?? '2348000000000';
