"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import {useLocale, useTranslations} from "next-intl";

import {
  AdminPricingTier,
  getAdminPricingTiers,
  updateAdminPricingTierPrice,
} from "@/lib/api";

export default function AdminPricingTiersPage() {
  const t = useTranslations("admin");
  const locale = useLocale();
  const naira = new Intl.NumberFormat(locale === "fr" ? "fr-NG" : "en-NG", { style: "currency", currency: "NGN", maximumFractionDigits: 0 });
  const [tiers, setTiers] = useState<AdminPricingTier[]>([]);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draftPrice, setDraftPrice] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try { setTiers(await getAdminPricingTiers()); }
    catch (caught) { setError(caught instanceof Error ? caught.message : t("pricing.loadFailed")); }
    finally { setLoading(false); }
  }, [t]);

  useEffect(() => {
    const timer = window.setTimeout(() => { load(); }, 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  function startEdit(tier: AdminPricingTier) {
    setError("");
    setEditingId(tier.id);
    setDraftPrice(String(tier.ngn_price));
  }

  function cancelEdit() {
    setEditingId(null);
    setDraftPrice("");
  }

  async function submitEdit(event: FormEvent, tier: AdminPricingTier) {
    event.preventDefault();
    const newPrice = Number(draftPrice);
    if (!Number.isFinite(newPrice) || newPrice <= 0) {
      setError(t("pricing.invalid"));
      return;
    }
    const percentChange = ((newPrice - tier.ngn_price) / tier.ngn_price) * 100;
    const direction = percentChange >= 0 ? t("pricing.increase") : t("pricing.decrease");
    const confirmed = window.confirm(
      t("pricing.confirm", {
        tier: tier.name,
        oldPrice: naira.format(tier.ngn_price),
        newPrice: naira.format(newPrice),
        percent: Math.abs(percentChange).toFixed(1),
        direction,
      }),
    );
    if (!confirmed) return;
    try {
      const result = await updateAdminPricingTierPrice(tier.id, newPrice);
      setTiers((current) =>
        current.map((item) =>
          item.id === tier.id ? { ...item, ngn_price: result.new_ngn_price } : item,
        ),
      );
      cancelEdit();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("pricing.updateFailed"));
    }
  }

  return (
    <main className="dashboard-shell">
      <section className="manifest-card wide-card">
        <p className="eyebrow">{t("label")}</p>
        <h1>{t("pricing.title")}</h1>
        {error ? <p className="error" role="alert">{error}</p> : null}
        {loading ? <p>{t("pricing.loading")}</p> : null}
        {!loading && tiers.length === 0 ? <p>{t("pricing.empty")}</p> : null}
        <div className="admin-order-list">
          {tiers.map((tier) => (
            <article className="admin-order" key={tier.id}>
              <div>
                <strong>{tier.name}</strong>
                <span>{tier.is_group_tier ? t("pricing.family") : t("pricing.individual")}</span>
              </div>
              {editingId === tier.id ? (
                <form className="search-row" onSubmit={(event) => submitEdit(event, tier)}>
                  <label>
                    {t("pricing.newPrice")}
                    <input
                      type="number"
                      min="0.01"
                      step="0.01"
                      value={draftPrice}
                      onChange={(event) => setDraftPrice(event.target.value)}
                      required
                    />
                  </label>
                  <button type="submit">{t("pricing.save")}</button>
                  <button type="button" className="secondary-button" onClick={cancelEdit}>
                    {t("operators.cancel")}
                  </button>
                </form>
              ) : (
                <>
                  <strong>{naira.format(tier.ngn_price)}</strong>
                  <button type="button" className="secondary-button" onClick={() => startEdit(tier)}>
                    {t("pricing.edit")}
                  </button>
                </>
              )}
            </article>
          ))}
        </div>
      </section>
    </main>
  );
}
