"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import {useTranslations} from "next-intl";

import { getHtoPilgrims, HtoPilgrim } from "@/lib/api";
import { matchesPilgrimSearch, sortPilgrimsByName } from "@/lib/pilgrimRoster";

const AUTO_REFRESH_MS = 60_000;

export default function ManifestDetailPage() {
  const t = useTranslations("home");
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
      setError(caught instanceof Error ? caught.message : t("loadFailed"));
    } finally {
      setLoading(false);
    }
  }, [id, t]);

  useEffect(() => {
    const initial = window.setTimeout(() => { load(); }, 0);
    const timer = window.setInterval(() => { load(); }, AUTO_REFRESH_MS);
    return () => { window.clearTimeout(initial); window.clearInterval(timer); };
  }, [load]);

  const visiblePilgrims = useMemo(() => {
    return sortPilgrimsByName(pilgrims).filter((pilgrim) =>
      matchesPilgrimSearch(pilgrim, search),
    );
  }, [pilgrims, search]);


  return (
    <main className="dashboard-shell">
      <section className="manifest-card wide-card">
        <div className="page-heading">
          <div>
            <p className="eyebrow">{t("manifest")}</p>
            <h1>{t("roster")}</h1>
          </div>
          <button disabled={loading} onClick={() => load()}>
            {loading ? t("refreshing") : t("refresh")}
          </button>
        </div>
        <p>{t("riskRefresh")}</p>
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
          <p>{t("noManifestPilgrims")}</p>
        ) : visiblePilgrims.length === 0 ? (
          <p>{t("noSearchMatches", {search})}</p>
        ) : (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>{t("name")}</th>
                  <th>{t("phone")}</th>
                  <th>{t("tier")}</th>
                  <th>{t("activation")}</th>
                  <th>eSIM</th>
                </tr>
              </thead>
              <tbody>
                {visiblePilgrims.map((pilgrim) => {
                  return (
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
