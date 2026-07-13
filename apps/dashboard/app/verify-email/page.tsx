"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";

import { verifyHTOEmail } from "@/lib/api";

export function VerifyEmailResult({ token }: { token: string | null }) {
  const [status, setStatus] = useState<"loading" | "success" | "error">(
    token ? "loading" : "error",
  );
  const [message, setMessage] = useState(
    token
      ? "Verifying your email address…"
      : "This verification link is incomplete.",
  );

  useEffect(() => {
    if (!token) {
      return;
    }
    verifyHTOEmail(token)
      .then(() => {
        setStatus("success");
        setMessage(
          "Email verified. Your account is pending DamDam admin approval.",
        );
      })
      .catch((caught: unknown) => {
        setStatus("error");
        setMessage(
          caught instanceof Error
            ? caught.message
            : "The verification link is invalid or expired.",
        );
      });
  }, [token]);

  return (
    <section className="auth-card" aria-live="polite" data-status={status}>
      <p className="eyebrow">Email verification</p>
      <h1>{status === "success" ? "You’re verified" : "Verifying account"}</h1>
      <p>{message}</p>
      {status === "success" ? (
        <p className="hint">Approval usually takes less than 24 hours.</p>
      ) : null}
    </section>
  );
}

function VerificationContent() {
  const searchParams = useSearchParams();
  return <VerifyEmailResult token={searchParams.get("token")} />;
}

export default function VerifyEmailPage() {
  return (
    <main className="auth-shell">
      <Suspense fallback={<section className="auth-card">Loading…</section>}>
        <VerificationContent />
      </Suspense>
    </main>
  );
}
