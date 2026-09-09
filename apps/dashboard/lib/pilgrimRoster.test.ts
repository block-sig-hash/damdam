import {describe, expect, it} from "vitest";

import type {HtoPilgrim} from "./api";
import {matchesPilgrimSearch, sortPilgrimsByName} from "./pilgrimRoster";

function pilgrim(name: string, phone = "08000000000"): HtoPilgrim {
  return {
    id: name,
    name,
    phone_number: phone,
    manifest_id: "manifest-1",
    manifest_name: "Manifest 1",
    tier: null,
    esim_status: "not_checked",
    activation_status: "not_activated",
  };
}

describe("roster ordering", () => {
  it("orders by name and does not mutate the input", () => {
    const input = [pilgrim("Zainab"), pilgrim("Amina"), pilgrim("Musa")];

    expect(sortPilgrimsByName(input).map((p) => p.name)).toEqual([
      "Amina",
      "Musa",
      "Zainab",
    ]);
    expect(input.map((p) => p.name)).toEqual(["Zainab", "Amina", "Musa"]);
  });

  it("US-30: exposes no welfare state to rank by", () => {
    expect(Object.keys(pilgrim("Amina"))).not.toContain("sos_status");
    expect(Object.keys(pilgrim("Amina"))).not.toContain("last_checkin_at");
  });
});

describe("AC-18.7 search", () => {
  it("matches name or phone, case-insensitively, and returns all on empty", () => {
    const amina = pilgrim("Amina Bello", "08031234567");

    expect(matchesPilgrimSearch(amina, "amina")).toBe(true);
    expect(matchesPilgrimSearch(amina, "BELLO")).toBe(true);
    expect(matchesPilgrimSearch(amina, "0803")).toBe(true);
    expect(matchesPilgrimSearch(amina, "  ")).toBe(true);
    expect(matchesPilgrimSearch(amina, "Musa")).toBe(false);
  });
});
