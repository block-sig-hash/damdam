import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { VerifyEmailResult } from "./page";

describe("email verification landing", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("AC-04.3/04.4 explains the pending approval state", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true }));
    render(<VerifyEmailResult token="signed-token" />);

    expect(
      await screen.findByText(
        "Email verified. Your account is pending DamDam admin approval.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText(/less than 24 hours/i)).toBeInTheDocument();
  });
});
