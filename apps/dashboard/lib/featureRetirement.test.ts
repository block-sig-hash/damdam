import {existsSync, readFileSync} from "node:fs";
import {join} from "node:path";

import {describe, expect, it} from "vitest";

const dashboardRoot = join(__dirname, "..");

describe("retired safety surface", () => {
  it("ships no SOS service worker or Firebase dependency", () => {
    expect(existsSync(join(dashboardRoot, "public", "firebase-messaging-sw.js"))).toBe(false);
    const packageJson = JSON.parse(
      readFileSync(join(dashboardRoot, "package.json"), "utf8"),
    ) as {dependencies: Record<string, string>};
    expect(packageJson.dependencies.firebase).toBeUndefined();
  });

  it.each(["en", "fr"])("does not advertise welfare features in %s", locale => {
    const messages = readFileSync(
      join(dashboardRoot, "messages", `${locale}.json`),
      "utf8",
    );
    expect(messages).not.toMatch(/check[_ -]?in|sos|pointage/i);
  });
});
