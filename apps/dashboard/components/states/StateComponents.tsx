/**
 * The dashboard's half of the state patterns.
 *
 * Same four states as the mobile app, same rules, deliberately not the same
 * code: React Native and the DOM do not share a rendering model, and a shared
 * abstraction over both would be a third thing to maintain that neither side
 * really wants. What *is* shared is the source of truth underneath — every
 * colour and space here is a `var(--…)` from the generated `tokens.css`, so the
 * two apps cannot drift apart on the thing that actually matters.
 *
 * The enterprise context changes the emphasis, not the rules. A bulk order's
 * partial failure is forty people's connectivity rather than one person's, so
 * the counts lead; a stale usage reading is what a budget decision gets made
 * on, so its age is stated rather than implied.
 */

import type { ReactNode } from "react";

export type StatusTone = "neutral" | "progress" | "positive" | "caution" | "negative";

const TONE_CLASS: Record<StatusTone, string> = {
  neutral: "status-pill status-pill-neutral",
  progress: "status-pill status-pill-progress",
  positive: "status-pill status-pill-positive",
  caution: "status-pill status-pill-caution",
  negative: "status-pill status-pill-negative",
};

export function StatusPill({
  family,
  label,
  tone,
  testId,
}: {
  /** Which question this pill answers — announced before the value. */
  family: string;
  label: string;
  tone: StatusTone;
  testId?: string;
}) {
  return (
    <span className={TONE_CLASS[tone]} data-testid={testId}>
      {/* Visually redundant next to a column header, essential to anyone
          listening: a table of five pills is five unattached words otherwise. */}
      <span className="visually-hidden">{family}: </span>
      {label}
    </span>
  );
}

export function UsageMeter({
  label,
  remaining,
  total,
  fraction,
  updatedLabel,
  stale = false,
  explanation,
  testId,
}: {
  label: string;
  remaining: string;
  total: string;
  fraction: number;
  /** `null` means the network has never reported — not "zero used". */
  updatedLabel: string | null;
  stale?: boolean;
  explanation?: string;
  testId?: string;
}) {
  const clamped = Math.min(1, Math.max(0, Number.isFinite(fraction) ? fraction : 0));
  const neverReported = updatedLabel === null;
  const severity = neverReported
    ? "unknown"
    : clamped < 0.05
      ? "critical"
      : clamped < 0.2
        ? "low"
        : "healthy";

  return (
    <div className="usage-meter" data-testid={testId}>
      <div className="usage-meter-header">
        <span className="usage-meter-label">{label}</span>
        <span className="usage-meter-remaining" data-testid={testId && `${testId}-remaining`}>
          {remaining} / {total}
        </span>
      </div>
      <div
        className="usage-meter-track"
        role="progressbar"
        aria-label={`${label}: ${remaining} / ${total}`}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(clamped * 100)}
        data-testid={testId && `${testId}-track`}
      >
        <div
          className="usage-meter-fill"
          data-severity={severity}
          style={{ width: `${clamped * 100}%` }}
        />
      </div>
      <p
        className={stale || neverReported ? "usage-meter-updated is-stale" : "usage-meter-updated"}
        data-testid={testId && `${testId}-updated`}
      >
        {updatedLabel}
      </p>
      {explanation ? <p className="usage-meter-explanation">{explanation}</p> : null}
    </div>
  );
}

export type StateVariant = "empty" | "pending" | "blocked" | "error";

export function StateMessage({
  variant,
  title,
  body,
  footnote,
  action,
  testId,
}: {
  variant: StateVariant;
  title: string;
  body: string;
  footnote?: string;
  action?: ReactNode;
  testId?: string;
}) {
  return (
    <section
      className={`state-message state-message-${variant}`}
      data-testid={testId}
      aria-labelledby={testId ? `${testId}-title` : undefined}
    >
      <h2 className="state-message-title" id={testId ? `${testId}-title` : undefined}>
        {title}
      </h2>
      <p className="state-message-body">{body}</p>
      {footnote ? <p className="state-message-footnote">{footnote}</p> : null}
      {action ? <div className="state-message-actions">{action}</div> : null}
    </section>
  );
}

export function PartialFailureNotice({
  title,
  body,
  noChargeNote,
  action,
  testId,
}: {
  title: string;
  body: string;
  noChargeNote: string;
  action?: ReactNode;
  testId?: string;
}) {
  return (
    <section
      className="state-message state-message-partial"
      data-testid={testId}
      aria-labelledby={testId ? `${testId}-title` : undefined}
    >
      <h2 className="state-message-title" id={testId ? `${testId}-title` : undefined}>
        {title}
      </h2>
      <p className="state-message-body">{body}</p>
      {/* With money already taken, "will this charge us again" is the question
          anybody has before pressing retry on forty lines. */}
      <p className="state-message-footnote" data-testid={testId && `${testId}-no-charge`}>
        {noChargeNote}
      </p>
      {action ? <div className="state-message-actions">{action}</div> : null}
    </section>
  );
}
