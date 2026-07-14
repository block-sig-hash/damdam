"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";

import {
  AdminManifestOrder,
  confirmManifestPayment,
  getPendingManifestOrders,
  openAdminInvoice,
} from "@/lib/api";

const naira = new Intl.NumberFormat("en-NG", { style: "currency", currency: "NGN", maximumFractionDigits: 0 });

export default function AdminManifestOrdersPage() {
  const [orders, setOrders] = useState<AdminManifestOrder[]>([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async (term = "") => {
    setLoading(true);
    setError("");
    try { setOrders(await getPendingManifestOrders(term)); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Could not load orders."); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => { load(); }, 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  async function submitSearch(event: FormEvent) {
    event.preventDefault();
    await load(search);
  }

  async function confirm(order: AdminManifestOrder) {
    if (!window.confirm(`Confirm payment for ${order.pilgrim_count} pilgrims? This starts provisioning and cannot be undone.`)) return;
    try {
      await confirmManifestPayment(order.id);
      setOrders((current) => current.filter((item) => item.id !== order.id));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not confirm payment.");
    }
  }

  return (
    <main className="dashboard-shell">
      <section className="manifest-card wide-card">
        <p className="eyebrow">Admin</p>
        <h1>Manifest payment confirmation</h1>
        <form className="search-row" onSubmit={submitSearch}>
          <label>Search HTO<input value={search} onChange={(event) => setSearch(event.target.value)} /></label>
          <button type="submit">Search</button>
        </form>
        {error ? <p className="error" role="alert">{error}</p> : null}
        {loading ? <p>Loading pending orders…</p> : null}
        {!loading && orders.length === 0 ? <p>No awaiting-payment orders.</p> : null}
        <div className="admin-order-list">
          {orders.map((order) => (
            <article className={order.days_pending > 2 ? "admin-order overdue" : "admin-order"} key={order.id}>
              <div><strong>{order.hto_business_name}</strong><span>{order.manifest_name ?? "Untitled manifest"}</span></div>
              <span>{order.pilgrim_count} pilgrims</span>
              <strong>{naira.format(order.total_ngn)}</strong>
              <span>{order.days_pending} days pending</span>
              <button type="button" className="secondary-button" onClick={() => openAdminInvoice(order.id)}>View invoice</button>
              <button type="button" onClick={() => confirm(order)}>Confirm payment received</button>
            </article>
          ))}
        </div>
      </section>
    </main>
  );
}
