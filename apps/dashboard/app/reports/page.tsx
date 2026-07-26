"use client";

import {useEffect, useState} from "react";
import {useTranslations} from "next-intl";
import {downloadProvisioningReport, getManifests, type Manifest} from "../../lib/api";

export default function ReportsPage() {
  const t = useTranslations("reports");
  const [manifests, setManifests] = useState<Manifest[]>([]);
  const [manifestId, setManifestId] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    getManifests()
      .then(setManifests)
      .catch(cause => setError(cause instanceof Error ? cause.message : t("loadFailed")));
  }, [t]);

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
      setError(cause instanceof Error ? cause.message : t("generateFailed"));
    } finally {
      setGenerating(false);
    }
  }

  const manifestLabel = manifestId
    ? (manifests.find(m => m.id === manifestId)?.name ?? t("selectedManifest"))
    : t("allManifests");
  const rangeLabel = dateFrom || dateTo
    ? t("range", {from: dateFrom || t("start"), to: dateTo || t("now")})
    : t("fullHistory");

  return (
    <main className="dashboard-page">
      <header className="page-heading">
        <div>
          <p className="eyebrow">{t("eyebrow")}</p>
          <h1>{t("title")}</h1>
        </div>
      </header>

      <p>
        {t("description", {manifest: manifestLabel, range: rangeLabel})}
      </p>

      <div className="report-controls">
        <label>
          {t("manifest")}
          <select value={manifestId} onChange={event => setManifestId(event.target.value)}>
            <option value="">{t("allOption")}</option>
            {manifests.map(manifest => (
              <option key={manifest.id} value={manifest.id}>
                {manifest.name ?? t("unnamed")}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("from")}
          <input type="date" value={dateFrom} onChange={event => setDateFrom(event.target.value)} />
        </label>
        <label>
          {t("to")}
          <input type="date" value={dateTo} onChange={event => setDateTo(event.target.value)} />
        </label>
      </div>

      {error ? <p role="alert">{error}</p> : null}

      <div className="action-row">
        <button disabled={generating} onClick={download}>
          {generating ? t("generating") : t("download")}
        </button>
        {generating ? <p>{t("duration")}</p> : null}
      </div>
    </main>
  );
}
