"use client";

import { useCallback, useEffect, useState } from "react";

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

function outcomeLabel(esimSupported: boolean | null): string {
  if (esimSupported === null) return "Unknown";
  return esimSupported ? "Compatible" : "Incompatible";
}

export default function AdminDeviceCompatibilityPage() {
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
      setError(caught instanceof Error ? caught.message : "Could not load the compatibility log.");
    } finally {
      setLoading(false);
    }
  }, [platform, outcome]);

  useEffect(() => {
    const timer = window.setTimeout(() => { load(); }, 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  return (
    <main className="dashboard-shell">
      <section className="manifest-card wide-card">
        <div className="page-heading">
          <div>
            <p className="eyebrow">Admin</p>
            <h1>Device compatibility log</h1>
          </div>
          <button disabled={loading} onClick={() => load()}>
            {loading ? "Refreshing…" : "Refresh"}
          </button>
        </div>
        <p>Manual refresh only. Used to identify known-incompatible devices.</p>
        <div className="filter-row">
          <label>
            Platform
            <select
              onChange={(event) => setPlatform(event.target.value as PlatformFilter)}
              value={platform}
            >
              <option value="">All platforms</option>
              <option value="ios">iOS</option>
              <option value="android">Android</option>
            </select>
          </label>
          <label>
            Outcome
            <select
              onChange={(event) => setOutcome(event.target.value as OutcomeFilter)}
              value={outcome}
            >
              <option value="">All outcomes</option>
              <option value="compatible">Compatible</option>
              <option value="incompatible">Incompatible</option>
            </select>
          </label>
        </div>
        {error ? <p className="error" role="alert">{error}</p> : null}
        {loading && entries.length === 0 ? (
          <p>Loading compatibility log…</p>
        ) : entries.length === 0 ? (
          <p>No device compatibility checks match these filters.</p>
        ) : (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Device model</th>
                  <th>Platform</th>
                  <th>OS version</th>
                  <th>Outcome</th>
                  <th>Checked</th>
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
                        {outcomeLabel(entry.esim_supported)}
                      </span>
                    </td>
                    <td>
                      <time dateTime={entry.checked_at}>
                        {new Date(entry.checked_at).toLocaleString()}
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
