import type {HtoPilgrim} from "./api";

/**
 * Roster ordering and search.
 *
 * This replaces `pilgrimRisk.ts`, which ranked people by welfare state --
 * unresolved SOS first, then a stale check-in. US-30 retires that tracking, and
 * the ordering was the last place it survived after the screens came out. What
 * is left is the name ordering the old sort fell through to on a tie.
 */

export function sortPilgrimsByName(pilgrims: HtoPilgrim[]): HtoPilgrim[] {
  return [...pilgrims].sort((a, b) => a.name.localeCompare(b.name));
}

/** AC-18.7: search by name or phone, case-insensitive, substring match. */
export function matchesPilgrimSearch(pilgrim: HtoPilgrim, query: string): boolean {
  const normalized = query.trim().toLowerCase();
  if (!normalized) return true;
  return (
    pilgrim.name.toLowerCase().includes(normalized) ||
    pilgrim.phone_number.toLowerCase().includes(normalized)
  );
}
