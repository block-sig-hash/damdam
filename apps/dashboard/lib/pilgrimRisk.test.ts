import {describe, expect, it} from "vitest";
import type {HtoPilgrim} from "./api";
import {
  hasUnresolvedSOS,
  isStaleCheckIn,
  matchesPilgrimSearch,
  sortPilgrimsByRisk,
} from "./pilgrimRisk";

const now = new Date("2026-07-16T12:00:00Z");

function pilgrim(overrides: Partial<HtoPilgrim>): HtoPilgrim {
  return {
    id: "p-1",
    name: "Amina Yusuf",
    phone_number: "+2348012345678",
    tier: "Standard",
    esim_status: "activated",
    activation_status: "activated",
    last_checkin_at: null,
    sos_status: "none",
    ...overrides,
  };
}

describe("isStaleCheckIn", () => {
  it("AC-18.3: no check-in at all counts as stale", () => {
    expect(isStaleCheckIn(null, now)).toBe(true);
  });

  it("is not stale at exactly 23h59m", () => {
    expect(isStaleCheckIn("2026-07-15T12:01:00Z", now)).toBe(false);
  });

  it("is stale at exactly 24h01m", () => {
    expect(isStaleCheckIn("2026-07-15T11:59:00Z", now)).toBe(true);
  });
});

describe("hasUnresolvedSOS", () => {
  it("is true only for sos_status active", () => {
    expect(hasUnresolvedSOS(pilgrim({sos_status: "active"}))).toBe(true);
    expect(hasUnresolvedSOS(pilgrim({sos_status: "none"}))).toBe(false);
  });
});

describe("sortPilgrimsByRisk", () => {
  it("AC-18.1: unresolved SOS first, then stale check-ins, then alphabetical", () => {
    const zainab = pilgrim({
      id: "p-zainab",
      name: "Zainab Bello",
      last_checkin_at: "2026-07-16T11:00:00Z", // fresh
      sos_status: "none",
    });
    const bello = pilgrim({
      id: "p-bello",
      name: "Bello Aliyu",
      last_checkin_at: null, // stale
      sos_status: "none",
    });
    const chidi = pilgrim({
      id: "p-chidi",
      name: "Chidi Okoro",
      last_checkin_at: "2026-07-01T00:00:00Z", // stale
      sos_status: "none",
    });
    const amina = pilgrim({
      id: "p-amina",
      name: "Amina Yusuf",
      last_checkin_at: "2026-07-16T11:00:00Z", // fresh, but has SOS
      sos_status: "active",
    });

    const sorted = sortPilgrimsByRisk([zainab, bello, chidi, amina], now);

    expect(sorted.map((p) => p.name)).toEqual([
      "Amina Yusuf", // unresolved SOS, always first regardless of check-in freshness
      "Bello Aliyu", // stale, alphabetically before Chidi
      "Chidi Okoro", // stale
      "Zainab Bello", // fresh, last
    ]);
  });

  it("does not mutate the input array", () => {
    const list = [pilgrim({name: "Zed"}), pilgrim({name: "Abe"})];
    const original = [...list];

    sortPilgrimsByRisk(list, now);

    expect(list).toEqual(original);
  });

  it("multiple unresolved SOS pilgrims are sorted alphabetically within that tier", () => {
    const sorted = sortPilgrimsByRisk(
      [
        pilgrim({name: "Zainab Bello", sos_status: "active"}),
        pilgrim({name: "Amina Yusuf", sos_status: "active"}),
      ],
      now,
    );
    expect(sorted.map((p) => p.name)).toEqual(["Amina Yusuf", "Zainab Bello"]);
  });
});

describe("matchesPilgrimSearch", () => {
  it("AC-18.7: matches by name, case-insensitive substring", () => {
    expect(matchesPilgrimSearch(pilgrim({name: "Amina Yusuf"}), "amina")).toBe(true);
    expect(matchesPilgrimSearch(pilgrim({name: "Amina Yusuf"}), "YUSUF")).toBe(true);
    expect(matchesPilgrimSearch(pilgrim({name: "Amina Yusuf"}), "bello")).toBe(false);
  });

  it("matches by phone number substring", () => {
    expect(
      matchesPilgrimSearch(pilgrim({phone_number: "+2348012345678"}), "8012345"),
    ).toBe(true);
  });

  it("an empty query matches everything", () => {
    expect(matchesPilgrimSearch(pilgrim({}), "")).toBe(true);
    expect(matchesPilgrimSearch(pilgrim({}), "   ")).toBe(true);
  });
});
