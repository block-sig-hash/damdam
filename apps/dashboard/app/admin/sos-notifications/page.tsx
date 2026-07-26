"use client";

import { useCallback, useEffect, useState } from "react";
import {useLocale, useTranslations} from "next-intl";

import {
  FailedSOSNotification,
  getFailedSOSNotifications,
  retrySOSNotification,
  retrySOSNotificationsBulk,
} from "@/lib/api";

export default function AdminFailedNotificationsPage() {
  const t = useTranslations("admin");
  const locale = useLocale();
  const [notifications, setNotifications] = useState<FailedSOSNotification[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [retrying, setRetrying] = useState<string[]>([]);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const rows = await getFailedSOSNotifications();
      setNotifications(rows);
      setSelected((current) => current.filter((id) => rows.some((row) => row.id === id)));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("notifications.loadFailed"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    const timer = window.setTimeout(() => { load(); }, 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  function toggleSelected(id: string) {
    setSelected((current) =>
      current.includes(id) ? current.filter((item) => item !== id) : [...current, id],
    );
  }

  async function retryOne(id: string) {
    setError("");
    setRetrying((current) => [...current, id]);
    try {
      await retrySOSNotification(id);
      // Refetch rather than optimistically removing the row -- this is
      // the actual resulting state (the row disappears only once the
      // backend has really cleared admin_queued_at/reset status), not an
      // assumption that the retry succeeded.
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("notifications.retryFailed"));
    } finally {
      setRetrying((current) => current.filter((item) => item !== id));
    }
  }

  async function retrySelected() {
    if (selected.length === 0) return;
    setError("");
    setRetrying((current) => [...current, ...selected]);
    try {
      await retrySOSNotificationsBulk(selected);
      setSelected([]);
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("notifications.bulkFailed"));
    } finally {
      setRetrying([]);
    }
  }

  return (
    <main className="dashboard-shell">
      <section className="manifest-card wide-card">
        <div className="page-heading">
          <div>
            <p className="eyebrow">{t("label")}</p>
            <h1>{t("notifications.title")}</h1>
          </div>
          <button disabled={loading} onClick={() => load()}>
            {loading ? t("refreshing") : t("refresh")}
          </button>
        </div>
        <p>{t("notifications.intro")}</p>
        {error ? <p className="error" role="alert">{error}</p> : null}
        {loading && notifications.length === 0 ? (
          <p>{t("notifications.loading")}</p>
        ) : notifications.length === 0 ? (
          <p>{t("notifications.empty")}</p>
        ) : (
          <>
            <div className="action-row">
              <button
                disabled={selected.length === 0 || retrying.length > 0}
                onClick={retrySelected}
                type="button"
              >
                {retrying.length > 0 && selected.length > 0
                  ? t("notifications.retrying")
                  : t("notifications.retrySelected", {count: selected.length})}
              </button>
            </div>
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th aria-label={t("notifications.select")} />
                    <th>{t("notifications.pilgrim")}</th>
                    <th>{t("notifications.channel")}</th>
                    <th>{t("notifications.failure")}</th>
                    <th>{t("notifications.timestamp")}</th>
                    <th>{t("notifications.retryCount")}</th>
                    <th aria-label={t("notifications.actions")} />
                  </tr>
                </thead>
                <tbody>
                  {notifications.map((notification) => (
                    <tr key={notification.id}>
                      <td>
                        <input
                          aria-label={t("notifications.selectAria", {name: notification.pilgrim_name, channel: notification.channel})}
                          checked={selected.includes(notification.id)}
                          onChange={() => toggleSelected(notification.id)}
                          type="checkbox"
                        />
                      </td>
                      <td>{notification.pilgrim_name}</td>
                      <td>{notification.channel}</td>
                      <td>{notification.failure_reason ?? "—"}</td>
                      <td>
                        <time dateTime={notification.sos_timestamp}>
                          {new Date(notification.sos_timestamp).toLocaleString(locale)}
                        </time>
                      </td>
                      <td>{notification.retry_count}</td>
                      <td>
                        <button
                          disabled={retrying.includes(notification.id)}
                          onClick={() => retryOne(notification.id)}
                          type="button"
                        >
                          {retrying.includes(notification.id) ? t("notifications.retrying") : t("notifications.retry")}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </section>
    </main>
  );
}
