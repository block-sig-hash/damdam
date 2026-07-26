import React, { useState } from 'react';
import { ScrollView, StyleSheet, Text, View } from 'react-native';
import { Banner } from '../../components/Banner/Banner';
import { DestructiveButton } from '../../components/DestructiveButton/DestructiveButton';
import { PrimaryButton } from '../../components/PrimaryButton/PrimaryButton';
import { SecondaryButton } from '../../components/SecondaryButton/SecondaryButton';
import { color, radius, space, typography } from '../../theme/tokens';
import { formatNigerianPhoneForDisplay } from '../../utils/phoneNumber';
import type { VerifiedCallerIdentity } from '../../api/cliClient';
import { useCliManage } from './useCliManage';

interface CliManageScreenProps {
  accessToken: string;
  onVerifyNumber: () => void;
  onResumeConfirm: (identity: VerifiedCallerIdentity) => void;
  onResumeConsent: (identity: VerifiedCallerIdentity) => void;
}

type ConfirmingAction = 'revoke' | 'lost_sim' | null;

const STATUS_LABEL: Partial<Record<VerifiedCallerIdentity['status'], string>> = {
  active: 'Verified',
  suspended: 'Suspended',
  expired: 'Expired',
  revoked: 'Revoked',
};

/**
 * The single entry point for both first-time CLI verification and ongoing
 * management (AC-14.11's revoke/lost-SIM). Resumes an in-progress
 * verification at whichever step it was left at, rather than a separate
 * screen per state.
 */
export function CliManageScreen({
  accessToken,
  onVerifyNumber,
  onResumeConfirm,
  onResumeConsent,
}: CliManageScreenProps): React.JSX.Element {
  const { identity, errorMessage, actionInFlight, revoke, reportLostSim } = useCliManage({
    accessToken,
  });
  const [confirming, setConfirming] = useState<ConfirmingAction>(null);

  if (identity === undefined) {
    return (
      <View style={styles.screen}>
        <Text style={styles.title}>Caller ID</Text>
        <Text style={styles.subtitle}>Loading...</Text>
      </View>
    );
  }

  async function runConfirmed(action: ConfirmingAction): Promise<void> {
    setConfirming(null);
    if (action === 'revoke') await revoke();
    else if (action === 'lost_sim') await reportLostSim();
  }

  const isActive = identity?.status === 'active';
  const needsConfirm = identity?.status === 'phone_verification_pending';
  const needsConsent = identity?.status === 'consent_required';

  return (
    <ScrollView contentContainerStyle={styles.screen}>
      <Text style={styles.title}>Caller ID</Text>

      {errorMessage ? (
        <Banner tone="error" message={errorMessage} testID="cli-manage-error" />
      ) : null}

      {!identity ? (
        <>
          <Text style={styles.subtitle}>
            Verify a Nigerian number so family sees it when you call, instead
            of an unrecognized number.
          </Text>
          <PrimaryButton
            testID="cli-manage-verify"
            label="Verify a number"
            onPress={onVerifyNumber}
          />
        </>
      ) : needsConfirm ? (
        <>
          <Text style={styles.subtitle}>
            You started verifying{' '}
            {formatNigerianPhoneForDisplay(identity.phone_number.replace('+234', '0'))}. Enter
            the code we sent to finish.
          </Text>
          <PrimaryButton
            testID="cli-manage-continue-confirm"
            label="Continue"
            onPress={() => onResumeConfirm(identity)}
          />
        </>
      ) : needsConsent ? (
        <>
          <Text style={styles.subtitle}>
            {formatNigerianPhoneForDisplay(identity.phone_number.replace('+234', '0'))} is
            verified. Confirm you want to use it as your caller ID.
          </Text>
          <PrimaryButton
            testID="cli-manage-continue-consent"
            label="Continue"
            onPress={() => onResumeConsent(identity)}
          />
        </>
      ) : isActive ? (
        <>
          <View style={styles.card}>
            <View style={styles.cardHeader}>
              <Text style={styles.cardNumber} testID="cli-manage-active-number">
                {formatNigerianPhoneForDisplay(identity.phone_number.replace('+234', '0'))}
              </Text>
              <View style={styles.badge}>
                <Text style={styles.badgeLabel}>{STATUS_LABEL[identity.status]}</Text>
              </View>
            </View>
            <Text style={styles.cardText}>
              This is the number family and other recipients see when you
              call them.
            </Text>
          </View>

          <SecondaryButton
            testID="cli-manage-verify-different"
            label="Verify a different number"
            onPress={onVerifyNumber}
          />

          {confirming === 'revoke' ? (
            <View style={styles.confirmRow}>
              <Text style={styles.confirmText}>
                New calls will stop showing this number. Continue?
              </Text>
              <View style={styles.confirmButtons}>
                <View style={styles.confirmButton}>
                  <SecondaryButton
                    testID="cli-manage-revoke-cancel"
                    label="Cancel"
                    onPress={() => setConfirming(null)}
                  />
                </View>
                <View style={styles.confirmButton}>
                  <DestructiveButton
                    testID="cli-manage-revoke-confirm"
                    label="Yes, revoke"
                    onPress={() => runConfirmed('revoke')}
                    loading={actionInFlight === 'revoke'}
                  />
                </View>
              </View>
            </View>
          ) : (
            <DestructiveButton
              testID="cli-manage-revoke"
              label="Revoke"
              onPress={() => setConfirming('revoke')}
            />
          )}

          {confirming === 'lost_sim' ? (
            <View style={styles.confirmRow}>
              <Text style={styles.confirmText}>
                Report this SIM as lost? New calls will stop showing this
                number until you verify again.
              </Text>
              <View style={styles.confirmButtons}>
                <View style={styles.confirmButton}>
                  <SecondaryButton
                    testID="cli-manage-lost-sim-cancel"
                    label="Cancel"
                    onPress={() => setConfirming(null)}
                  />
                </View>
                <View style={styles.confirmButton}>
                  <DestructiveButton
                    testID="cli-manage-lost-sim-confirm"
                    label="Yes, report lost"
                    onPress={() => runConfirmed('lost_sim')}
                    loading={actionInFlight === 'lost_sim'}
                  />
                </View>
              </View>
            </View>
          ) : (
            <DestructiveButton
              testID="cli-manage-lost-sim"
              label="Report lost SIM"
              onPress={() => setConfirming('lost_sim')}
            />
          )}
        </>
      ) : (
        <>
          <Text style={styles.subtitle}>
            {STATUS_LABEL[identity.status] ?? 'Not verified'}. Verify a number
            to make PSTN calls again.
          </Text>
          <PrimaryButton
            testID="cli-manage-verify"
            label="Verify a number"
            onPress={onVerifyNumber}
          />
        </>
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  screen: {
    flexGrow: 1,
    backgroundColor: color.gray50,
    paddingHorizontal: space.space5,
    paddingTop: space.space10,
    gap: space.space4,
  },
  title: { ...typography.heading1, color: color.gray900 },
  subtitle: { ...typography.bodyLarge, color: color.gray700 },
  card: {
    backgroundColor: color.white,
    borderWidth: 1,
    borderColor: color.gray200,
    borderRadius: radius.card,
    padding: space.space4,
    gap: space.space2,
  },
  cardHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  cardNumber: { ...typography.heading2, color: color.gray900 },
  cardText: { ...typography.body, color: color.gray700 },
  badge: {
    backgroundColor: color.success100,
    borderRadius: 999,
    paddingVertical: space.space1,
    paddingHorizontal: space.space3,
  },
  badgeLabel: { ...typography.caption, fontWeight: '600', color: color.success700 },
  confirmRow: {
    backgroundColor: color.white,
    borderWidth: 1,
    borderColor: color.gray200,
    borderRadius: radius.card,
    padding: space.space4,
    gap: space.space3,
  },
  confirmText: { ...typography.body, color: color.gray900 },
  confirmButtons: { flexDirection: 'row', gap: space.space3 },
  confirmButton: { flex: 1 },
});
