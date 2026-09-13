import React from 'react';
import { useTranslation } from 'react-i18next';
import { Platform, ScrollView, StyleSheet, Text, View } from 'react-native';
import type { InstallationCredential } from '../../api/lineClient';
import { splitActivationCode } from '../../api/lineClient';
import { Banner } from '../../components/Banner/Banner';
import { PrimaryButton } from '../../components/PrimaryButton/PrimaryButton';
import { SecondaryButton } from '../../components/SecondaryButton/SecondaryButton';
import { StateMessage } from '../../components/StateMessage/StateMessage';
import type { ScreenPrivacyResult } from '../../services/screenPrivacy';
import { color, radius, space, typography } from '../../theme/tokens';
import type { ActivationGuide } from '../EsimActivation/activationGuides';
import { InstallationQr } from './InstallationQr';

interface InstallProfileScreenProps {
  credential: InstallationCredential | null;
  guide: ActivationGuide;
  privacy: ScreenPrivacyResult | null;
  /** True while the grant is being issued and spent. */
  loading: boolean;
  busy: boolean;
  errorMessage: string | null;
  /** Set once the platform's direct install has been invoked. */
  directInstallInvoked: boolean;
  onReveal: () => void;
  onDirectInstall: () => void;
  onConfirmInstalled: () => void;
  onReportFailed: () => void;
  onBack: () => void;
}

/**
 * The one screen that shows an eSIM activation code (US-38, AC-38.1, AC-38.2).
 *
 * Everything unusual about it comes from one property: a Telnyx profile is
 * one-time use and **cannot be re-downloaded**. A code that leaks is a
 * paid-for line somebody else can install, and there is nothing to rotate
 * afterwards — only another purchase. So:
 *
 * - The code is fetched on an explicit tap, not on mount. Opening the screen to
 *   read the instructions should not spend the profile.
 * - The window is put under `FLAG_SECURE` where the platform has it, and where
 *   it does not — iOS offers no way to prevent a screenshot — the screen
 *   **says so** rather than rendering the code as though it were protected.
 * - Nothing here writes the code anywhere. Not to state that outlives the
 *   screen, not to storage, not to a log. It is held for the render and gone.
 *
 * The install path differs by platform because the platforms genuinely differ:
 * Android exposes `EuiccManager`, which can hand the profile straight to the
 * system, and iOS has no equivalent, so it gets the manual steps for its own
 * settings app. Neither is dressed up as the other, and neither claims a silent
 * install — the system asks the customer to confirm, on both.
 */
export function InstallProfileScreen({
  credential,
  guide,
  privacy,
  loading,
  busy,
  errorMessage,
  directInstallInvoked,
  onReveal,
  onDirectInstall,
  onConfirmInstalled,
  onReportFailed,
  onBack,
}: InstallProfileScreenProps): React.JSX.Element {
  const { t } = useTranslation('line');
  const parts = credential ? splitActivationCode(credential.lpa) : null;

  return (
    <ScrollView contentContainerStyle={styles.screen} testID="install-profile">
      <Text style={styles.title}>{t('install.title')}</Text>

      {/*
        Stated before the code is on screen, not after. A warning that appears
        alongside a secret has already missed the moment it was for.
      */}
      {privacy === 'protected' ? (
        <Banner
          tone="info"
          testID="install-privacy-protected"
          message={t('install.privacyProtected')}
        />
      ) : (
        <Banner
          tone="warning"
          testID="install-privacy-unprotected"
          message={
            Platform.OS === 'ios'
              ? t('install.privacyIosWarning')
              : t('install.privacyFailedWarning')
          }
        />
      )}

      {errorMessage ? (
        <StateMessage
          variant="error"
          title={t('install.errorTitle')}
          body={errorMessage}
          actionLabel={t('install.retry')}
          onAction={onReveal}
          busy={loading || privacy === null}
          secondaryActionLabel={t('install.back')}
          onSecondaryAction={onBack}
          testID="install-error"
        />
      ) : null}

      {credential === null ? (
        <StateMessage
          variant="pending"
          title={t('install.revealTitle')}
          body={t('install.revealBody')}
          footnote={t('install.revealFootnote')}
          actionLabel={t('install.revealAction')}
          onAction={onReveal}
          busy={loading || privacy === null}
          busyLabel={t('install.revealing')}
          testID="install-reveal"
        />
      ) : (
        <>
          {credential.delivery_count > 1 ? (
            /*
              Not a refusal. The customer may well be re-reading the code after a
              screen lock, and blocking that strands them. But they are entitled
              to know it has been shown before, because a one-time profile shown
              twice may already be installed elsewhere.
            */
            <Banner
              tone="warning"
              testID="install-shown-before"
              message={t('install.shownBefore', {
                count: credential.delivery_count,
              })}
            />
          ) : null}

          <View style={styles.card} testID="install-code">
            <Text style={styles.cardLabel}>{t('install.qrTitle')}</Text>
            <InstallationQr lpa={credential.lpa} />
            <Text style={styles.footnote}>{t('install.qrHint')}</Text>
            <Text style={styles.cardLabel}>{t('install.manualTitle')}</Text>
            {parts ? (
              <>
                <Field
                  label={t('install.smdpLabel')}
                  value={parts.smdpAddress}
                  testID="install-smdp"
                />
                <Field
                  label={t('install.activationCodeLabel')}
                  value={parts.activationCode}
                  testID="install-activation-code"
                />
              </>
            ) : (
              /*
                An LPA that does not split into the documented three parts is not
                guessed at. A wrong split fails in a way that looks like a bad
                profile; the whole string always works where a code is accepted.
              */
              <Field
                label={t('install.wholeCodeLabel')}
                value={credential.lpa}
                testID="install-whole-code"
              />
            )}
            <Text style={styles.footnote}>{t('install.manualHint')}</Text>
          </View>

          {Platform.OS === 'android' ? (
            <PrimaryButton
              label={t('install.directAction')}
              onPress={onDirectInstall}
              loading={busy}
              testID="install-direct"
            />
          ) : null}

          <View style={styles.card} testID="install-guide">
            <Text style={styles.cardLabel}>
              {t('install.guideTitle', { device: guide.name })}
            </Text>
            {guide.steps.map((step, index) => (
              <Text key={step.instruction} style={styles.step}>
                {`${index + 1}. ${step.instruction}`}
              </Text>
            ))}
            {guide.contentStatus === 'placeholder' ? (
              /*
                Chunk 04's guides are generic for most Android families. Saying
                so beats presenting generic steps as if they were this handset's.
              */
              <Text style={styles.footnote} testID="install-guide-generic">
                {t('install.guideGeneric')}
              </Text>
            ) : null}
          </View>

          {directInstallInvoked ? (
            <Banner
              tone="info"
              testID="install-invoked"
              message={t('install.invoked')}
            />
          ) : null}

          <Text style={styles.footnote} testID="install-no-reinstall">
            {t('install.noReinstall')}
          </Text>

          {/*
            The device reports what happened, and the customer is the only one
            who can see the device. Both answers are offered: an install that
            failed, recorded as succeeded, is how somebody is told their line is
            ready while nothing is on the phone.
          */}
          <PrimaryButton
            label={t('install.confirmAction')}
            onPress={onConfirmInstalled}
            loading={busy}
            testID="install-confirm"
          />
          <SecondaryButton
            label={t('install.failedAction')}
            onPress={onReportFailed}
            disabled={busy}
            testID="install-failed"
          />
        </>
      )}

      <SecondaryButton
        label={t('install.back')}
        onPress={onBack}
        testID="install-back"
      />
    </ScrollView>
  );
}

function Field({
  label,
  value,
  testID,
}: {
  label: string;
  value: string;
  testID: string;
}): React.JSX.Element {
  return (
    <View style={styles.field}>
      <Text style={styles.cardLabel}>{label}</Text>
      {/*
        Selectable rather than a copy button: a clipboard write is a copy of the
        profile living outside this screen for as long as the clipboard holds it,
        readable by anything that asks.
      */}
      <Text style={styles.fieldValue} selectable testID={testID}>
        {value}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: {
    flexGrow: 1,
    padding: space.space5,
    gap: space.space4,
    backgroundColor: color.gray50,
  },
  title: {
    fontSize: typography.heading1.fontSize,
    lineHeight: typography.heading1.lineHeight,
    fontWeight: typography.heading1.fontWeight,
    color: color.gray900,
  },
  card: {
    padding: space.space4,
    borderRadius: radius.card,
    borderWidth: 1,
    borderColor: color.gray200,
    backgroundColor: color.white,
    gap: space.space3,
  },
  cardLabel: {
    fontSize: typography.caption.fontSize,
    lineHeight: typography.caption.lineHeight,
    color: color.gray700,
  },
  field: { gap: space.space1 },
  fieldValue: {
    fontSize: typography.bodyLarge.fontSize,
    lineHeight: typography.bodyLarge.lineHeight,
    color: color.gray900,
  },
  step: {
    fontSize: typography.body.fontSize,
    lineHeight: typography.body.lineHeight,
    color: color.gray900,
  },
  footnote: {
    fontSize: typography.caption.fontSize,
    lineHeight: typography.caption.lineHeight,
    color: color.gray700,
  },
});
