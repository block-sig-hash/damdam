"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {useLocale, useTranslations} from "next-intl";

import { getHtoPilgrims, getManifests, HtoPilgrim, Manifest } from "@/lib/api";
import { isStaleCheckIn, matchesPilgrimSearch, sortPilgrimsByRisk } from "@/lib/pilgrimRisk";

const AUTO_REFRESH_MS = 60_000;

export default function HTOHomePage() {
  const t = useTranslations("home");
  const locale = useLocale();
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
      setError(caught instanceof Error ? caught.message : t("loadFailed"));
    } finally {
      setLoading(false);
    }
  }, [t]);

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
            <p className="eyebrow">{t("operations")}</p>
            <h1>{t("title")}</h1>
          </div>
          <button disabled={loading} onClick={() => load()}>
            {loading ? t("refreshing") : t("refresh")}
          </button>
        </div>
        <p>{t("allManifests")}</p>
        {unresolvedSOSCount > 0 ? (
          <aside className="sos-home-banner" role="alert">
            <strong>
              {t("unresolvedSos", {count: unresolvedSOSCount})}
            </strong>
            <a href="/sos-alerts">{t("openSos")}</a>
          </aside>
        ) : null}
        {!loading && manifests.length === 0 ? (
          <p>
            {t("noManifests")}{" "}
            <Link className="primary-link" href="/manifests/new">
              {t("createManifest")}
            </Link>
          </p>
        ) : (
          <>
            <div className="filter-row">
              <label>
                {t("manifest")}
                <select
                  onChange={(event) => setManifestFilter(event.target.value)}
                  value={manifestFilter}
                >
                  <option value="">{t("allManifestOption")}</option>
                  {manifests.map((manifest) => (
                    <option key={manifest.id} value={manifest.id}>
                      {manifest.name ?? t("unnamedManifest")}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <input
              aria-label={t("searchAria")}
              onChange={(event) => setSearch(event.target.value)}
              placeholder={t("searchPlaceholder")}
              type="search"
              value={search}
            />
            {error ? <p className="error" role="alert">{error}</p> : null}
            {loading && pilgrims.length === 0 ? (
              <p>{t("loadingPilgrims")}</p>
            ) : pilgrims.length === 0 ? (
              <p>{t("noPilgrims")}</p>
            ) : visiblePilgrims.length === 0 ? (
              <p>{t("noMatches")}</p>
            ) : (
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>{t("name")}</th>
                      <th>{t("phone")}</th>
                      <th>{t("manifest")}</th>
                      <th>{t("tier")}</th>
                      <th>{t("activation")}</th>
                      <th>eSIM</th>
                      <th>{t("lastCheckIn")}</th>
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
                              {pilgrim.manifest_name ?? t("untitledManifest")}
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
                                ? t("activated")
                                : t("notActivated")}
                            </span>
                          </td>
                          <td>
                            {pilgrim.esim_status === "incompatible" ? (
                              <span className="status-badge status-follow-up">{t("followUp")}</span>
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
                                {t(`esimStatuses.${pilgrim.esim_status as "issued" | "downloaded" | "activated"}`)}
                              </span>
                            ) : (
                              "—"
                            )}
                          </td>
                          <td>{pilgrim.last_checkin_at ? new Date(pilgrim.last_checkin_at).toLocaleString(locale) : t("noCheckIn")}</td>
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
