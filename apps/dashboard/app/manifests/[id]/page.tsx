"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";

import { getHtoPilgrims, HtoPilgrim } from "@/lib/api";
import { isStaleCheckIn, matchesPilgrimSearch, sortPilgrimsByRisk } from "@/lib/pilgrimRisk";

const AUTO_REFRESH_MS = 60_000;

function formatLastCheckIn(lastCheckinAt: string | null): string {
  if (!lastCheckinAt) return "No check-in yet";
  return new Date(lastCheckinAt).toLocaleString();
}

export default function ManifestDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [pilgrims, setPilgrims] = useState<HtoPilgrim[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setPilgrims(await getHtoPilgrims(id));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not load pilgrims.");
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    const initial = window.setTimeout(() => { load(); }, 0);
    const timer = window.setInterval(() => { load(); }, AUTO_REFRESH_MS);
    return () => { window.clearTimeout(initial); window.clearInterval(timer); };
  }, [load]);

  const visiblePilgrims = useMemo(() => {
    const now = new Date();
    return sortPilgrimsByRisk(pilgrims, now).filter((pilgrim) =>
      matchesPilgrimSearch(pilgrim, search),
    );
  }, [pilgrims, search]);

  const unresolvedSOSCount = pilgrims.filter((p) => p.sos_status === "active").length;

  return (
    <main className="dashboard-shell">
      <section className="manifest-card wide-card">
        <div className="page-heading">
          <div>
            <p className="eyebrow">Manifest</p>
            <h1>Pilgrim roster</h1>
          </div>
          <button disabled={loading} onClick={() => load()}>
            {loading ? "Refreshing…" : "Refresh"}
          </button>
        </div>
        <p>Sorted by risk. Auto-refreshes every 60 seconds.</p>
        {unresolvedSOSCount > 0 ? (
          <aside className="sos-home-banner" role="alert">
            <strong>
              {unresolvedSOSCount} unresolved SOS {unresolvedSOSCount === 1 ? "alert" : "alerts"}{" "}
              on this manifest
            </strong>
            <a href="/sos-alerts">Open SOS Alerts</a>
          </aside>
        ) : null}
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
          <p>No pilgrims on this manifest yet.</p>
        ) : visiblePilgrims.length === 0 ? (
          <p>No pilgrims match &quot;{search}&quot;.</p>
        ) : (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Phone</th>
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
      </section>
    </main>
  );
}
