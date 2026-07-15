"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";

import { getHtoPilgrims, HtoPilgrim } from "@/lib/api";

export default function ManifestDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [pilgrims, setPilgrims] = useState<HtoPilgrim[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

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
    const timer = window.setTimeout(() => { load(); }, 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  return (
    <main className="dashboard-shell">
      <section className="manifest-card wide-card">
        <p className="eyebrow">Manifest</p>
        <h1>Pilgrim roster</h1>
        {error ? <p className="error" role="alert">{error}</p> : null}
        {loading ? (
          <p>Loading pilgrims…</p>
        ) : pilgrims.length === 0 ? (
          <p>No pilgrims on this manifest yet.</p>
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
                </tr>
              </thead>
              <tbody>
                {pilgrims.map((pilgrim) => (
                  <tr key={pilgrim.id}>
                    <td>{pilgrim.name}</td>
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
