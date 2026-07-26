"use client";

import { FormEvent, useState } from "react";
import {useLocale, useTranslations} from "next-intl";

import {LocaleSwitcher} from "@/components/LocaleSwitcher";
import type {AppLocale} from "@/i18n/locale";
import { registerHTO } from "@/lib/api";

const initialForm = {
  business_name: "",
  operator_name: "",
  email: "",
  password: "",
  phone_number: "",
  nahcon_licence_number: "",
};

export default function RegistrationPage() {
  const locale = useLocale() as AppLocale;
  const t = useTranslations("auth");
  const [form, setForm] = useState(initialForm);
  const [submitting, setSubmitting] = useState(false);
  const [complete, setComplete] = useState(false);
  const [error, setError] = useState("");

  function update(field: keyof typeof form, value: string) {
    setForm((current) => ({ ...current, [field]: value }));
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    try {
      await registerHTO({...form, locale});
      setComplete(true);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("registrationFailed"));
    } finally {
      setSubmitting(false);
    }
  }

  if (complete) {
    return (
      <main className="auth-shell">
        <section className="auth-card" aria-live="polite">
          <p className="eyebrow">{t("registrationReceived")}</p>
          <h1>{t("checkEmail")}</h1>
          <p>{t("verificationSent", {email: form.email})}</p>
        </section>
      </main>
    );
  }

  return (
    <main className="auth-shell">
      <section className="auth-card">
        <LocaleSwitcher />
        <p className="eyebrow">{t("operatorEyebrow")}</p>
        <h1>{t("createTitle")}</h1>
        <p className="intro">{t("createIntro")}</p>

        <form onSubmit={submit} className="registration-form">
          <label>
            {t("businessName")}
            <input
              required
              autoComplete="organization"
              value={form.business_name}
              onChange={(event) => update("business_name", event.target.value)}
            />
          </label>
          <label>
            {t("operatorName")}
            <input
              required
              autoComplete="name"
              value={form.operator_name}
              onChange={(event) => update("operator_name", event.target.value)}
            />
          </label>
          <label>
            {t("email")}
            <input
              required
              type="email"
              autoComplete="email"
              value={form.email}
              onChange={(event) => update("email", event.target.value)}
            />
          </label>
          <label>
            {t("nigerianPhone")}
            <input
              required
              type="tel"
              inputMode="numeric"
              pattern="0(70|80|81|90|91)[0-9]{8}"
              placeholder="08012345678"
              autoComplete="tel"
              value={form.phone_number}
              onChange={(event) => update("phone_number", event.target.value)}
            />
          </label>
          <label>
            {t("licence")}
            <input
              required
              value={form.nahcon_licence_number}
              onChange={(event) =>
                update("nahcon_licence_number", event.target.value)
              }
            />
          </label>
          <label>
            {t("password")}
            <input
              required
              type="password"
              minLength={8}
              maxLength={128}
              autoComplete="new-password"
              value={form.password}
              onChange={(event) => update("password", event.target.value)}
            />
            <span className="hint">{t("passwordHint")}</span>
          </label>

          {error ? <p className="error" role="alert">{error}</p> : null}
          <button type="submit" disabled={submitting}>
            {submitting ? t("creating") : t("create")}
          </button>
        </form>
      </section>
    </main>
  );
}
