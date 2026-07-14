"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";

import {
  AdminHTOOperator,
  HTOApprovalStatus,
  approveHTOOperator,
  getAdminHTOOperators,
  rejectHTOOperator,
} from "@/lib/api";

const STATUSES: HTOApprovalStatus[] = ["pending", "approved", "rejected"];

export default function AdminHTOOperatorsPage() {
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
    catch (caught) { setError(caught instanceof Error ? caught.message : "Could not load operators."); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => { load(status); }, 0);
    return () => window.clearTimeout(timer);
  }, [status, load]);

  async function approve(operator: AdminHTOOperator) {
    if (!window.confirm(`Approve ${operator.business_name}? They will be notified by email and WhatsApp.`)) return;
    try {
      await approveHTOOperator(operator.id);
      setOperators((current) => current.filter((item) => item.id !== operator.id));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not approve operator.");
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
      setError("Enter a reason for rejecting this operator.");
      return;
    }
    if (!window.confirm(`Reject ${operator.business_name}? This cannot be undone.`)) return;
    try {
      await rejectHTOOperator(operator.id, reason.trim());
      setOperators((current) => current.filter((item) => item.id !== operator.id));
      cancelReject();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not reject operator.");
    }
  }

  return (
    <main className="dashboard-shell">
      <section className="manifest-card wide-card">
        <p className="eyebrow">Admin</p>
        <h1>HTO operator approvals</h1>
        <div className="search-row">
          {STATUSES.map((candidate) => (
            <button
              key={candidate}
              type="button"
              className={candidate === status ? undefined : "secondary-button"}
              onClick={() => setStatus(candidate)}
            >
              {candidate[0].toUpperCase() + candidate.slice(1)}
            </button>
          ))}
        </div>
        {error ? <p className="error" role="alert">{error}</p> : null}
        {loading ? <p>Loading operators…</p> : null}
        {!loading && operators.length === 0 ? <p>No {status} operators.</p> : null}
        <div className="admin-order-list">
          {operators.map((operator) => (
            <article className="admin-order" key={operator.id}>
              <div>
                <strong>{operator.business_name}</strong>
                <span>{operator.operator_name} · {operator.email}</span>
                <span>{operator.phone_number} · Licence {operator.nahcon_licence_number}</span>
                <span>{operator.email_verified ? "Email verified" : "Email not verified"}</span>
              </div>
              {status === "pending" ? (
                rejectingId === operator.id ? (
                  <form className="search-row" onSubmit={(event) => confirmReject(event, operator)}>
                    <label>
                      Rejection reason
                      <input
                        value={reason}
                        onChange={(event) => setReason(event.target.value)}
                      />
                    </label>
                    <button type="submit">Confirm reject</button>
                    <button type="button" className="secondary-button" onClick={cancelReject}>
                      Cancel
                    </button>
                  </form>
                ) : (
                  <>
                    <button type="button" onClick={() => approve(operator)}>Approve</button>
                    <button type="button" className="link-button danger-link" onClick={() => startReject(operator)}>
                      Reject
                    </button>
                  </>
                )
              ) : (
                <span className={`status-badge status-${operator.approval_status}`}>
                  {operator.approval_status}
                </span>
              )}
            </article>
          ))}
        </div>
      </section>
    </main>
  );
}
