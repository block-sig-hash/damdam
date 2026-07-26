"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import {useTranslations} from "next-intl";

import { verifyHTOEmail } from "@/lib/api";

export function VerifyEmailResult({ token }: { token: string | null }) {
  const t = useTranslations("auth");
  const [status, setStatus] = useState<"loading" | "success" | "error">(
    token ? "loading" : "error",
  );
  const [message, setMessage] = useState(
    token
      ? t("verifyingEmail")
      : t("incompleteLink"),
  );

  useEffect(() => {
    if (!token) {
      return;
    }
    verifyHTOEmail(token)
      .then(() => {
        setStatus("success");
        setMessage(
          t("verifiedMessage"),
        );
      })
      .catch((caught: unknown) => {
        setStatus("error");
        setMessage(
          caught instanceof Error
            ? caught.message
            : t("invalidLink"),
        );
      });
  }, [token, t]);

  return (
    <section className="auth-card" aria-live="polite" data-status={status}>
      <p className="eyebrow">{t("verification")}</p>
      <h1>{status === "success" ? t("verifiedTitle") : t("verifyingTitle")}</h1>
      <p>{message}</p>
      {status === "success" ? (
        <p className="hint">{t("approvalTime")}</p>
      ) : null}
    </section>
  );
}

function VerificationContent() {
  const searchParams = useSearchParams();
  return <VerifyEmailResult token={searchParams.get("token")} />;
}

export default function VerifyEmailPage() {
  const t = useTranslations("common");
  return (
    <main className="auth-shell">
      <Suspense fallback={<section className="auth-card">{t("state.loading")}</section>}>
        <VerificationContent />
      </Suspense>
    </main>
  );
}
