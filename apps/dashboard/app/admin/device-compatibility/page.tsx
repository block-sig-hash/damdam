"use client";

import { useCallback, useEffect, useState } from "react";
import {useLocale, useTranslations} from "next-intl";

import {
  DeviceCompatibilityLogEntry,
  getDeviceCompatibilityLog,
} from "@/lib/api";

type PlatformFilter = "" | "ios" | "android";
// Known gap: no "Unknown" option, so a null esim_supported row can't be
// isolated via this filter (it's still shown under "All outcomes").
// Not fixed -- compatibility_check rows always populate esim_supported
// in practice (DeviceCompatibilityCreate requires it), so the null case
// exists only in outcomeLabel() below for defensive completeness against
// the DB column's own nullability, not a real state this filter needs to
// target.
type OutcomeFilter = "" | "compatible" | "incompatible";

export default function AdminDeviceCompatibilityPage() {
  const t = useTranslations("admin");
  const locale = useLocale();
  const [entries, setEntries] = useState<DeviceCompatibilityLogEntry[]>([]);
  const [platform, setPlatform] = useState<PlatformFilter>("");
  const [outcome, setOutcome] = useState<OutcomeFilter>("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setEntries(
        await getDeviceCompatibilityLog({
          platform: platform || undefined,
          esimSupported: outcome ? outcome === "compatible" : undefined,
        }),
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("device.loadFailed"));
    } finally {
      setLoading(false);
    }
  }, [platform, outcome, t]);

  useEffect(() => {
    const timer = window.setTimeout(() => { load(); }, 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  return (
    <main className="dashboard-shell">
      <section className="manifest-card wide-card">
        <div className="page-heading">
          <div>
            <p className="eyebrow">{t("label")}</p>
            <h1>{t("device.title")}</h1>
          </div>
          <button disabled={loading} onClick={() => load()}>
            {loading ? t("refreshing") : t("refresh")}
          </button>
        </div>
        <p>{t("device.intro")}</p>
        <div className="filter-row">
          <label>
            {t("device.platform")}
            <select
              onChange={(event) => setPlatform(event.target.value as PlatformFilter)}
              value={platform}
            >
              <option value="">{t("device.allPlatforms")}</option>
              <option value="ios">iOS</option>
              <option value="android">Android</option>
            </select>
          </label>
          <label>
            {t("device.outcome")}
            <select
              onChange={(event) => setOutcome(event.target.value as OutcomeFilter)}
              value={outcome}
            >
              <option value="">{t("device.allOutcomes")}</option>
              <option value="compatible">{t("device.compatible")}</option>
              <option value="incompatible">{t("device.incompatible")}</option>
            </select>
          </label>
        </div>
        {error ? <p className="error" role="alert">{error}</p> : null}
        {loading && entries.length === 0 ? (
          <p>{t("device.loading")}</p>
        ) : entries.length === 0 ? (
          <p>{t("device.empty")}</p>
        ) : (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>{t("device.model")}</th>
                  <th>{t("device.platform")}</th>
                  <th>{t("device.os")}</th>
                  <th>{t("device.outcome")}</th>
                  <th>{t("device.checked")}</th>
                </tr>
              </thead>
              <tbody>
                {entries.map((entry) => (
                  <tr key={entry.id}>
                    <td>{entry.device_model ?? "—"}</td>
                    <td>{entry.platform ?? "—"}</td>
                    <td>{entry.os_version ?? "—"}</td>
                    <td>
                      <span
                        className={`status-badge ${
                          entry.esim_supported === false ? "status-follow-up" : ""
                        }`}
                      >
                        {entry.esim_supported === null ? t("device.unknown") : entry.esim_supported ? t("device.compatible") : t("device.incompatible")}
                      </span>
                    </td>
                    <td>
                      <time dateTime={entry.checked_at}>
                        {new Date(entry.checked_at).toLocaleString(locale)}
                      </time>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </main>
  );
}
