"use client";

import { FormEvent, useState } from "react";
import {useLocale} from "next-intl";

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
      setError(caught instanceof Error ? caught.message : "Registration failed.");
    } finally {
      setSubmitting(false);
    }
  }

  if (complete) {
    return (
      <main className="auth-shell">
        <section className="auth-card" aria-live="polite">
          <p className="eyebrow">Registration received</p>
          <h1>Check your email</h1>
          <p>
            We sent a verification link to <strong>{form.email}</strong>. The
            link expires in 24 hours. After verification, DamDam will review
            your NAHCON licence and respond within 24 hours.
          </p>
        </section>
      </main>
    );
  }

  return (
    <main className="auth-shell">
      <section className="auth-card">
        <LocaleSwitcher />
        <p className="eyebrow">DamDam for Hajj Tour Operators</p>
        <h1>Create your business account</h1>
        <p className="intro">
          Register your operator details. Your NAHCON licence will be reviewed
          manually before dashboard access is activated.
        </p>

        <form onSubmit={submit} className="registration-form">
          <label>
            Business name
            <input
              required
              autoComplete="organization"
              value={form.business_name}
              onChange={(event) => update("business_name", event.target.value)}
            />
          </label>
          <label>
            Operator name
            <input
              required
              autoComplete="name"
              value={form.operator_name}
              onChange={(event) => update("operator_name", event.target.value)}
            />
          </label>
          <label>
            Email address
            <input
              required
              type="email"
              autoComplete="email"
              value={form.email}
              onChange={(event) => update("email", event.target.value)}
            />
          </label>
          <label>
            Nigerian phone number
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
            NAHCON licence number
            <input
              required
              value={form.nahcon_licence_number}
              onChange={(event) =>
                update("nahcon_licence_number", event.target.value)
              }
            />
          </label>
          <label>
            Password
            <input
              required
              type="password"
              minLength={8}
              maxLength={128}
              autoComplete="new-password"
              value={form.password}
              onChange={(event) => update("password", event.target.value)}
            />
            <span className="hint">Use at least 8 characters.</span>
          </label>

          {error ? <p className="error" role="alert">{error}</p> : null}
          <button type="submit" disabled={submitting}>
            {submitting ? "Creating account…" : "Create account"}
          </button>
        </form>
      </section>
    </main>
  );
}
