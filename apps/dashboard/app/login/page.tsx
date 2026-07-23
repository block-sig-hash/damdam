"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import {useTranslations} from "next-intl";

import {LocaleSwitcher} from "@/components/LocaleSwitcher";
import { loginHTO } from "@/lib/api";

export default function LoginPage() {
  const t = useTranslations("auth");
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    try {
      await loginHTO(email, password);
      router.push("/home");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("signInFailed"));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="auth-shell">
      <section className="auth-card compact-card">
        <LocaleSwitcher />
        <p className="eyebrow">{t("dashboard")}</p>
        <h1>{t("signIn")}</h1>
        <p className="intro">{t("signInIntro")}</p>
        <form onSubmit={submit} className="single-column-form">
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
          <label>
            {t("password")}
            <input
              required
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </label>
          {error ? <p className="error" role="alert">{error}</p> : null}
          <button type="submit" disabled={submitting}>
            {submitting ? t("signingIn") : t("signIn")}
          </button>
        </form>
      </section>
    </main>
  );
}
