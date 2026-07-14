"use client";

import { FormEvent, useState } from "react";

import {
  confirmManifest,
  createManifest,
  ManifestUploadResult,
  uploadManifest,
} from "@/lib/api";

export default function ManifestUploadPage() {
  const [name, setName] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [manifestId, setManifestId] = useState<string | null>(null);
  const [preview, setPreview] = useState<ManifestUploadResult | null>(null);
  const [uploading, setUploading] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [confirmedCount, setConfirmedCount] = useState<number | null>(null);
  const [error, setError] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file) return;
    setUploading(true);
    setError("");
    try {
      const id = manifestId ?? (await createManifest(name));
      setManifestId(id);
      setPreview(await uploadManifest(id, file));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Upload failed.");
    } finally {
      setUploading(false);
    }
  }

  async function confirm() {
    if (!manifestId) return;
    setConfirming(true);
    setError("");
    try {
      setConfirmedCount(await confirmManifest(manifestId));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Confirmation failed.");
    } finally {
      setConfirming(false);
    }
  }

  function reupload() {
    setPreview(null);
    setFile(null);
    setError("");
  }

  if (confirmedCount !== null) {
    return (
      <main className="dashboard-shell">
        <section className="manifest-card" aria-live="polite">
          <p className="eyebrow">Manifest confirmed</p>
          <h1>{confirmedCount} pilgrims accepted</h1>
          <p>The valid rows are ready for package selection.</p>
          <a
            className="primary-link"
            href={`/manifests/${manifestId}/order`}
          >
            Continue to grouping and package order
          </a>
        </section>
      </main>
    );
  }

  if (preview) {
    const warnings = preview.preview.filter((row) => row.warning);
    return (
      <main className="dashboard-shell">
        <section className="manifest-card wide-card">
          <p className="eyebrow">Validation preview</p>
          <h1>Review before confirming</h1>
          <div className="summary-row" aria-label="Upload summary">
            <strong>{preview.valid_rows} valid</strong>
            <span>{preview.invalid_rows.length} invalid</span>
            <span>{warnings.length} duplicate warnings</span>
          </div>

          <section className="issues-panel">
            <h2>Issues found</h2>
            {preview.invalid_rows.length === 0 && warnings.length === 0 ? (
              <p>No issues found.</p>
            ) : (
              <ul className="issue-list">
                {preview.invalid_rows.map((issue) => (
                  <li className="hard-error" key={`error-${issue.row_number}`}>
                    <strong>Row {issue.row_number}</strong>: {issue.reason}
                  </li>
                ))}
                {warnings.map((row) => (
                  <li className="warning" key={`warning-${row.id}`}>
                    <strong>Row {row.row_number}</strong>: {row.first_name} {row.last_name} — {row.warning}
                  </li>
                ))}
              </ul>
            )}
          </section>

          <details>
            <summary>Valid rows ({preview.valid_rows})</summary>
            <div className="table-scroll">
              <table>
                <thead><tr><th>Row</th><th>Name</th><th>Phone</th><th>Passport</th><th>Seat</th></tr></thead>
                <tbody>
                  {preview.preview.map((row) => (
                    <tr key={row.id}>
                      <td>{row.row_number}</td>
                      <td>{row.first_name} {row.last_name}</td>
                      <td>{row.phone_number}</td>
                      <td>{row.passport_number ?? "—"}</td>
                      <td>{row.seat_number ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>

          {error ? <p className="error" role="alert">{error}</p> : null}
          <div className="action-row">
            <button className="secondary-button" type="button" onClick={reupload}>
              Cancel and re-upload
            </button>
            <button type="button" onClick={confirm} disabled={confirming || preview.valid_rows === 0}>
              {confirming ? "Confirming…" : "Confirm and proceed"}
            </button>
          </div>
        </section>
      </main>
    );
  }

  return (
    <main className="dashboard-shell">
      <section className="manifest-card">
        <p className="eyebrow">New manifest</p>
        <h1>Upload pilgrim CSV</h1>
        <p className="intro">Up to 500 pilgrims. Invalid rows will be separated before you confirm.</p>
        <form onSubmit={submit} className="single-column-form">
          <label>
            Manifest name <span className="hint">(optional)</span>
            <input value={name} onChange={(event) => setName(event.target.value)} placeholder="Flight NAF203 — 14 May" />
          </label>
          <label className="file-zone">
            CSV file
            <input
              required
              type="file"
              accept=".csv,text/csv"
              onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            />
            <span className="hint">Required: first_name, last_name, phone_number</span>
          </label>
          <a href="/manifest-template.csv" download>Download CSV template</a>
          {error ? <p className="error" role="alert">{error}</p> : null}
          <button type="submit" disabled={!file || uploading}>
            {uploading ? "Uploading and validating…" : "Upload"}
          </button>
        </form>
      </section>
    </main>
  );
}
