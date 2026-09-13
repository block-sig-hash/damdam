"use client";

import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";

import { LocaleSwitcher } from "@/components/LocaleSwitcher";
import {
  getEligibility,
  listCalls,
  type AttemptView,
  type EligibilityView,
} from "@/lib/callingClient";
import {
  clearConsumerSession,
  readConsumerSession,
  type ConsumerSession,
} from "@/lib/consumerSession";
import { confirmConsumerSignIn, requestConsumerSignIn } from "@/lib/consumerAuth";
import { mediaSupport } from "@/lib/calling/adapter";
import { requestMicrophone } from "@/lib/calling/microphone";
import { resolveCallAdapter } from "@/lib/calling/registry";
import {
  BrowserCallSession,
  failureCodeFor,
  type CallSnapshot,
} from "@/lib/calling/session";

/**
 * The consumer calling area (US-48).
 *
 * Its own route, its own credential, its own sign-in. `/home` belongs to an
 * organization operator and `/admin` to internal staff; neither token opens
 * this page, because nothing here ever reads them. A staff member who wants to
 * make a personal call signs in as themselves — which is the point, not an
 * inconvenience.
 *
 * **Personal only.** There is no organization payer on this surface and no
 * request field through which one could be asked for. A member's work calls
 * belong somewhere their employer can see them, and that is not here.
 *
 * **No eSIM, no membership.** Nothing on this path consults an entitlement, an
 * installation or a tenant. A brand-new account with an email address and a
 * balance can call.
 *
 * **A refresh reconciles; it never redials.** The live attempt lives on the
 * server and is remembered here by id alone. On mount the page asks what that
 * attempt is doing rather than starting another one — the most likely way a
 * browser client would otherwise bill twice.
 */

const DIGITS = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "*", "0", "#"];
const CURRENCY = "NGN";

export default function CallsPage() {
  const [session, setSession] = useState<ConsumerSession | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setSession(readConsumerSession());
      setReady(true);
    }, 0);
    return () => window.clearTimeout(timer);
  }, []);

  if (!ready) {
    return <main className="dashboard-shell" data-testid="calls-loading" />;
  }

  return session ? (
    <CallingArea
      session={session}
      onSignOut={() => {
        clearConsumerSession();
        setSession(null);
      }}
    />
  ) : (
    <ConsumerSignIn onSignedIn={() => setSession(readConsumerSession())} />
  );
}

function ConsumerSignIn({ onSignedIn }: { onSignedIn: () => void }) {
  const t = useTranslations("calling");
  const [email, setEmail] = useState("");
  const [token, setToken] = useState("");
  const [sent, setSent] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function send(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await requestConsumerSignIn(email, "en");
      setSent(true);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("signIn.failed"));
    } finally {
      setBusy(false);
    }
  }

  async function confirm(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await confirmConsumerSignIn(token);
      onSignedIn();
    } catch {
      setError(t("signIn.failed"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="auth-shell">
      <section className="auth-card compact-card">
        <LocaleSwitcher />
        <p className="eyebrow">{t("title")}</p>
        <h1>{t("signIn.heading")}</h1>
        {/* Says plainly that a staff or operator sign-in does not open this. */}
        <p className="intro">{t("signIn.intro")}</p>
        <form onSubmit={send} className="single-column-form">
          <label htmlFor="calls-email">{t("signIn.emailLabel")}</label>
          <input
            id="calls-email"
            data-testid="calls-email"
            type="email"
            required
            value={email}
            onChange={(event) => setEmail(event.target.value)}
          />
          <button type="submit" data-testid="calls-send-code" disabled={busy}>
            {t("signIn.send")}
          </button>
        </form>
        {sent ? (
          <>
            {/* Identical whether or not the account exists — chunk 06's rule. */}
            <p role="status" data-testid="calls-code-sent">
              {t("signIn.sent")}
            </p>
            <form onSubmit={confirm} className="single-column-form">
              <label htmlFor="calls-token">{t("signIn.codeLabel")}</label>
              <input
                id="calls-token"
                data-testid="calls-token"
                required
                value={token}
                onChange={(event) => setToken(event.target.value)}
              />
              <button type="submit" data-testid="calls-confirm" disabled={busy}>
                {t("signIn.confirm")}
              </button>
            </form>
          </>
        ) : null}
        {error ? (
          <p role="alert" data-testid="calls-signin-error">
            {error}
          </p>
        ) : null}
      </section>
    </main>
  );
}

function CallingArea({
  session,
  onSignOut,
}: {
  session: ConsumerSession;
  onSignOut: () => void;
}) {
  const t = useTranslations("calling");
  const [destination, setDestination] = useState("");
  const [eligibility, setEligibility] = useState<EligibilityView | null>(null);
  const [pricing, setPricing] = useState(false);
  const [eligibilityError, setEligibilityError] = useState<string | null>(null);
  const [history, setHistory] = useState<AttemptView[]>([]);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [snapshot, setSnapshot] = useState<CallSnapshot | null>(null);
  const callRef = useRef<BrowserCallSession | null>(null);
  const support = useMemo(() => mediaSupport(), []);

  useEffect(() => {
    const call = new BrowserCallSession({
      userId: session.userId,
      deviceId: session.userId,
      currency: CURRENCY,
      adapter: resolveCallAdapter(),
      requestMicrophone,
      onChange: setSnapshot,
    });
    callRef.current = call;
    // Deferred to a macrotask, the idiom this app already uses for effect-driven
    // state (see `app/home/page.tsx`): setting state synchronously inside an
    // effect cascades a render, and the lint rule is right to refuse it.
    const timer = window.setTimeout(() => {
      setSnapshot(call.snapshot());
      // Refresh, restored tab, second tab, machine waking from sleep — all the
      // same question, all answered by asking the server, never by redialing.
      call.reconcile().catch(() => undefined);
    }, 0);

    const leave = () => {
      // Best effort only. V03's cutoff is what bounds the spend.
      call.releaseOnUnload().catch(() => undefined);
    };
    window.addEventListener("pagehide", leave);

    return () => {
      window.clearTimeout(timer);
      window.removeEventListener("pagehide", leave);
      call.dispose();
      callRef.current = null;
    };
  }, [session.userId]);

  const loadHistory = useCallback(() => {
    setHistoryError(null);
    listCalls(20)
      .then(setHistory)
      .catch((caught) => setHistoryError(failureCodeFor(caught)));
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => { loadHistory(); }, 0);
    return () => window.clearTimeout(timer);
  }, [loadHistory]);

  useEffect(() => {
    let cancelled = false;
    const timer = window.setTimeout(() => {
      if (!destination.startsWith("+") || destination.length < 7) {
        setEligibility(null);
        setEligibilityError(null);
        return;
      }
      setPricing(true);
      setEligibilityError(null);
      priceDestination();
    }, 0);

    function priceDestination() {
      getEligibility({ destination, currency: CURRENCY })
        .then((view) => {
          if (!cancelled) setEligibility(view);
        })
        .catch((caught) => {
          if (!cancelled) {
            setEligibility(null);
            setEligibilityError(failureCodeFor(caught));
          }
        })
        .finally(() => {
          if (!cancelled) setPricing(false);
        });
    }

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [destination]);

  const live =
    snapshot !== null &&
    ["preparing", "connecting", "ringing", "answered"].includes(snapshot.phase);
  const callable =
    !live &&
    support === "supported" &&
    destination.startsWith("+") &&
    destination.length > 6 &&
    eligibility !== null &&
    eligibility.route_enabled &&
    eligibility.fundable;

  const failureCode =
    support === "insecure_context"
      ? "insecure_context"
      : support === "unsupported"
        ? "browser_unsupported"
        : snapshot?.phase === "failed"
          ? snapshot.failureCode
          : null;

  return (
    <main className="dashboard-shell">
      <section className="manifest-card wide-card">
        <div className="page-heading">
          <div>
            <p className="eyebrow">{t("title")}</p>
            <h1>{t("subtitle")}</h1>
          </div>
          <div>
            <LocaleSwitcher />
            <button type="button" data-testid="calls-sign-out" onClick={onSignOut}>
              {t("signIn.signOut")}
            </button>
          </div>
        </div>

        {/* Who pays, stated before the call rather than discovered after it. */}
        <section data-testid="calls-personal">
          <h2>{t("personal.heading")}</h2>
          <p>{t("personal.body")}</p>
        </section>

        {live && snapshot ? (
          <section data-testid="calls-in-progress" aria-live="polite">
            <p data-testid="calls-phase">{t(`phase.${snapshot.phase}`)}</p>
            <p>{snapshot.destinationE164}</p>
            <p>
              {snapshot.identityE164
                ? t("preview.identity", { number: snapshot.identityE164 })
                : t("preview.identityUnknown")}
            </p>
            <p>{t("elapsed.estimate")}</p>
            <p data-testid="calls-unload-note">{t("unsupported.leaving")}</p>
            <div>
              <button
                type="button"
                data-testid="calls-mute"
                aria-pressed={snapshot.muted}
                onClick={() => {
                  callRef.current?.setMuted(!snapshot.muted).catch(() => undefined);
                }}
              >
                {snapshot.muted ? t("action.unmute") : t("action.mute")}
              </button>
              <button
                type="button"
                data-testid="calls-hang-up"
                onClick={() => {
                  callRef.current
                    ?.hangup()
                    .then(loadHistory)
                    .catch(() => undefined);
                }}
              >
                {t("action.hangUp")}
              </button>
            </div>
            <div role="group" aria-label={t("action.keypad")}>
              {DIGITS.map((digit) => (
                <button
                  key={digit}
                  type="button"
                  data-testid={`calls-dtmf-${digit}`}
                  onClick={() => {
                    callRef.current?.sendDigit(digit).catch(() => undefined);
                  }}
                >
                  {digit}
                </button>
              ))}
            </div>
          </section>
        ) : (
          <section data-testid="calls-setup">
            <label htmlFor="calls-destination">{t("destination.label")}</label>
            <input
              id="calls-destination"
              data-testid="calls-destination"
              inputMode="tel"
              placeholder={t("destination.hint")}
              value={destination}
              onChange={(event) => setDestination(event.target.value)}
            />
            <div role="group" aria-label={t("action.keypad")}>
              {DIGITS.map((digit) => (
                <button
                  key={digit}
                  type="button"
                  data-testid={`calls-digit-${digit}`}
                  onClick={() =>
                    setDestination((current) =>
                      current === "" ? `+${digit}` : `${current}${digit}`,
                    )
                  }
                >
                  {digit}
                </button>
              ))}
              <button
                type="button"
                data-testid="calls-backspace"
                onClick={() => setDestination((current) => current.slice(0, -1))}
              >
                {t("destination.clear")}
              </button>
            </div>

            <section data-testid="calls-preview">
              <h2>{t("preview.heading")}</h2>
              {pricing ? (
                <p>{t("preview.pricing")}</p>
              ) : eligibilityError ? (
                <p data-testid="calls-preview-error">{t("preview.unavailable")}</p>
              ) : eligibility ? (
                <>
                  <p data-testid="calls-rate">
                    {t("preview.rate", {
                      amount: eligibility.rate_per_minute_amount,
                      currency: eligibility.currency,
                    })}
                  </p>
                  <p>
                    {t("preview.maximum", {
                      amount: eligibility.max_charge_amount,
                      currency: eligibility.currency,
                      minutes: Math.max(1, Math.floor(eligibility.max_seconds / 60)),
                    })}
                  </p>
                  <p>
                    {t("preview.available", {
                      amount: eligibility.available_amount,
                      currency: eligibility.currency,
                    })}
                  </p>
                  {!eligibility.route_enabled ? (
                    <p data-testid="calls-route-disabled">{t("preview.routeDisabled")}</p>
                  ) : null}
                  {eligibility.route_enabled && !eligibility.fundable ? (
                    <p data-testid="calls-not-fundable">{t("preview.notFundable")}</p>
                  ) : null}
                </>
              ) : (
                <p>{t("destination.hint")}</p>
              )}
            </section>

            <button
              type="button"
              data-testid="calls-place"
              disabled={!callable}
              onClick={() => {
                callRef.current?.place(destination).catch(() => undefined);
              }}
            >
              {t("action.call")}
            </button>
          </section>
        )}

        {failureCode ? (
          <section data-testid="calls-failure" role="alert">
            <p>{messageFor(t, failureCode)}</p>
            <button
              type="button"
              data-testid="calls-retry"
              onClick={() => {
                callRef.current?.retry().catch(() => undefined);
              }}
            >
              {t("action.retry")}
            </button>
          </section>
        ) : null}

        <section data-testid="calls-history">
          <h2>{t("history.heading")}</h2>
          {historyError ? (
            <p>{t("history.error")}</p>
          ) : history.length === 0 ? (
            <p>{t("history.empty")}</p>
          ) : (
            <ul>
              {history.map((attempt) => (
                <li key={attempt.attempt_id} data-testid={`calls-row-${attempt.attempt_id}`}>
                  <span>{attempt.destination_e164}</span>
                  <span data-testid={`calls-cost-${attempt.attempt_id}`}>
                    {/* A missing charge is "not settled yet", never zero. */}
                    {attempt.charge === null
                      ? attempt.answered_at === null
                        ? t("history.unanswered")
                        : t("history.costPending")
                      : attempt.charge.is_final
                        ? t("history.cost", {
                            amount: attempt.charge.amount,
                            currency: attempt.charge.currency,
                          })
                        : t("history.costProvisional", {
                            amount: attempt.charge.amount,
                            currency: attempt.charge.currency,
                          })}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </section>
    </main>
  );
}

/** Unknown codes fall back rather than rendering a raw key at somebody. */
function messageFor(t: ReturnType<typeof useTranslations>, code: string): string {
  const key = `failure.${code}`;
  const message = t(key);
  return message === key ? t("failure.generic") : message;
}
