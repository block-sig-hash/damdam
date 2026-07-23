import { cleanup, fireEvent, render, screen, waitFor } from "@/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";

import AdminDeviceCompatibilityPage from "./page";

function response(body: unknown) {
  return { ok: true, json: vi.fn().mockResolvedValue(body) };
}

const entry = {
  id: "log-1",
  device_model: "iPhone 8",
  platform: "ios",
  os_version: "15.0",
  esim_supported: false,
  checked_at: "2026-07-16T12:00:00Z",
};

describe("admin device compatibility log", () => {
  afterEach(() => {
    cleanup();
    window.localStorage.clear();
    vi.unstubAllGlobals();
  });

  it("lists device model, platform, OS version, outcome, and timestamp", async () => {
    window.localStorage.setItem("admin_access_token", "admin-token");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(response({ entries: [entry] })));

    render(<AdminDeviceCompatibilityPage />);

    expect(await screen.findByText("iPhone 8")).toBeInTheDocument();
    const row = screen.getByText("iPhone 8").closest("tr")!;
    expect(row).toHaveTextContent("ios");
    expect(row).toHaveTextContent("15.0");
    expect(row).toHaveTextContent("Incompatible");
  });

  it("shows Compatible for a supported device", async () => {
    window.localStorage.setItem("admin_access_token", "admin-token");
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValueOnce(
        response({ entries: [{ ...entry, id: "log-2", esim_supported: true, device_model: "iPhone 15" }] }),
      ),
    );

    render(<AdminDeviceCompatibilityPage />);

    expect(await screen.findByText("iPhone 15")).toBeInTheDocument();
    expect(screen.getByText("iPhone 15").closest("tr")).toHaveTextContent("Compatible");
  });

  it("shows an empty state when no entries match", async () => {
    window.localStorage.setItem("admin_access_token", "admin-token");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(response({ entries: [] })));

    render(<AdminDeviceCompatibilityPage />);

    expect(
      await screen.findByText("No device compatibility checks match these filters."),
    ).toBeInTheDocument();
  });

  it("changing the platform filter refetches with the platform query param", async () => {
    window.localStorage.setItem("admin_access_token", "admin-token");
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(response({ entries: [entry] }))
      .mockResolvedValueOnce(response({ entries: [entry] }));
    vi.stubGlobal("fetch", fetchMock);

    render(<AdminDeviceCompatibilityPage />);
    await screen.findByText("iPhone 8");

    fireEvent.change(screen.getByLabelText("Platform"), { target: { value: "ios" } });

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(fetchMock.mock.calls[1][0]).toContain("platform=ios");
  });

  it("changing the outcome filter refetches with the esim_supported query param", async () => {
    window.localStorage.setItem("admin_access_token", "admin-token");
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(response({ entries: [entry] }))
      .mockResolvedValueOnce(response({ entries: [entry] }));
    vi.stubGlobal("fetch", fetchMock);

    render(<AdminDeviceCompatibilityPage />);
    await screen.findByText("iPhone 8");

    fireEvent.change(screen.getByLabelText("Outcome"), { target: { value: "incompatible" } });

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(fetchMock.mock.calls[1][0]).toContain("esim_supported=false");
  });
});
