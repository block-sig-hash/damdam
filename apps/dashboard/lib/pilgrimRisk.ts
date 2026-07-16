import type {HtoPilgrim} from "./api";

const STALE_CHECKIN_MS = 24 * 60 * 60 * 1000;

/** AC-18.3: no check-in ever recorded counts as stale too, not just an old one. */
export function isStaleCheckIn(lastCheckinAt: string | null, now: Date): boolean {
  if (!lastCheckinAt) return true;
  return now.getTime() - new Date(lastCheckinAt).getTime() > STALE_CHECKIN_MS;
}

export function hasUnresolvedSOS(pilgrim: HtoPilgrim): boolean {
  return pilgrim.sos_status === "active";
}

/**
 * AC-18.1: unresolved SOS first, then stale check-ins, then alphabetical.
 * Each tier falls through to the next on a tie, so two pilgrims who are
 * both/neither in SOS and both/neither stale end up ordered by name.
 */
export function sortPilgrimsByRisk(pilgrims: HtoPilgrim[], now: Date): HtoPilgrim[] {
  return [...pilgrims].sort((a, b) => {
    const sosRank = Number(!hasUnresolvedSOS(a)) - Number(!hasUnresolvedSOS(b));
    if (sosRank !== 0) return sosRank;
    const staleRank =
      Number(!isStaleCheckIn(a.last_checkin_at, now)) -
      Number(!isStaleCheckIn(b.last_checkin_at, now));
    if (staleRank !== 0) return staleRank;
    return a.name.localeCompare(b.name);
  });
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
