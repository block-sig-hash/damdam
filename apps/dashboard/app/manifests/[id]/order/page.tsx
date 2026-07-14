"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";

import {
  createFamilyGroup,
  deleteFamilyGroup,
  getManifestOrders,
  getPricingTiers,
  getUnorderedPilgrims,
  ManifestOrder,
  openManifestInvoice,
  placeManifestOrder,
  PricingTier,
  UnorderedPilgrim,
  updateFamilyGroup,
} from "@/lib/api";

const naira = new Intl.NumberFormat("en-NG", {
  style: "currency",
  currency: "NGN",
  maximumFractionDigits: 0,
});

export default function ManifestOrderPage() {
  const { id } = useParams<{ id: string }>();
  const [pilgrims, setPilgrims] = useState<UnorderedPilgrim[]>([]);
  const [tiers, setTiers] = useState<PricingTier[]>([]);
  const [orders, setOrders] = useState<ManifestOrder[]>([]);
  const [groupSelection, setGroupSelection] = useState<Set<string>>(new Set());
  const [orderSelection, setOrderSelection] = useState<Set<string>>(new Set());
  const [editingGroup, setEditingGroup] = useState<string | null>(null);
  const [tierId, setTierId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [placedOrder, setPlacedOrder] = useState<{ id: string; total: number } | null>(null);

  const refresh = useCallback(async () => {
    const [nextPilgrims, nextTiers, nextOrders] = await Promise.all([
      getUnorderedPilgrims(id),
      getPricingTiers(),
      getManifestOrders(id),
    ]);
    setPilgrims(nextPilgrims);
    setTiers(nextTiers);
    setOrders(nextOrders);
  }, [id]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      refresh().catch((caught) => setError(caught instanceof Error ? caught.message : "Could not load manifest."));
    }, 0);
    return () => window.clearTimeout(timer);
  }, [refresh]);

  useEffect(() => {
    if (!orders.some((order) => order.status === "awaiting_payment")) return;
    const timer = window.setInterval(() => {
      getManifestOrders(id).then(setOrders).catch(() => undefined);
    }, 30_000);
    return () => window.clearInterval(timer);
  }, [id, orders]);

  const groups = useMemo(() => {
    const grouped = new Map<string, UnorderedPilgrim[]>();
    for (const pilgrim of pilgrims) {
      if (!pilgrim.family_group_id) continue;
      const members = grouped.get(pilgrim.family_group_id) ?? [];
      members.push(pilgrim);
      grouped.set(pilgrim.family_group_id, members);
    }
    return grouped;
  }, [pilgrims]);

  const selectedPilgrims = pilgrims.filter((item) => orderSelection.has(item.id));
  const selectedGroupIds = new Set(selectedPilgrims.map((item) => item.family_group_id));
  const completeFamilyGroup =
    selectedPilgrims.length > 0 &&
    selectedGroupIds.size === 1 &&
    !selectedGroupIds.has(null) &&
    groups.get(selectedPilgrims[0].family_group_id!)?.length === selectedPilgrims.length;
  const individualSelection = selectedPilgrims.length > 0 && selectedGroupIds.size === 1 && selectedGroupIds.has(null);
  const availableTiers = tiers.filter((tier) =>
    completeFamilyGroup ? tier.is_group_tier : individualSelection ? !tier.is_group_tier : false,
  );
  const selectedTier = availableTiers.find((tier) => tier.id === tierId) ?? availableTiers[0];
  const total = (selectedTier?.wholesale_price_ngn ?? 0) * selectedPilgrims.length;
  const margin = (selectedTier?.estimated_margin_ngn ?? 0) * selectedPilgrims.length;

  function toggleGroupCandidate(pilgrimId: string) {
    setGroupSelection((current) => {
      const next = new Set(current);
      if (next.has(pilgrimId)) next.delete(pilgrimId); else next.add(pilgrimId);
      return next;
    });
  }

  function toggleOrderPilgrim(pilgrim: UnorderedPilgrim) {
    const ids = pilgrim.family_group_id
      ? (groups.get(pilgrim.family_group_id) ?? []).map((member) => member.id)
      : [pilgrim.id];
    setOrderSelection((current) => {
      const next = new Set(current);
      const remove = ids.every((memberId) => next.has(memberId));
      for (const memberId of ids) {
        if (remove) next.delete(memberId);
        else next.add(memberId);
      }
      return next;
    });
    setTierId("");
  }

  async function saveGroup() {
    setBusy(true);
    setError("");
    try {
      const ids = [...groupSelection];
      if (editingGroup) await updateFamilyGroup(id, editingGroup, ids);
      else await createFamilyGroup(id, ids);
      setEditingGroup(null);
      setGroupSelection(new Set());
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not save family group.");
    } finally {
      setBusy(false);
    }
  }

  async function removeGroup(groupId: string) {
    setBusy(true);
    try {
      await deleteFamilyGroup(id, groupId);
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not delete family group.");
    } finally {
      setBusy(false);
    }
  }

  function editGroup(groupId: string) {
    setEditingGroup(groupId);
    setGroupSelection(new Set((groups.get(groupId) ?? []).map((member) => member.id)));
  }

  async function placeOrder() {
    if (!selectedTier) return;
    setBusy(true);
    setError("");
    try {
      const result = await placeManifestOrder(id, selectedTier.id, [...orderSelection]);
      setPlacedOrder({ id: result.manifest_order_id, total: result.total_ngn });
      setOrderSelection(new Set());
      setTierId("");
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not place order.");
    } finally {
      setBusy(false);
    }
  }

  const groupingCandidates = pilgrims.filter(
    (pilgrim) => !pilgrim.family_group_id || pilgrim.family_group_id === editingGroup,
  );

  return (
    <main className="dashboard-shell">
      <section className="manifest-card wide-card">
        <p className="eyebrow">Manifest packages</p>
        <h1>Group families and place orders</h1>
        {error ? <p className="error" role="alert">{error}</p> : null}

        <section className="order-section">
          <h2>1. Optional Family grouping</h2>
          <p>Select 2–8 pilgrims who will share a Family-tier purchase.</p>
          <div className="check-grid">
            {groupingCandidates.map((pilgrim) => (
              <label className="check-row" key={pilgrim.id}>
                <input
                  type="checkbox"
                  checked={groupSelection.has(pilgrim.id)}
                  onChange={() => toggleGroupCandidate(pilgrim.id)}
                />
                <span>{pilgrim.name}<small>{pilgrim.phone_number}</small></span>
              </label>
            ))}
          </div>
          <button type="button" disabled={busy || groupSelection.size < 2 || groupSelection.size > 8} onClick={saveGroup}>
            {editingGroup ? `Update group (${groupSelection.size})` : `Group selected (${groupSelection.size})`}
          </button>
          {editingGroup ? <button type="button" className="link-button" onClick={() => { setEditingGroup(null); setGroupSelection(new Set()); }}>Cancel editing</button> : null}

          {[...groups].map(([groupId, members]) => (
            <div className="family-group" key={groupId}>
              <strong>Family group ({members.length})</strong>
              <span>{members.map((member) => member.name).join(", ")}</span>
              <div><button type="button" className="link-button" onClick={() => editGroup(groupId)}>Edit</button><button type="button" className="link-button danger-link" onClick={() => removeGroup(groupId)}>Delete</button></div>
            </div>
          ))}
        </section>

        <section className="order-section">
          <h2>2. Select pilgrims</h2>
          <p>Choosing one Family member selects their complete group.</p>
          <div className="check-grid">
            {pilgrims.map((pilgrim) => (
              <label className="check-row" key={pilgrim.id}>
                <input type="checkbox" checked={orderSelection.has(pilgrim.id)} onChange={() => toggleOrderPilgrim(pilgrim)} />
                <span>{pilgrim.name}<small>{pilgrim.family_group_id ? "Family group" : pilgrim.phone_number}</small></span>
              </label>
            ))}
          </div>
        </section>

        <section className="order-section">
          <h2>3. Select package tier</h2>
          {!completeFamilyGroup && !individualSelection && selectedPilgrims.length ? <p className="error">Select individuals or one complete Family group, not both.</p> : null}
          <div className="tier-grid">
            {availableTiers.map((tier) => (
              <label className="tier-card" key={tier.id}>
                <input type="radio" name="tier" checked={(selectedTier?.id ?? "") === tier.id} onChange={() => setTierId(tier.id)} />
                <strong>{tier.name}</strong>
                <span>{naira.format(tier.wholesale_price_ngn)} per pilgrim</span>
                <small>Retail {naira.format(tier.retail_price_ngn)} · Margin {naira.format(tier.estimated_margin_ngn)}</small>
              </label>
            ))}
          </div>
          {selectedTier ? (
            <div className="price-summary">
              <span>{selectedPilgrims.length} × {naira.format(selectedTier.wholesale_price_ngn)}</span>
              <strong>Total {naira.format(total)}</strong>
              <span>Estimated retail margin {naira.format(margin)}</span>
            </div>
          ) : null}
          <button type="button" disabled={busy || !selectedTier} onClick={placeOrder}>Place order and generate invoice</button>
        </section>

        {placedOrder ? (
          <section className="success-panel" aria-live="polite">
            <strong>Order awaiting bank-transfer payment</strong>
            <span>Total: {naira.format(placedOrder.total)}</span>
            <button type="button" onClick={() => openManifestInvoice(id, placedOrder.id)}>View PDF invoice</button>
          </section>
        ) : null}

        <section className="order-section">
          <h2>Orders</h2>
          {orders.map((order) => (
            <div className="order-row" key={order.id}>
              <span><strong>{order.tier_name}</strong> · {order.pilgrim_count} pilgrims</span>
              <span>{naira.format(order.total_ngn)}</span>
              <span className={`status-badge status-${order.status}`}>{order.status.replaceAll("_", " ")}</span>
              <button type="button" className="link-button" onClick={() => openManifestInvoice(id, order.id)}>Invoice</button>
            </div>
          ))}
        </section>
      </section>
    </main>
  );
}
