"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import {useLocale, useTranslations} from "next-intl";

import {
  AdminManifestOrder,
  confirmManifestPayment,
  getPendingManifestOrders,
  openAdminInvoice,
} from "@/lib/api";

export default function AdminManifestOrdersPage() {
  const t = useTranslations("admin");
  const locale = useLocale();
  const naira = new Intl.NumberFormat(locale === "fr" ? "fr-NG" : "en-NG", { style: "currency", currency: "NGN", maximumFractionDigits: 0 });
  const [orders, setOrders] = useState<AdminManifestOrder[]>([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async (term = "") => {
    setLoading(true);
    setError("");
    try { setOrders(await getPendingManifestOrders(term)); }
    catch (caught) { setError(caught instanceof Error ? caught.message : t("orders.loadFailed")); }
    finally { setLoading(false); }
  }, [t]);

  useEffect(() => {
    const timer = window.setTimeout(() => { load(); }, 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  async function submitSearch(event: FormEvent) {
    event.preventDefault();
    await load(search);
  }

  async function confirm(order: AdminManifestOrder) {
    if (!window.confirm(t("orders.confirmPrompt", {count: order.pilgrim_count}))) return;
    try {
      await confirmManifestPayment(order.id);
      setOrders((current) => current.filter((item) => item.id !== order.id));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("orders.confirmFailed"));
    }
  }

  return (
    <main className="dashboard-shell">
      <section className="manifest-card wide-card">
        <p className="eyebrow">{t("label")}</p>
        <h1>{t("orders.title")}</h1>
        <form className="search-row" onSubmit={submitSearch}>
          <label>{t("orders.searchHto")}<input value={search} onChange={(event) => setSearch(event.target.value)} /></label>
          <button type="submit">{t("orders.search")}</button>
        </form>
        {error ? <p className="error" role="alert">{error}</p> : null}
        {loading ? <p>{t("orders.loading")}</p> : null}
        {!loading && orders.length === 0 ? <p>{t("orders.empty")}</p> : null}
        <div className="admin-order-list">
          {orders.map((order) => (
            <article className={order.days_pending > 2 ? "admin-order overdue" : "admin-order"} key={order.id}>
              <div><strong>{order.hto_business_name}</strong><span>{order.manifest_name ?? t("orders.untitled")}</span></div>
              <span>{t("orders.pilgrims", {count: order.pilgrim_count})}</span>
              <strong>{naira.format(order.total_ngn)}</strong>
              <span>{t("orders.days", {count: order.days_pending})}</span>
              <button type="button" className="secondary-button" onClick={() => openAdminInvoice(order.id)}>{t("orders.invoice")}</button>
              <button type="button" onClick={() => confirm(order)}>{t("orders.confirm")}</button>
            </article>
          ))}
        </div>
      </section>
    </main>
  );
}
