"use client";

import {useCallback, useEffect, useState} from "react";
import {getSOSAlerts, resolveSOSAlert, type SOSAlert} from "../../lib/api";
import {enableSOSPushAlerts, type PushSubscriptionOutcome} from "../../lib/push";

type Filter = "active" | "resolved" | "all";

export default function SOSAlertsPage() {
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
      setError(cause instanceof Error ? cause.message : "Could not load SOS alerts.");
    }
  }, [filter]);
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
      <header className="page-heading"><div><p className="eyebrow">HTO safety desk</p><h1>SOS Alerts</h1></div><p>Refreshes every 15 seconds</p></header>
      {pushPermission === "default" ? (
        <aside className="push-banner" role="status">
          <p>Get an alert on this browser the moment an SOS comes in, even when this tab isn&apos;t open.</p>
          <button disabled={enablingPush} onClick={requestPushAlerts}>
            {enablingPush ? "Enabling…" : "Enable browser alerts"}
          </button>
        </aside>
      ) : null}
      {pushOutcome === "error" ? <p role="alert">Could not enable browser alerts. Try again shortly.</p> : null}
      {pushOutcome === "unsupported" ? <p role="alert">This browser doesn&apos;t support push alerts.</p> : null}
      <nav aria-label="SOS status filter" className="filter-row">
        {(["active", "resolved", "all"] as const).map(value => <button aria-pressed={filter === value} key={value} onClick={() => setFilter(value)}>{value[0].toUpperCase() + value.slice(1)}</button>)}
      </nav>
      {error ? <p role="alert">{error}</p> : null}
      <section aria-live="polite" className="sos-grid">
        {alerts.length === 0 ? <p>No {filter} SOS alerts.</p> : alerts.map(alert => (
          <article className={`sos-card sos-${alert.status}`} key={alert.id}>
            <div><span className="status-pill">{alert.status.toUpperCase()}</span><h2>{alert.pilgrim_name}</h2><a href={`tel:${alert.pilgrim_phone}`}>{alert.pilgrim_phone}</a><time dateTime={alert.timestamp}>{new Date(alert.timestamp).toLocaleString()}</time></div>
            {alert.latitude !== null && alert.longitude !== null ? <a href={`https://www.google.com/maps?q=${alert.latitude},${alert.longitude}`} target="_blank" rel="noreferrer">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img alt={`Location of ${alert.pilgrim_name}`} src={`https://staticmap.openstreetmap.de/staticmap.php?center=${alert.latitude},${alert.longitude}&zoom=15&size=420x180&markers=${alert.latitude},${alert.longitude},red-pushpin`} />
            </a> : <p>Location unavailable</p>}
            <div className="action-row"><a href={`/pilgrims/${alert.id}`}>View pilgrim detail</a>{alert.status === "active" ? <button onClick={() => resolve(alert)}>Resolve</button> : null}</div>
          </article>
        ))}
      </section>
    </main>
  );
}
