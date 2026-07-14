"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";

import {
  AdminPricingTier,
  getAdminPricingTiers,
  updateAdminPricingTierPrice,
} from "@/lib/api";

const naira = new Intl.NumberFormat("en-NG", { style: "currency", currency: "NGN", maximumFractionDigits: 0 });

export default function AdminPricingTiersPage() {
  const [tiers, setTiers] = useState<AdminPricingTier[]>([]);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draftPrice, setDraftPrice] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try { setTiers(await getAdminPricingTiers()); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Could not load pricing tiers."); }
    finally { setLoading(false); }
  }, []);

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
      setError("Enter a price greater than zero.");
      return;
    }
    const percentChange = ((newPrice - tier.ngn_price) / tier.ngn_price) * 100;
    const direction = percentChange >= 0 ? "increase" : "decrease";
    const confirmed = window.confirm(
      `Change ${tier.name} from ${naira.format(tier.ngn_price)} to ${naira.format(newPrice)} ` +
      `(${Math.abs(percentChange).toFixed(1)}% ${direction})? This takes effect immediately for new purchases.`,
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
      setError(caught instanceof Error ? caught.message : "Could not update price.");
    }
  }

  return (
    <main className="dashboard-shell">
      <section className="manifest-card wide-card">
        <p className="eyebrow">Admin</p>
        <h1>Naira pricing</h1>
        {error ? <p className="error" role="alert">{error}</p> : null}
        {loading ? <p>Loading pricing tiers…</p> : null}
        {!loading && tiers.length === 0 ? <p>No active pricing tiers.</p> : null}
        <div className="admin-order-list">
          {tiers.map((tier) => (
            <article className="admin-order" key={tier.id}>
              <div>
                <strong>{tier.name}</strong>
                <span>{tier.is_group_tier ? "Family (group)" : "Individual"}</span>
              </div>
              {editingId === tier.id ? (
                <form className="search-row" onSubmit={(event) => submitEdit(event, tier)}>
                  <label>
                    New price (₦)
                    <input
                      type="number"
                      min="0.01"
                      step="0.01"
                      value={draftPrice}
                      onChange={(event) => setDraftPrice(event.target.value)}
                      required
                    />
                  </label>
                  <button type="submit">Save</button>
                  <button type="button" className="secondary-button" onClick={cancelEdit}>
                    Cancel
                  </button>
                </form>
              ) : (
                <>
                  <strong>{naira.format(tier.ngn_price)}</strong>
                  <button type="button" className="secondary-button" onClick={() => startEdit(tier)}>
                    Edit
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
