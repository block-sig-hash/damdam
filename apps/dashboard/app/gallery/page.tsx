import { getTranslations } from "next-intl/server";

import {
  PartialFailureNotice,
  StateMessage,
  StatusPill,
  UsageMeter,
} from "@/components/states/StateComponents";

/**
 * Every state pattern on one page, at `/gallery`.
 *
 * Deliberately not a product screen. People, Orders, Lines and Billing belong
 * to chunks 22–24, and half-built versions of them here would be evidence of
 * nothing. What a gallery can prove today is what those screens will otherwise
 * each get wrong separately: that the tint rule holds, that French does not
 * clip, that no state depends on colour alone, and that a stale usage reading
 * still says how stale it is.
 *
 * It is also the dashboard's screenshot surface. Narrow the viewport, raise the
 * text size or switch language and this page is where that shows up first.
 */
export default async function GalleryPage() {
  const t = await getTranslations("states");

  return (
    <main className="dashboard-page gallery-page">
      <header>
        <p className="eyebrow">{t("gallery.title")}</p>
        <h1>{t("gallery.title")}</h1>
        <p className="intro">{t("gallery.subtitle")}</p>
      </header>

      <section className="gallery-section" data-testid="gallery-section-status">
        <h2>{t("gallery.sectionStatus")}</h2>
        {/* One pill per question the schema keeps separate (data-model.md
            §6.44). Shown together so it is obvious they are five answers, not
            one status wearing five hats. */}
        <div className="gallery-row">
          <StatusPill
            family={t("status.familyPayment")}
            label={t("status.paymentPaid")}
            tone="positive"
            testId="pill-payment"
          />
          <StatusPill
            family={t("status.familyProvisioning")}
            label={t("status.provisioningOutcomeUnknown")}
            tone="progress"
            testId="pill-provisioning"
          />
          <StatusPill
            family={t("status.familyInstallation")}
            label={t("status.installationNotInstalled")}
            tone="neutral"
            testId="pill-installation"
          />
          <StatusPill
            family={t("status.familyActivation")}
            label={t("status.activationSuspended")}
            tone="caution"
            testId="pill-activation"
          />
          <StatusPill
            family={t("status.familyNetwork")}
            label={t("status.networkDetached")}
            tone="negative"
            testId="pill-network"
          />
        </div>
      </section>

      <section className="gallery-section" data-testid="gallery-section-usage">
        <h2>{t("gallery.sectionUsage")}</h2>
        <div className="gallery-stack">
          <UsageMeter
            label={t("usage.dataLabel")}
            remaining="412 GB"
            total="1 TB"
            fraction={0.41}
            updatedLabel={t("usage.updated", { when: "2 min" })}
            testId="usage-healthy"
          />
          <UsageMeter
            label={t("usage.callsLabel")}
            remaining="140 min"
            total="4 000 min"
            fraction={0.035}
            updatedLabel={t("usage.stale", { when: "3 h" })}
            stale
            explanation={t("usage.staleExplanation")}
            testId="usage-stale"
          />
          <UsageMeter
            label={t("usage.dataLabel")}
            remaining="—"
            total="500 GB"
            fraction={0}
            updatedLabel={null}
            explanation={t("usage.neverUpdatedExplanation")}
            testId="usage-never"
          />
        </div>
      </section>

      <section className="gallery-section" data-testid="gallery-section-states">
        <h2>{t("gallery.sectionStates")}</h2>
        <div className="gallery-stack">
          <StateMessage
            variant="pending"
            title={t("pending.title", { count: 40 })}
            body={t("pending.body")}
            footnote={t("pending.footnote", { reference: "DD-4821" })}
            testId="state-pending"
          />
          <StateMessage
            variant="empty"
            title={t("empty.peopleTitle")}
            body={t("empty.peopleBody")}
            action={<button type="button">{t("empty.peopleAction")}</button>}
            testId="state-empty"
          />
          <StateMessage
            variant="blocked"
            title={t("blocked.title")}
            body={t("blocked.body", { count: 3 })}
            footnote={t("blocked.footnote")}
            action={<button type="button">{t("blocked.action", { count: 3 })}</button>}
            testId="state-blocked"
          />
          <StateMessage
            variant="error"
            title={t("error.title")}
            body={t("error.body")}
            footnote={t("error.footnote", { reference: "DD-4821" })}
            action={
              <>
                <button type="button">{t("error.retry")}</button>
                <button type="button" className="secondary-button">
                  {t("error.contactSupport")}
                </button>
              </>
            }
            testId="state-error"
          />
          <PartialFailureNotice
            title={t("partialFailure.title", { failed: 2, total: 40 })}
            body={t("partialFailure.body", { succeeded: 38 })}
            noChargeNote={t("partialFailure.noCharge")}
            action={<button type="button">{t("partialFailure.retry", { failed: 2 })}</button>}
            testId="state-partial"
          />
        </div>
      </section>
    </main>
  );
}
