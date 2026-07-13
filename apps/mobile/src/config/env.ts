/**
 * process.env.API_BASE_URL is expected to be wired up via
 * react-native-config (or an equivalent per-environment .env setup)
 * once the rest of the app's build configuration exists — this file
 * is intentionally the single seam that changes when that happens.
 */
export const API_BASE_URL: string = process.env.API_BASE_URL ?? 'http://localhost:8000/v1';
