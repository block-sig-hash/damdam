import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import RegistrationPage from "./page";

describe("HTO registration", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("AC-04.1 submits every required operator field", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true });
    vi.stubGlobal("fetch", fetchMock);
    render(<RegistrationPage />);

    fireEvent.change(screen.getByLabelText("Business name"), {
      target: { value: "Barakah Hajj Services" },
    });
    fireEvent.change(screen.getByLabelText("Operator name"), {
      target: { value: "Amina Yusuf" },
    });
    fireEvent.change(screen.getByLabelText("Email address"), {
      target: { value: "amina@example.com" },
    });
    fireEvent.change(screen.getByLabelText("Nigerian phone number"), {
      target: { value: "08012345678" },
    });
    fireEvent.change(screen.getByLabelText("NAHCON licence number"), {
      target: { value: "NAHCON-123" },
    });
    fireEvent.change(screen.getByLabelText(/^Password/), {
      target: { value: "secure-password" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create account" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledOnce());
    const request = fetchMock.mock.calls[0][1] as RequestInit;
    expect(JSON.parse(String(request.body))).toEqual({
      business_name: "Barakah Hajj Services",
      operator_name: "Amina Yusuf",
      email: "amina@example.com",
      phone_number: "08012345678",
      nahcon_licence_number: "NAHCON-123",
      password: "secure-password",
    });
    expect(await screen.findByText("Check your email")).toBeInTheDocument();
  });
});
