import React, { useState } from 'react';
import { ScrollView, StyleSheet, Text, View } from 'react-native';
import { useTranslation } from 'react-i18next';

import { Banner } from '../../components/Banner/Banner';
import { CallSetupCard, KeypadPreview } from '../../components/CallSetup/CallSetupCard';
import { PartialFailureNotice } from '../../components/PartialFailureNotice/PartialFailureNotice';
import { PrimaryButton } from '../../components/PrimaryButton/PrimaryButton';
import { SecondaryButton } from '../../components/SecondaryButton/SecondaryButton';
import { StateMessage } from '../../components/StateMessage/StateMessage';
import { StatusPill } from '../../components/StatusPill/StatusPill';
import { UsageMeter } from '../../components/UsageMeter/UsageMeter';
import { color, space, typography } from '../../theme/tokens';

/**
 * Every state pattern in the system, on one scrolling screen.
 *
 * This is the chunk's screenshot surface, and it is deliberately not a product
 * screen. Home, Plans, My Line and Account are chunks 18–21; capturing
 * half-built versions of them here would produce a matrix that has to be thrown
 * away the moment they land.
 *
 * What a gallery *can* prove now is the thing screens will otherwise get wrong
 * one at a time: that the tint rule holds, that French does not clip, that
 * nothing depends on colour alone, and that a stale reading still says how
 * stale it is. Each section carries its own testID so the screenshot flow can
 * capture them separately rather than as one unreadable full-page image.
 */

const SECTIONS = ['status', 'usage', 'states', 'calls', 'banners'] as const;
export type GallerySection = (typeof SECTIONS)[number];

function Section({
  id,
  title,
  children,
}: {
  id: GallerySection;
  title: string;
  children: React.ReactNode;
}): React.JSX.Element {
  return (
    <View style={styles.section} testID={`gallery-section-${id}`}>
      <Text accessibilityRole="header" style={styles.sectionTitle}>
        {title}
      </Text>
      <View style={styles.sectionBody}>{children}</View>
    </View>
  );
}

interface GalleryScreenProps {
  /** Render one section only — how the screenshot flow captures them. */
  only?: GallerySection;
}

export function GalleryScreen({ only }: GalleryScreenProps): React.JSX.Element {
  const { t } = useTranslation('states');
  const [retrying, setRetrying] = useState(false);
  const shows = (section: GallerySection) => !only || only === section;

  return (
    <ScrollView
      testID="gallery-screen"
      style={styles.screen}
      contentContainerStyle={styles.content}
    >
      {only ? null : (
        <View style={styles.intro}>
          <Text accessibilityRole="header" style={styles.title} testID="gallery-title">
            {t('gallery.title')}
          </Text>
          <Text style={styles.subtitle}>{t('gallery.subtitle')}</Text>
        </View>
      )}

      {shows('status') ? (
        <Section id="status" title={t('gallery.sectionStatus')}>
          {/* One row per question the schema keeps separate, so a reviewer can
              see at a glance that they are not one status wearing five hats. */}
          <StatusPill
            family="Payment"
            label={t('status.paymentPaid')}
            tone="positive"
            testID="pill-payment"
          />
          <StatusPill
            family="Setup"
            label={t('status.provisioningOutcomeUnknown')}
            tone="progress"
            testID="pill-provisioning"
          />
          <StatusPill
            family="Installation"
            label={t('status.installationNotInstalled')}
            tone="neutral"
            testID="pill-installation"
          />
          <StatusPill
            family="Line"
            label={t('status.activationSuspended')}
            tone="caution"
            testID="pill-activation"
          />
          <StatusPill
            family="Network"
            label={t('status.networkDetached')}
            tone="negative"
            testID="pill-network"
          />
        </Section>
      ) : null}

      {shows('usage') ? (
        <Section id="usage" title={t('gallery.sectionUsage')}>
          <UsageMeter
            label={t('usage.dataLabel')}
            remaining="4.2 GB"
            total="10 GB"
            fraction={0.42}
            updatedLabel={t('usage.updated', { when: '2 min' })}
            testID="usage-healthy"
          />
          <UsageMeter
            label={t('usage.callsLabel')}
            remaining="8 min"
            total="120 min"
            fraction={0.067}
            updatedLabel={t('usage.stale', { when: '3 h' })}
            stale
            explanation={t('usage.staleExplanation')}
            testID="usage-stale"
          />
          <UsageMeter
            label={t('usage.dataLabel')}
            remaining="—"
            total="5 GB"
            fraction={0}
            updatedLabel={null}
            explanation={t('usage.neverUpdatedExplanation')}
            testID="usage-never"
          />
        </Section>
      ) : null}

      {shows('states') ? (
        <Section id="states" title={t('gallery.sectionStates')}>
          <StateMessage
            variant="pending"
            title={t('pendingProvisioning.title')}
            body={t('pendingProvisioning.body')}
            footnote={t('pendingProvisioning.reference', { reference: 'DD-4821' })}
            testID="state-pending"
          />
          <StateMessage
            variant="empty"
            title={t('empty.linesTitle')}
            body={t('empty.linesBody')}
            actionLabel={t('empty.linesAction')}
            onAction={() => undefined}
            testID="state-empty"
          />
          <StateMessage
            variant="blocked"
            title={t('unsupportedDevice.title')}
            body={t('unsupportedDevice.body')}
            footnote={t('unsupportedDevice.beforePaying')}
            actionLabel={t('unsupportedDevice.action')}
            onAction={() => undefined}
            testID="state-blocked"
          />
          <StateMessage
            variant="error"
            title={t('error.title')}
            body={t('error.genericBody')}
            footnote={t('error.reference', { reference: 'DD-4821' })}
            actionLabel={t('error.retry')}
            busyLabel={t('error.retrying')}
            onAction={() => undefined}
            secondaryActionLabel={t('error.contactSupport')}
            onSecondaryAction={() => undefined}
            testID="state-error"
          />
          <PartialFailureNotice
            total={40}
            succeeded={38}
            title={t('partialFailure.title', { failed: 2, total: 40 })}
            body={t('partialFailure.bodyOther', { succeeded: 38 })}
            retryLabel={t('partialFailure.retry', { failed: 2 })}
            noChargeNote={t('partialFailure.noCharge')}
            retrying={retrying}
            retryingLabel={t('error.retrying')}
            onRetry={() => setRetrying(true)}
            testID="state-partial"
          />
        </Section>
      ) : null}

      {shows('calls') ? (
        <Section id="calls" title={t('gallery.sectionCalls')}>
          {/* The two modes side by side. They bill, route and fail
              differently, so which one is about to happen is stated rather
              than inferred from the screen you are on. */}
          <CallSetupCard
            mode="carrier"
            outboundIdentity="+234 801 234 5678"
            payer={{ kind: 'personal' }}
            destination="Nigeria mobile"
            ratePerMinute="₦12"
            currency="NGN"
            onCall={() => undefined}
            testID="call-carrier"
          />
          <CallSetupCard
            mode="internet"
            outboundIdentity={null}
            payer={{ kind: 'work', organization: 'Acme Ltd' }}
            destination="United Kingdom mobile"
            ratePerMinute={null}
            currency="NGN"
            onCall={() => undefined}
            testID="call-internet-unpriced"
          />
          <StateMessage
            variant="blocked"
            title={t('calls.micDeniedTitle')}
            body={t('calls.micDeniedBody')}
            footnote={t('calls.micDeniedAlternative')}
            actionLabel={t('calls.micDeniedAction')}
            onAction={() => undefined}
            testID="call-mic-denied"
          />
          <StateMessage
            variant="blocked"
            title={t('calls.lowCreditTitle')}
            body={t('calls.lowCreditBody', { balance: '₦40', required: '₦120' })}
            actionLabel={t('calls.lowCreditAction')}
            onAction={() => undefined}
            testID="call-low-credit"
          />
          <StateMessage
            variant="empty"
            title={t('calls.unavailableTitle')}
            body={t('calls.unavailableBody')}
            testID="call-unavailable"
          />
          <KeypadPreview testID="call-keypad" />
        </Section>
      ) : null}

      {shows('banners') ? (
        <Section id="banners" title={t('gallery.sectionBanners')}>
          <Banner tone="info" message={t('outcomeUnknown.reassurance')} testID="banner-info" />
          <Banner
            tone="warning"
            message={t('usage.staleExplanation')}
            testID="banner-warning"
          />
          <Banner tone="error" message={t('error.genericBody')} testID="banner-error" />
          <Banner
            tone="neutral"
            message={t('usage.neverUpdatedExplanation')}
            testID="banner-neutral"
          />
          <View style={styles.buttonRow}>
            <PrimaryButton
              label={t('error.retry')}
              onPress={() => undefined}
              testID="gallery-primary-button"
            />
            <SecondaryButton
              label={t('error.contactSupport')}
              onPress={() => undefined}
              testID="gallery-secondary-button"
            />
          </View>
        </Section>
      ) : null}
    </ScrollView>
  );
}

export const GALLERY_SECTIONS = SECTIONS;

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: color.gray50 },
  content: { padding: space.space4, gap: space.space6, paddingBottom: space.space12 },
  intro: { gap: space.space2 },
  title: {
    fontSize: typography.heading1.fontSize,
    lineHeight: typography.heading1.lineHeight,
    fontWeight: typography.heading1.fontWeight,
    color: color.gray900,
  },
  subtitle: {
    fontSize: typography.body.fontSize,
    lineHeight: typography.body.lineHeight,
    color: color.gray700,
  },
  section: { gap: space.space3 },
  sectionTitle: {
    fontSize: typography.heading3.fontSize,
    lineHeight: typography.heading3.lineHeight,
    fontWeight: typography.heading3.fontWeight,
    color: color.gray900,
  },
  sectionBody: { gap: space.space4 },
  buttonRow: { gap: space.space3 },
});
