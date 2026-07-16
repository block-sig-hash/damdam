"use client";

import {useEffect, useState} from "react";
import {getSOSAlerts, type SOSAlert} from "../../lib/api";

export default function HTOHomePage() {
  const [alerts, setAlerts] = useState<SOSAlert[]>([]);
  useEffect(() => {
    const load = () => getSOSAlerts("active").then(setAlerts).catch(() => undefined);
    const initial = window.setTimeout(load, 0);
    const timer = window.setInterval(load, 15_000);
    return () => { window.clearTimeout(initial); window.clearInterval(timer); };
  }, []);
  return (
    <main className="dashboard-page">
      <h1>HTO Home</h1>
      {alerts.length ? (
        <aside className="sos-home-banner" role="alert">
          <strong>{alerts.length} unresolved SOS {alerts.length === 1 ? "alert" : "alerts"}</strong>
          <a href="/sos-alerts">Open SOS Alerts now</a>
        </aside>
      ) : null}
      <section aria-label="Pilgrims requiring immediate attention" className="sos-grid">
        {alerts.map(alert => (
          <a className="sos-pinned-row" href="/sos-alerts" key={alert.id}>
            <strong>SOS — {alert.pilgrim_name}</strong>
            <span>{alert.pilgrim_phone}</span>
            <time dateTime={alert.timestamp}>{new Date(alert.timestamp).toLocaleString()}</time>
          </a>
        ))}
      </section>
      {!alerts.length ? <p>No unresolved SOS alerts.</p> : null}
    </main>
  );
}
