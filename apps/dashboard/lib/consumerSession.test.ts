import { beforeEach, describe, expect, it } from "vitest";

import {
  clearConsumerSession,
  readOrCreateCallingDeviceId,
} from "./consumerSession";

describe("browser calling device identity", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("is stable for the browser and is not the signed-in user id", () => {
    const first = readOrCreateCallingDeviceId();
    const second = readOrCreateCallingDeviceId();

    expect(first).toMatch(/^web-/);
    expect(second).toBe(first);
    expect(first).not.toBe("user-1");
  });

  it("survives account sign-out so one browser remains one revocation target", () => {
    const beforeSignOut = readOrCreateCallingDeviceId();

    clearConsumerSession();

    expect(readOrCreateCallingDeviceId()).toBe(beforeSignOut);
  });
});
