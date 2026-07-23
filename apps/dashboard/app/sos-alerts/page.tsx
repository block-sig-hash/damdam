"use client";

import {useCallback, useEffect, useState} from "react";
import {useLocale, useTranslations} from "next-intl";
import {getSOSAlerts, resolveSOSAlert, type SOSAlert} from "../../lib/api";
import {enableSOSPushAlerts, type PushSubscriptionOutcome} from "../../lib/push";

type Filter = "active" | "resolved" | "all";

export default function SOSAlertsPage() {
  const t = useTranslations("safety");
  const locale = useLocale();
  const [filter, setFilter] = useState<Filter>("active");
  const [alerts, setAlerts] = useState<SOSAlert[]>([]);
  const [error, setError] = useState("");
  const [pushPermission, setPushPermission] = useState<NotificationPermission | "unsupported">("default");
  const [pushOutcome, setPushOutcome] = useState<PushSubscriptionOutcome>();
  const [enablingPush, setEnablingPush] = useState(false);
  const load = useCallback(async () => {
    try {
      setAlerts(await getSOSAlerts(filter === "all" ? undefined : filter));
      setError("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : t("loadFailed"));
    }
  }, [filter, t]);
  useEffect(() => {
    const initial = window.setTimeout(load, 0);
    const timer = window.setInterval(load, 15_000);
    return () => { window.clearTimeout(initial); window.clearInterval(timer); };
  }, [load]);
  useEffect(() => {
    // One-time sync with a browser API that isn't available during SSR
    // (Notification is undefined in Node), so it can't be read at render
    // time -- not a subscription, nothing to clean up.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setPushPermission(typeof Notification === "undefined" ? "unsupported" : Notification.permission);
  }, []);
  async function resolve(alert: SOSAlert) {
    await resolveSOSAlert(alert.id);
    setAlerts(rows => rows.map(row => row.id === alert.id ? {...row, status: "resolved"} : row));
  }
  async function requestPushAlerts() {
    // Only ever called from this button press -- never on page load.
    setEnablingPush(true);
    try {
      const outcome = await enableSOSPushAlerts();
      setPushOutcome(outcome);
      setPushPermission(typeof Notification === "undefined" ? "unsupported" : Notification.permission);
    } finally {
      setEnablingPush(false);
    }
  }
  return (
    <main className="dashboard-page">
      <header className="page-heading"><div><p className="eyebrow">{t("desk")}</p><h1>{t("title")}</h1></div><p>{t("refresh")}</p></header>
      {pushPermission === "default" ? (
        <aside className="push-banner" role="status">
          <p>{t("pushIntro")}</p>
          <button disabled={enablingPush} onClick={requestPushAlerts}>
            {enablingPush ? t("enabling") : t("enable")}
          </button>
        </aside>
      ) : null}
      {pushOutcome === "error" ? <p role="alert">{t("pushFailed")}</p> : null}
      {pushOutcome === "unsupported" ? <p role="alert">{t("pushUnsupported")}</p> : null}
      <nav aria-label={t("filterAria")} className="filter-row">
        {(["active", "resolved", "all"] as const).map(value => <button aria-pressed={filter === value} key={value} onClick={() => setFilter(value)}>{t(`filters.${value}`)}</button>)}
      </nav>
      {error ? <p role="alert">{error}</p> : null}
      <section aria-live="polite" className="sos-grid">
        {alerts.length === 0 ? <p>{t("empty", {filter: t(`filters.${filter}`).toLocaleLowerCase(locale)})}</p> : alerts.map(alert => (
          <article className={`sos-card sos-${alert.status}`} key={alert.id}>
            <div><span className="status-pill">{t(`filters.${alert.status as "active" | "resolved"}`)}</span><h2>{alert.pilgrim_name}</h2><a href={`tel:${alert.pilgrim_phone}`}>{alert.pilgrim_phone}</a><time dateTime={alert.timestamp}>{new Date(alert.timestamp).toLocaleString(locale)}</time></div>
            {alert.latitude !== null && alert.longitude !== null ? <a href={`https://www.google.com/maps?q=${alert.latitude},${alert.longitude}`} target="_blank" rel="noreferrer">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img alt={t("locationAlt", {name: alert.pilgrim_name})} src={`https://staticmap.openstreetmap.de/staticmap.php?center=${alert.latitude},${alert.longitude}&zoom=15&size=420x180&markers=${alert.latitude},${alert.longitude},red-pushpin`} />
            </a> : <p>{t("locationUnavailable")}</p>}
            <div className="action-row"><a href={`/pilgrims/${alert.id}`}>{t("viewPilgrim")}</a>{alert.status === "active" ? <button onClick={() => resolve(alert)}>{t("resolve")}</button> : null}</div>
          </article>
        ))}
      </section>
    </main>
  );
}
