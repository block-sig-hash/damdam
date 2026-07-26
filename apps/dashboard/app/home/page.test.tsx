import { cleanup, fireEvent, render, screen } from "@/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";

import HTOHomePage from "./page";

function response(body: unknown) {
  return { ok: true, json: vi.fn().mockResolvedValue(body) };
}

const manifests = {
  manifests: [
    { id: "manifest-a", name: "Flight NAF203", status: "provisioned", valid_rows: 2, created_at: "2026-07-01T00:00:00Z" },
    { id: "manifest-b", name: "Flight NAF900", status: "provisioned", valid_rows: 1, created_at: "2026-07-02T00:00:00Z" },
  ],
};

const crossManifestPilgrims = {
  pilgrims: [
    {
      id: "p-amina",
      name: "Amina Yusuf",
      phone_number: "+2348011110000",
      manifest_id: "manifest-a",
      manifest_name: "Flight NAF203",
      tier: "Standard",
      esim_status: "activated",
      activation_status: "activated",
      last_checkin_at: null,
      sos_status: "active",
    },
    {
      id: "p-bello",
      name: "Bello Aliyu",
      phone_number: "+2348022220000",
      manifest_id: "manifest-b",
      manifest_name: "Flight NAF900",
      tier: null,
      esim_status: "not_checked",
      activation_status: "not_activated",
      last_checkin_at: null,
      sos_status: "none",
    },
  ],
};

describe("HTO Home cross-manifest roster", () => {
  afterEach(() => {
    cleanup();
    window.localStorage.clear();
    vi.unstubAllGlobals();
  });

  it("aggregates pilgrims across manifests and shows which manifest each belongs to", async () => {
    window.localStorage.setItem("hto_access_token", "hto-token");
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(response(crossManifestPilgrims))
      .mockResolvedValueOnce(response(manifests));
    vi.stubGlobal("fetch", fetchMock);

    render(<HTOHomePage />);

    expect(await screen.findByText("Amina Yusuf")).toBeInTheDocument();
    expect(screen.getByText("Bello Aliyu")).toBeInTheDocument();
    // The pilgrims fetch has no manifest_id filter -- cross-manifest, not
    // scoped to one manifest the way /manifests/[id] is.
    expect(fetchMock.mock.calls[0][0]).toContain("/hto/pilgrims");
    expect(fetchMock.mock.calls[0][0]).not.toContain("manifest_id");

    const aminaRow = screen.getByText("Amina Yusuf").closest("tr")!;
    expect(aminaRow).toHaveTextContent("Flight NAF203");
    const belloRow = screen.getByText("Bello Aliyu").closest("tr")!;
    expect(belloRow).toHaveTextContent("Flight NAF900");
  });

  it("risk-sorts across manifests: unresolved SOS first regardless of which manifest", async () => {
    window.localStorage.setItem("hto_access_token", "hto-token");
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(response(crossManifestPilgrims))
        .mockResolvedValueOnce(response(manifests)),
    );

    render(<HTOHomePage />);
    await screen.findByText("Amina Yusuf");

    const rows = screen.getAllByRole("row").slice(1);
    expect(rows[0]).toHaveTextContent("Amina Yusuf");
    expect(rows[0]).toHaveClass("row-sos");
    expect(screen.getByText("1 unresolved SOS alert")).toBeInTheDocument();
  });

  it("the manifest filter dropdown narrows the table client-side, without a new request", async () => {
    window.localStorage.setItem("hto_access_token", "hto-token");
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(response(crossManifestPilgrims))
      .mockResolvedValueOnce(response(manifests));
    vi.stubGlobal("fetch", fetchMock);

    render(<HTOHomePage />);
    await screen.findByText("Amina Yusuf");

    fireEvent.change(screen.getByLabelText("Manifest"), { target: { value: "manifest-b" } });

    expect(screen.queryByText("Amina Yusuf")).not.toBeInTheDocument();
    expect(screen.getByText("Bello Aliyu")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2); // no additional fetch on filter change
  });

  it("search filters across all manifests without a new request", async () => {
    window.localStorage.setItem("hto_access_token", "hto-token");
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(response(crossManifestPilgrims))
      .mockResolvedValueOnce(response(manifests));
    vi.stubGlobal("fetch", fetchMock);

    render(<HTOHomePage />);
    await screen.findByText("Amina Yusuf");

    fireEvent.change(screen.getByLabelText("Search pilgrims by name or phone"), {
      target: { value: "bello" },
    });

    expect(screen.queryByText("Amina Yusuf")).not.toBeInTheDocument();
    expect(screen.getByText("Bello Aliyu")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("shows a create-first-manifest CTA when the organization has no manifests yet", async () => {
    window.localStorage.setItem("hto_access_token", "hto-token");
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(response({ pilgrims: [] }))
        .mockResolvedValueOnce(response({ manifests: [] })),
    );

    render(<HTOHomePage />);

    expect(await screen.findByText("Create your first manifest")).toBeInTheDocument();
    expect(screen.getByText("Create your first manifest")).toHaveAttribute(
      "href",
      "/manifests/new",
    );
  });

  it("shows a distinct empty state when manifests exist but have no pilgrims yet", async () => {
    window.localStorage.setItem("hto_access_token", "hto-token");
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(response({ pilgrims: [] }))
        .mockResolvedValueOnce(response(manifests)),
    );

    render(<HTOHomePage />);

    expect(await screen.findByText("No pilgrims across your manifests yet.")).toBeInTheDocument();
  });

  it("auto-refreshes every 60 seconds and the manual button also refetches", async () => {
    vi.useFakeTimers();
    window.localStorage.setItem("hto_access_token", "hto-token");
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(response({ pilgrims: [] }))
      .mockResolvedValueOnce(response({ manifests: [] }))
      .mockResolvedValueOnce(response({ pilgrims: [] }))
      .mockResolvedValueOnce(response({ manifests: [] }))
      .mockResolvedValueOnce(response({ pilgrims: [] }))
      .mockResolvedValueOnce(response({ manifests: [] }));
    vi.stubGlobal("fetch", fetchMock);

    render(<HTOHomePage />);
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));

    await vi.advanceTimersByTimeAsync(60_000);
    expect(fetchMock).toHaveBeenCalledTimes(4);

    fireEvent.click(screen.getByRole("button", { name: /refresh/i }));
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(6));

    vi.useRealTimers();
  });
});
