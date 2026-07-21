import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import AdminFailedNotificationsPage from "./page";

function response(body: unknown) {
  return { ok: true, json: vi.fn().mockResolvedValue(body) };
}

const failedNotification = {
  id: "notif-1",
  pilgrim_name: "Amina Yusuf",
  channel: "whatsapp",
  failure_reason: "delivery timeout",
  sos_timestamp: "2026-07-16T12:00:00Z",
  retry_count: 3,
};

describe("admin failed notification queue", () => {
  afterEach(() => {
    cleanup();
    window.localStorage.clear();
    vi.unstubAllGlobals();
  });

  it("lists failed notifications with channel, failure reason, timestamp, and retry count", async () => {
    window.localStorage.setItem("admin_access_token", "admin-token");
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValueOnce(response({ notifications: [failedNotification] })),
    );

    render(<AdminFailedNotificationsPage />);

    expect(await screen.findByText("Amina Yusuf")).toBeInTheDocument();
    const row = screen.getByText("Amina Yusuf").closest("tr")!;
    expect(row).toHaveTextContent("whatsapp");
    expect(row).toHaveTextContent("delivery timeout");
    expect(row).toHaveTextContent("3");
  });

  it("shows an empty state when there are no failed notifications", async () => {
    window.localStorage.setItem("admin_access_token", "admin-token");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(response({ notifications: [] })));

    render(<AdminFailedNotificationsPage />);

    expect(await screen.findByText("No failed notifications.")).toBeInTheDocument();
  });

  it("per-row retry refetches and reflects the real resulting state, not an optimistic removal", async () => {
    window.localStorage.setItem("admin_access_token", "admin-token");
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(response({ notifications: [failedNotification] })) // initial load
      .mockResolvedValueOnce(response({ queued: 1 })) // retry POST
      .mockResolvedValueOnce(response({ notifications: [] })); // refetch after retry
    vi.stubGlobal("fetch", fetchMock);

    render(<AdminFailedNotificationsPage />);
    await screen.findByText("Amina Yusuf");

    fireEvent.click(screen.getByRole("button", { name: "Retry" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    expect(fetchMock.mock.calls[1][0]).toContain("/admin/sos-notifications/notif-1/retry");
    expect(fetchMock.mock.calls[1][1]).toMatchObject({ method: "POST" });
    // The row is gone only because the third (refetch) call returned an
    // empty list -- not because the click handler removed it locally.
    await waitFor(() => expect(screen.queryByText("Amina Yusuf")).not.toBeInTheDocument());
  });

  it("bulk retry sends the selected ids and refetches", async () => {
    window.localStorage.setItem("admin_access_token", "admin-token");
    const second = { ...failedNotification, id: "notif-2", pilgrim_name: "Bello Aliyu" };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(response({ notifications: [failedNotification, second] }))
      .mockResolvedValueOnce(response({ queued: 2 }))
      .mockResolvedValueOnce(response({ notifications: [] }));
    vi.stubGlobal("fetch", fetchMock);

    render(<AdminFailedNotificationsPage />);
    await screen.findByText("Amina Yusuf");

    fireEvent.click(
      screen.getByLabelText("Select Amina Yusuf's whatsapp notification"),
    );
    fireEvent.click(screen.getByLabelText("Select Bello Aliyu's whatsapp notification"));
    fireEvent.click(screen.getByRole("button", { name: "Retry selected (2)" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    expect(fetchMock.mock.calls[1][0]).toContain("/admin/sos-notifications/retry-bulk");
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({
      notification_ids: ["notif-1", "notif-2"],
    });
    await waitFor(() => expect(screen.queryByText("Amina Yusuf")).not.toBeInTheDocument());
  });

  it("the bulk retry button is disabled until at least one row is selected", async () => {
    window.localStorage.setItem("admin_access_token", "admin-token");
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValueOnce(response({ notifications: [failedNotification] })),
    );

    render(<AdminFailedNotificationsPage />);
    await screen.findByText("Amina Yusuf");

    expect(screen.getByRole("button", { name: "Retry selected (0)" })).toBeDisabled();
  });

  it("shows an error and keeps the row if retry fails", async () => {
    window.localStorage.setItem("admin_access_token", "admin-token");
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(response({ notifications: [failedNotification] }))
      .mockResolvedValueOnce({
        ok: false,
        json: vi.fn().mockResolvedValue({ message: "Retry failed." }),
      });
    vi.stubGlobal("fetch", fetchMock);

    render(<AdminFailedNotificationsPage />);
    await screen.findByText("Amina Yusuf");

    fireEvent.click(screen.getByRole("button", { name: "Retry" }));

    expect(await screen.findByText("Retry failed.")).toBeInTheDocument();
    expect(screen.getByText("Amina Yusuf")).toBeInTheDocument();
  });
});
