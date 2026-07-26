"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import {useTranslations} from "next-intl";

import {
  AdminHTOOperator,
  HTOApprovalStatus,
  approveHTOOperator,
  getAdminHTOOperators,
  rejectHTOOperator,
} from "@/lib/api";

const STATUSES: HTOApprovalStatus[] = ["pending", "approved", "rejected"];

export default function AdminHTOOperatorsPage() {
  const t = useTranslations("admin");
  const [status, setStatus] = useState<HTOApprovalStatus>("pending");
  const [operators, setOperators] = useState<AdminHTOOperator[]>([]);
  const [rejectingId, setRejectingId] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async (nextStatus: HTOApprovalStatus) => {
    setLoading(true);
    setError("");
    try { setOperators(await getAdminHTOOperators(nextStatus)); }
    catch (caught) { setError(caught instanceof Error ? caught.message : t("operators.loadFailed")); }
    finally { setLoading(false); }
  }, [t]);

  useEffect(() => {
    const timer = window.setTimeout(() => { load(status); }, 0);
    return () => window.clearTimeout(timer);
  }, [status, load]);

  async function approve(operator: AdminHTOOperator) {
    if (!window.confirm(t("operators.approveConfirm", {business: operator.business_name}))) return;
    try {
      await approveHTOOperator(operator.id);
      setOperators((current) => current.filter((item) => item.id !== operator.id));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("operators.approveFailed"));
    }
  }

  function startReject(operator: AdminHTOOperator) {
    setError("");
    setRejectingId(operator.id);
    setReason("");
  }

  function cancelReject() {
    setRejectingId(null);
    setReason("");
  }

  async function confirmReject(event: FormEvent, operator: AdminHTOOperator) {
    event.preventDefault();
    if (!reason.trim()) {
      setError(t("operators.reasonRequired"));
      return;
    }
    if (!window.confirm(t("operators.rejectConfirm", {business: operator.business_name}))) return;
    try {
      await rejectHTOOperator(operator.id, reason.trim());
      setOperators((current) => current.filter((item) => item.id !== operator.id));
      cancelReject();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("operators.rejectFailed"));
    }
  }

  return (
    <main className="dashboard-shell">
      <section className="manifest-card wide-card">
        <p className="eyebrow">{t("label")}</p>
        <h1>{t("operators.title")}</h1>
        <div className="search-row">
          {STATUSES.map((candidate) => (
            <button
              key={candidate}
              type="button"
              className={candidate === status ? undefined : "secondary-button"}
              onClick={() => setStatus(candidate)}
            >
              {t(`operators.statuses.${candidate}`)}
            </button>
          ))}
        </div>
        {error ? <p className="error" role="alert">{error}</p> : null}
        {loading ? <p>{t("operators.loading")}</p> : null}
        {!loading && operators.length === 0 ? <p>{t("operators.empty", {status: t(`operators.statuses.${status}`).toLocaleLowerCase()})}</p> : null}
        <div className="admin-order-list">
          {operators.map((operator) => (
            <article className="admin-order" key={operator.id}>
              <div>
                <strong>{operator.business_name}</strong>
                <span>{operator.operator_name} · {operator.email}</span>
                <span>{operator.phone_number} · {t("operators.licence", {number: operator.nahcon_licence_number})}</span>
                <span>{operator.email_verified ? t("operators.emailVerified") : t("operators.emailNotVerified")}</span>
              </div>
              {status === "pending" ? (
                rejectingId === operator.id ? (
                  <form className="search-row" onSubmit={(event) => confirmReject(event, operator)}>
                    <label>
                      {t("operators.reason")}
                      <input
                        value={reason}
                        onChange={(event) => setReason(event.target.value)}
                      />
                    </label>
                    <button type="submit">{t("operators.confirmReject")}</button>
                    <button type="button" className="secondary-button" onClick={cancelReject}>
                      {t("operators.cancel")}
                    </button>
                  </form>
                ) : (
                  <>
                    <button type="button" onClick={() => approve(operator)}>{t("operators.approve")}</button>
                    <button type="button" className="link-button danger-link" onClick={() => startReject(operator)}>
                      {t("operators.reject")}
                    </button>
                  </>
                )
              ) : (
                <span className={`status-badge status-${operator.approval_status}`}>
                  {t(`operators.statuses.${operator.approval_status}`)}
                </span>
              )}
            </article>
          ))}
        </div>
      </section>
    </main>
  );
}
