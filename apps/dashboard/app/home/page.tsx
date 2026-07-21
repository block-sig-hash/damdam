"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";

import { getHtoPilgrims, getManifests, HtoPilgrim, Manifest } from "@/lib/api";
import { isStaleCheckIn, matchesPilgrimSearch, sortPilgrimsByRisk } from "@/lib/pilgrimRisk";

const AUTO_REFRESH_MS = 60_000;

function formatLastCheckIn(lastCheckinAt: string | null): string {
  if (!lastCheckinAt) return "No check-in yet";
  return new Date(lastCheckinAt).toLocaleString();
}

export default function HTOHomePage() {
  const [pilgrims, setPilgrims] = useState<HtoPilgrim[]>([]);
  const [manifests, setManifests] = useState<Manifest[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [manifestFilter, setManifestFilter] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [pilgrimRows, manifestRows] = await Promise.all([
        getHtoPilgrims(),
        getManifests(),
      ]);
      setPilgrims(pilgrimRows);
      setManifests(manifestRows);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not load pilgrims.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const initial = window.setTimeout(() => { load(); }, 0);
    const timer = window.setInterval(() => { load(); }, AUTO_REFRESH_MS);
    return () => { window.clearTimeout(initial); window.clearInterval(timer); };
  }, [load]);

  const visiblePilgrims = useMemo(() => {
    const now = new Date();
    return sortPilgrimsByRisk(pilgrims, now).filter(
      (pilgrim) =>
        (!manifestFilter || pilgrim.manifest_id === manifestFilter) &&
        matchesPilgrimSearch(pilgrim, search),
    );
  }, [pilgrims, search, manifestFilter]);

  const unresolvedSOSCount = pilgrims.filter((p) => p.sos_status === "active").length;

  return (
    <main className="dashboard-shell">
      <section className="manifest-card wide-card">
        <div className="page-heading">
          <div>
            <p className="eyebrow">HTO operations</p>
            <h1>HTO Home</h1>
          </div>
          <button disabled={loading} onClick={() => load()}>
            {loading ? "Refreshing…" : "Refresh"}
          </button>
        </div>
        <p>All manifests, sorted by risk. Auto-refreshes every 60 seconds.</p>
        {unresolvedSOSCount > 0 ? (
          <aside className="sos-home-banner" role="alert">
            <strong>
              {unresolvedSOSCount} unresolved SOS {unresolvedSOSCount === 1 ? "alert" : "alerts"}
            </strong>
            <a href="/sos-alerts">Open SOS Alerts</a>
          </aside>
        ) : null}
        {!loading && manifests.length === 0 ? (
          <p>
            No manifests yet.{" "}
            <Link className="primary-link" href="/manifests/new">
              Create your first manifest
            </Link>
          </p>
        ) : (
          <>
            <div className="filter-row">
              <label>
                Manifest
                <select
                  onChange={(event) => setManifestFilter(event.target.value)}
                  value={manifestFilter}
                >
                  <option value="">All manifests</option>
                  {manifests.map((manifest) => (
                    <option key={manifest.id} value={manifest.id}>
                      {manifest.name ?? "Unnamed manifest"}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <input
              aria-label="Search pilgrims by name or phone"
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search by name or phone"
              type="search"
              value={search}
            />
            {error ? <p className="error" role="alert">{error}</p> : null}
            {loading && pilgrims.length === 0 ? (
              <p>Loading pilgrims…</p>
            ) : pilgrims.length === 0 ? (
              <p>No pilgrims across your manifests yet.</p>
            ) : visiblePilgrims.length === 0 ? (
              <p>No pilgrims match the current filters.</p>
            ) : (
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Name</th>
                      <th>Phone</th>
                      <th>Manifest</th>
                      <th>Tier</th>
                      <th>Activation</th>
                      <th>eSIM</th>
                      <th>Last check-in</th>
                    </tr>
                  </thead>
                  <tbody>
                    {visiblePilgrims.map((pilgrim) => {
                      const sos = pilgrim.sos_status === "active";
                      const stale = !sos && isStaleCheckIn(pilgrim.last_checkin_at, new Date());
                      return (
                        <tr
                          className={sos ? "row-sos" : stale ? "row-stale" : undefined}
                          key={pilgrim.id}
                        >
                          <td>
                            {sos ? <span className="status-pill">SOS</span> : null}
                            {pilgrim.name}
                          </td>
                          <td>{pilgrim.phone_number}</td>
                          <td>
                            <a href={`/manifests/${pilgrim.manifest_id}`}>
                              {pilgrim.manifest_name ?? "Untitled manifest"}
                            </a>
                          </td>
                          <td>{pilgrim.tier ?? "—"}</td>
                          <td>
                            <span
                              className={`status-badge ${
                                pilgrim.activation_status === "activated" ? "status-approved" : ""
                              }`}
                            >
                              {pilgrim.activation_status === "activated"
                                ? "Activated"
                                : "Not activated"}
                            </span>
                          </td>
                          <td>
                            {pilgrim.esim_status === "incompatible" ? (
                              <span className="status-badge status-follow-up">Follow up</span>
                            ) : ["issued", "downloaded", "activated"].includes(
                                pilgrim.esim_status,
                              ) ? (
                              <span
                                className={`status-badge ${
                                  pilgrim.esim_status === "downloaded" ||
                                  pilgrim.esim_status === "activated"
                                    ? "status-approved"
                                    : ""
                                }`}
                              >
                                {pilgrim.esim_status.charAt(0).toUpperCase() +
                                  pilgrim.esim_status.slice(1)}
                              </span>
                            ) : (
                              "—"
                            )}
                          </td>
                          <td>{formatLastCheckIn(pilgrim.last_checkin_at)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
      </section>
    </main>
  );
}
