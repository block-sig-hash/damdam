"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";

import { LocaleSwitcher } from "@/components/LocaleSwitcher";
import {
  completeMemberLogin,
  requestMemberLogin,
} from "@/lib/memberAuth";

export default function EnterpriseLoginPage() {
  const t = useTranslations("auth");
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const token = new URLSearchParams(window.location.search).get("token");
    if (!token) return;
    const timer = window.setTimeout(() => {
      setVerifying(true);
      setBusy(true);
      completeMemberLogin(token)
        .then(() => router.replace("/people"))
        .catch((caught: unknown) => {
          setError(caught instanceof Error ? caught.message : t("signInFailed"));
          setBusy(false);
          setVerifying(false);
        });
    }, 0);
    return () => window.clearTimeout(timer);
  }, [router, t]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await requestMemberLogin(email);
      setSent(true);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("signInFailed"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="auth-shell">
      <section className="auth-card compact-card">
        <LocaleSwitcher />
        <p className="eyebrow">{t("enterpriseDashboard")}</p>
        <h1>{t("enterpriseSignIn")}</h1>
        {busy && verifying ? (
          <p>{t("verifyingMemberLink")}</p>
        ) : sent ? (
          <p role="status">{t("memberLinkSent")}</p>
        ) : (
          <form onSubmit={submit} className="single-column-form">
            <p className="intro">{t("enterpriseSignInIntro")}</p>
            <label>
              {t("email")}
              <input
                required
                type="email"
                autoComplete="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
              />
            </label>
            {error ? <p className="error" role="alert">{error}</p> : null}
            <button type="submit" disabled={busy}>
              {busy ? t("sendingMemberLink") : t("sendMemberLink")}
            </button>
          </form>
        )}
      </section>
    </main>
  );
}
