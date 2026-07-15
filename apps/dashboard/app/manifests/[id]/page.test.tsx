import { cleanup, render, screen } from "@testing-library/react";
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
            esim_status: "not_checked",
            activation_status: "not_activated",
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
  });

  it("shows an empty state when the manifest has no pilgrims", async () => {
    window.localStorage.setItem("hto_access_token", "hto-token");
    const fetchMock = vi.fn().mockResolvedValueOnce(response({ pilgrims: [] }));
    vi.stubGlobal("fetch", fetchMock);

    render(<ManifestDetailPage />);

    expect(await screen.findByText("No pilgrims on this manifest yet.")).toBeInTheDocument();
  });
});
