"use client";

import { FormEvent, useState } from "react";
import { useTranslations } from "next-intl";

import {
  confirmManifest,
  createManifest,
  ManifestUploadResult,
  uploadManifest,
} from "@/lib/api";

export default function ManifestUploadPage() {
  const t = useTranslations("manifests.upload");
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
      setError(caught instanceof Error ? caught.message : t("uploadFailed"));
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
      setError(caught instanceof Error ? caught.message : t("confirmationFailed"));
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
          <p className="eyebrow">{t("confirmedEyebrow")}</p>
          <h1>{t("accepted", { count: confirmedCount })}</h1>
          <p>{t("ready")}</p>
          <a
            className="primary-link"
            href={`/manifests/${manifestId}/order`}
          >
            {t("continue")}
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
          <p className="eyebrow">{t("previewEyebrow")}</p>
          <h1>{t("reviewTitle")}</h1>
          <div className="summary-row" aria-label={t("summaryAria")}>
            <strong>{t("valid", { count: preview.valid_rows })}</strong>
            <span>{t("invalid", { count: preview.invalid_rows.length })}</span>
            <span>{t("duplicateWarnings", { count: warnings.length })}</span>
          </div>

          <section className="issues-panel">
            <h2>{t("issues")}</h2>
            {preview.invalid_rows.length === 0 && warnings.length === 0 ? (
              <p>{t("noIssues")}</p>
            ) : (
              <ul className="issue-list">
                {preview.invalid_rows.map((issue) => (
                  <li className="hard-error" key={`error-${issue.row_number}`}>
                    <strong>{t("row", { number: issue.row_number })}</strong>: {issue.reason}
                  </li>
                ))}
                {warnings.map((row) => (
                  <li className="warning" key={`warning-${row.id}`}>
                    <strong>{t("row", { number: row.row_number })}</strong>: {row.first_name} {row.last_name} — {row.warning}
                  </li>
                ))}
              </ul>
            )}
          </section>

          <details>
            <summary>{t("validRows", { count: preview.valid_rows })}</summary>
            <div className="table-scroll">
              <table>
                <thead><tr><th>{t("row", { number: "" })}</th><th>{t("name")}</th><th>{t("phone")}</th><th>{t("passport")}</th><th>{t("seat")}</th></tr></thead>
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
              {t("cancelReupload")}
            </button>
            <button type="button" onClick={confirm} disabled={confirming || preview.valid_rows === 0}>
              {confirming ? t("confirming") : t("confirmProceed")}
            </button>
          </div>
        </section>
      </main>
    );
  }

  return (
    <main className="dashboard-shell">
      <section className="manifest-card">
        <p className="eyebrow">{t("newEyebrow")}</p>
        <h1>{t("title")}</h1>
        <p className="intro">{t("intro")}</p>
        <form onSubmit={submit} className="single-column-form">
          <label>
            {t("manifestName")} <span className="hint">{t("optional")}</span>
            <input value={name} onChange={(event) => setName(event.target.value)} placeholder={t("namePlaceholder")} />
          </label>
          <label className="file-zone">
            {t("csvFile")}
            <input
              required
              type="file"
              accept=".csv,text/csv"
              onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            />
            <span className="hint">{t("requiredColumns")}</span>
          </label>
          <a href="/manifest-template.csv" download>{t("downloadTemplate")}</a>
          {error ? <p className="error" role="alert">{error}</p> : null}
          <button type="submit" disabled={!file || uploading}>
            {uploading ? t("uploading") : t("submit")}
          </button>
        </form>
      </section>
    </main>
  );
}
