import { cleanup, fireEvent, render, screen } from "@/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";

import ManifestDetailPage from "./page";

vi.mock("next/navigation", () => ({ useParams: () => ({ id: "manifest-1" }) }));

function response(body: unknown) {
  return { ok: true, json: vi.fn().mockResolvedValue(body) };
}

describe("HTO manifest pilgrim roster", () => {
  afterEach(() => {
    cleanup();
    window.localStorage.clear();
    vi.unstubAllGlobals();
  });

  it("AC-10.7: flags an eSIM-incompatible pilgrim with a Follow up label", async () => {
    window.localStorage.setItem("hto_access_token", "hto-token");
    const fetchMock = vi.fn().mockResolvedValueOnce(
      response({
        pilgrims: [
          {
            id: "p1",
            name: "Amina Yusuf",
            phone_number: "+2348012345678",
            tier: "Standard",
            esim_status: "incompatible",
            activation_status: "activated",
            last_checkin_at: null,
            sos_status: "none",
          },
          {
            id: "p2",
            name: "Bello Aliyu",
            phone_number: "+2348087654321",
            tier: null,
            esim_status: "downloaded",
            activation_status: "activated",
            last_checkin_at: null,
            sos_status: "none",
          },
        ],
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    render(<ManifestDetailPage />);

    expect(await screen.findByText("Amina Yusuf")).toBeInTheDocument();
    expect(fetchMock.mock.calls[0][0]).toContain("/hto/pilgrims");
    expect(fetchMock.mock.calls[0][0]).toContain("manifest_id=manifest-1");

    const aminaRow = screen.getByText("Amina Yusuf").closest("tr");
    expect(aminaRow).not.toBeNull();
    expect(aminaRow!.querySelector(".status-follow-up")).toHaveTextContent("Follow up");
    expect(aminaRow!.querySelector(".status-follow-up")).toBeInTheDocument();

    const belloRow = screen.getByText("Bello Aliyu").closest("tr");
    expect(belloRow!.querySelector(".status-follow-up")).toBeNull();
    expect(belloRow).toHaveTextContent("Downloaded");
  });

  it("shows an empty state when the manifest has no pilgrims", async () => {
    window.localStorage.setItem("hto_access_token", "hto-token");
    const fetchMock = vi.fn().mockResolvedValueOnce(response({ pilgrims: [] }));
    vi.stubGlobal("fetch", fetchMock);

    render(<ManifestDetailPage />);

    expect(await screen.findByText("No pilgrims on this manifest yet.")).toBeInTheDocument();
  });

  const riskyPilgrims = {
    pilgrims: [
      {
        id: "p-zainab",
        name: "Zainab Bello",
        phone_number: "+2348011110000",
        tier: "Standard",
        esim_status: "activated",
        activation_status: "activated",
        last_checkin_at: new Date().toISOString(), // fresh
        sos_status: "none",
      },
      {
        id: "p-bello",
        name: "Bello Aliyu",
        phone_number: "+2348022220000",
        tier: "Standard",
        esim_status: "activated",
        activation_status: "activated",
        last_checkin_at: null, // stale: never checked in
        sos_status: "none",
      },
      {
        id: "p-amina",
        name: "Amina Yusuf",
        phone_number: "+2348033330000",
        tier: "Standard",
        esim_status: "activated",
        activation_status: "activated",
        last_checkin_at: new Date().toISOString(), // fresh, but has SOS
        sos_status: "active",
      },
    ],
  };

  it("AC-18.1/18.3/18.4: risk-sorts rows and highlights SOS red, stale amber", async () => {
    window.localStorage.setItem("hto_access_token", "hto-token");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(response(riskyPilgrims)));

    render(<ManifestDetailPage />);
    await screen.findByText("Amina Yusuf");

    const rows = screen.getAllByRole("row").slice(1); // drop the header row
    const names = rows.map((row) => row.textContent);
    expect(names[0]).toContain("Amina Yusuf"); // unresolved SOS: always first
    expect(names[1]).toContain("Bello Aliyu"); // stale: second
    expect(names[2]).toContain("Zainab Bello"); // fresh: last

    expect(rows[0]).toHaveClass("row-sos");
    expect(rows[1]).toHaveClass("row-stale");
    expect(rows[2]).not.toHaveClass("row-sos");
    expect(rows[2]).not.toHaveClass("row-stale");

    expect(screen.getByText("1 unresolved SOS alert on this manifest")).toBeInTheDocument();
  });

  it("AC-18.7: search filters by name or phone without a new request", async () => {
    window.localStorage.setItem("hto_access_token", "hto-token");
    const fetchMock = vi.fn().mockResolvedValueOnce(response(riskyPilgrims));
    vi.stubGlobal("fetch", fetchMock);

    render(<ManifestDetailPage />);
    await screen.findByText("Amina Yusuf");

    fireEvent.change(screen.getByLabelText("Search pilgrims by name or phone"), {
      target: { value: "zainab" },
    });

    expect(screen.queryByText("Amina Yusuf")).not.toBeInTheDocument();
    expect(screen.queryByText("Bello Aliyu")).not.toBeInTheDocument();
    expect(screen.getByText("Zainab Bello")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1); // filtering is client-side, no refetch

    fireEvent.change(screen.getByLabelText("Search pilgrims by name or phone"), {
      target: { value: "+2348033330000" },
    });
    expect(screen.getByText("Amina Yusuf")).toBeInTheDocument();
    expect(screen.queryByText("Zainab Bello")).not.toBeInTheDocument();
  });

  it("AC-18.5: auto-refreshes every 60 seconds and the manual button also refetches", async () => {
    vi.useFakeTimers();
    window.localStorage.setItem("hto_access_token", "hto-token");
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(response({ pilgrims: [] }))
      .mockResolvedValueOnce(response({ pilgrims: [] }))
      .mockResolvedValueOnce(response({ pilgrims: [] }));
    vi.stubGlobal("fetch", fetchMock);

    render(<ManifestDetailPage />);
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));

    await vi.advanceTimersByTimeAsync(60_000);
    expect(fetchMock).toHaveBeenCalledTimes(2);

    fireEvent.click(screen.getByRole("button", { name: /refresh/i }));
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));

    vi.useRealTimers();
  });
});
