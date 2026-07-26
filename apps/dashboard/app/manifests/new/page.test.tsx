import { cleanup, fireEvent, render, screen, waitFor } from "@/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";

import ManifestUploadPage from "./page";

function apiResponse(body: unknown, ok = true) {
  return { ok, json: vi.fn().mockResolvedValue(body) };
}

describe("HTO manifest upload", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    window.localStorage.clear();
  });

  it("AC-05.5–05.7 previews issues and confirms valid rows", async () => {
    window.localStorage.setItem("hto_access_token", "operator-token");
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(apiResponse({ manifest_id: "manifest-1", status: "draft" }))
      .mockResolvedValueOnce(apiResponse({
        total_rows: 3,
        valid_rows: 2,
        invalid_rows: [{ row_number: 3, reason: "phone_number must be Nigerian" }],
        preview: [
          {
            id: "row-1",
            row_number: 2,
            first_name: "Aisha",
            last_name: "Bello",
            phone_number: "+2348012345678",
            passport_number: null,
            seat_number: "14A",
            validation_status: "duplicate_warning",
            warning: "Duplicate phone number in this manifest",
          },
          {
            id: "row-2",
            row_number: 4,
            first_name: "Hauwa",
            last_name: "Sani",
            phone_number: "+2349012345678",
            passport_number: "A123",
            seat_number: null,
            validation_status: "valid",
            warning: null,
          },
        ],
      }))
      .mockResolvedValueOnce(apiResponse({ status: "validated", pilgrim_count: 2 }));
    vi.stubGlobal("fetch", fetchMock);
    render(<ManifestUploadPage />);

    fireEvent.change(screen.getByLabelText(/Manifest name/), {
      target: { value: "Flight NAF203" },
    });
    const file = new File(
      ["first_name,last_name,phone_number\nAisha,Bello,08012345678\n"],
      "pilgrims.csv",
      { type: "text/csv" },
    );
    fireEvent.change(screen.getByLabelText(/^CSV file/), {
      target: { files: [file] },
    });
    fireEvent.submit(screen.getByRole("button", { name: "Upload" }).closest("form")!);

    expect(await screen.findByText("Review before confirming")).toBeInTheDocument();
    expect(screen.getByText(/Row 3/).closest("li")).toHaveClass("hard-error");
    expect(screen.getByText(/Row 2/).closest("li")).toHaveClass("warning");
    expect(screen.getByText("2 valid")).toBeInTheDocument();

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "http://localhost:8000/v1/hto/manifests",
      expect.objectContaining({ method: "POST" }),
    );
    const uploadRequest = fetchMock.mock.calls[1][1] as RequestInit;
    expect(uploadRequest.body).toBeInstanceOf(FormData);
    expect((uploadRequest.headers as Record<string, string>).Authorization).toBe(
      "Bearer operator-token",
    );

    fireEvent.click(screen.getByRole("button", { name: "Confirm and proceed" }));
    expect(await screen.findByText("2 pilgrims accepted")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /Continue to grouping/ }),
    ).toHaveAttribute("href", "/manifests/manifest-1/order");
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
  });

  it("shows file-level validation failures separately from row issues", async () => {
    window.localStorage.setItem("hto_access_token", "operator-token");
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(apiResponse({ manifest_id: "manifest-1" }))
      .mockResolvedValueOnce(
        apiResponse({ message: "The CSV must include required columns." }, false),
      );
    vi.stubGlobal("fetch", fetchMock);
    render(<ManifestUploadPage />);

    const file = new File(["name\nAisha\n"], "pilgrims.csv", { type: "text/csv" });
    fireEvent.change(screen.getByLabelText(/^CSV file/), {
      target: { files: [file] },
    });
    fireEvent.submit(screen.getByRole("button", { name: "Upload" }).closest("form")!);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The CSV must include required columns.",
    );
    expect(screen.queryByText("Review before confirming")).not.toBeInTheDocument();
  });
});
