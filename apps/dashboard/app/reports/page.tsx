"use client";

import {useEffect, useState} from "react";
import {downloadProvisioningReport, getManifests, type Manifest} from "../../lib/api";

export default function ReportsPage() {
  const [manifests, setManifests] = useState<Manifest[]>([]);
  const [manifestId, setManifestId] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    getManifests()
      .then(setManifests)
      .catch(cause => setError(cause instanceof Error ? cause.message : "Could not load manifests."));
  }, []);

  async function download() {
    setGenerating(true);
    setError("");
    try {
      await downloadProvisioningReport({
        manifestId: manifestId || undefined,
        dateFrom: dateFrom || undefined,
        dateTo: dateTo || undefined,
      });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not generate the report.");
    } finally {
      setGenerating(false);
    }
  }

  const manifestLabel = manifestId
    ? (manifests.find(m => m.id === manifestId)?.name ?? "the selected manifest")
    : "all manifests";
  const rangeLabel = dateFrom || dateTo ? `${dateFrom || "the start"} to ${dateTo || "now"}` : "your full provisioning history";

  return (
    <main className="dashboard-page">
      <header className="page-heading">
        <div>
          <p className="eyebrow">HTO records &amp; compliance</p>
          <h1>Provisioning Report</h1>
        </div>
      </header>

      <p>
        Downloads a CSV covering {manifestLabel}, {rangeLabel} — name, phone, tier, purchase date, eSIM
        status, check-in count, and SOS events per pilgrim.
      </p>

      <div className="report-controls">
        <label>
          Manifest
          <select value={manifestId} onChange={event => setManifestId(event.target.value)}>
            <option value="">All manifests</option>
            {manifests.map(manifest => (
              <option key={manifest.id} value={manifest.id}>
                {manifest.name ?? "Unnamed manifest"}
              </option>
            ))}
          </select>
        </label>
        <label>
          From
          <input type="date" value={dateFrom} onChange={event => setDateFrom(event.target.value)} />
        </label>
        <label>
          To
          <input type="date" value={dateTo} onChange={event => setDateTo(event.target.value)} />
        </label>
      </div>

      {error ? <p role="alert">{error}</p> : null}

      <div className="action-row">
        <button disabled={generating} onClick={download}>
          {generating ? "Generating…" : "Download CSV"}
        </button>
        {generating ? <p>This can take up to 30 seconds for large manifests.</p> : null}
      </div>
    </main>
  );
}
