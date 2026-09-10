import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { useTranslation } from 'react-i18next';

import { announce } from '../announce';
import { StatusPill } from '../StatusPill/StatusPill';
import { color, minTouchTarget, radius, space, typography } from '../../theme/tokens';

/**
 * What is about to happen, before it happens (`VOICE-EXPANSION.md`, chunk 08).
 *
 * DamDam will have two ways to place a call, and they are not interchangeable:
 * a **carrier** call goes through the phone's own dialler on the eSIM and works
 * with no internet; an **internet** call happens inside DamDam, needs no eSIM,
 * needs the microphone, and bills against a different balance. They also fail
 * differently, and a person who thinks they are making one while making the
 * other gets a surprise on a bill or a call that will not connect.
 *
 * So mode, outbound identity, payer and rate are stated on the card, not
 * inferred from which screen you happen to be on. The payer line is the one
 * that matters most: "this is on your work account, and your employer can see
 * that it happened, how long it lasted and what it cost — not what was said" is
 * a sentence somebody deserves before they dial, not after.
 *
 * **This component places no call.** There is no SDK, no client and no
 * permission request here — V02 owns call control and V04/V05 own the mobile
 * and browser channels. Chunk 08 owns what the states look like and what they
 * say. Notably, `RECORD_AUDIO` is deliberately *not* added to the Android
 * manifest: chunk 04's retirement guard asserts its absence, and re-adding it
 * for a design chunk would request a permission the shipped product does not
 * yet use.
 */

export type CallMode = 'carrier' | 'internet';

export interface CallPayer {
  kind: 'personal' | 'work';
  /** Required when `kind` is `work`. */
  organization?: string;
}

interface CallSetupCardProps {
  mode: CallMode;
  /** The number the other party will see, or `null` when we cannot confirm it. */
  outboundIdentity: string | null;
  payer: CallPayer;
  destination: string;
  /** Formatted per-minute rate, or `null` when the destination has no rate. */
  ratePerMinute: string | null;
  currency: string;
  onCall?: () => void;
  testID?: string;
}

function Row({
  label,
  value,
  detail,
  testID,
}: {
  label: string;
  value: string;
  detail?: string;
  testID?: string;
}): React.JSX.Element {
  return (
    <View
      style={styles.row}
      accessible
      accessibilityLabel={announce(label, value, detail)}
      testID={testID}
    >
      <Text style={styles.rowLabel}>{label}</Text>
      <Text style={styles.rowValue}>{value}</Text>
      {detail ? <Text style={styles.rowDetail}>{detail}</Text> : null}
    </View>
  );
}

export function CallSetupCard({
  mode,
  outboundIdentity,
  payer,
  destination,
  ratePerMinute,
  currency,
  onCall,
  testID = 'call-setup',
}: CallSetupCardProps): React.JSX.Element {
  const { t } = useTranslation('states');
  const isWork = payer.kind === 'work';
  // No rate, no call. Placing one we cannot price is how somebody discovers the
  // cost afterwards, and there is no honest way to show them a number first.
  const callable = ratePerMinute !== null;

  return (
    <View style={styles.card} testID={testID}>
      <View style={styles.modeHeader}>
        <StatusPill
          family={t('calls.modeLabel')}
          label={mode === 'carrier' ? t('calls.modeCarrierTitle') : t('calls.modeInternetTitle')}
          tone={mode === 'carrier' ? 'neutral' : 'progress'}
          testID={`${testID}-mode`}
        />
        <Text style={styles.modeBody} testID={`${testID}-mode-body`}>
          {mode === 'carrier' ? t('calls.modeCarrierBody') : t('calls.modeInternetBody')}
        </Text>
      </View>

      <Row
        label={t('calls.identityLabel')}
        value={outboundIdentity ?? t('calls.identityUnknown')}
        detail={outboundIdentity ? undefined : t('calls.identityUnknownDetail')}
        testID={`${testID}-identity`}
      />

      <Row
        label={
          isWork
            ? t('calls.payerLabelWork', { organization: payer.organization ?? '' })
            : t('calls.payerLabelPersonal')
        }
        value={
          isWork
            ? t('calls.payerWorkNote', { organization: payer.organization ?? '' })
            : t('calls.payerPersonalNote')
        }
        testID={`${testID}-payer`}
      />

      <Row
        label={t('calls.rateLabel')}
        value={
          ratePerMinute
            ? t('calls.ratePerMinute', { amount: ratePerMinute, destination })
            : t('calls.rateUnknown')
        }
        detail={
          ratePerMinute ? t('calls.rateEstimate', { currency }) : t('calls.rateUnknownDetail')
        }
        testID={`${testID}-rate`}
      />

      {onCall ? (
        <Pressable
          accessibilityRole="button"
          accessibilityState={{ disabled: !callable }}
          disabled={!callable}
          onPress={onCall}
          style={[styles.callButton, !callable && styles.callButtonDisabled]}
          testID={`${testID}-action`}
        >
          <Text style={[styles.callLabel, !callable && styles.callLabelDisabled]}>
            {mode === 'carrier' ? t('calls.openDialler') : t('calls.callAction')}
          </Text>
        </Pressable>
      ) : null}
    </View>
  );
}

const KEYS = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '*', '0', '#'] as const;

/**
 * The in-call keypad, for menu options (DTMF).
 *
 * Present because "press 2 for account balance" is unusable without it, and
 * separate from the setup card because it belongs to a call that is already
 * running. Every key is a real button with its own label — a grid of bare
 * glyphs is unusable to anyone navigating by screen reader, and this is exactly
 * the moment somebody is listening rather than looking.
 */
export function KeypadPreview({
  onPress,
  testID = 'keypad',
}: {
  onPress?: (digit: string) => void;
  testID?: string;
}): React.JSX.Element {
  const { t } = useTranslation('states');
  return (
    <View testID={testID}>
      <Text style={styles.rowLabel}>{t('calls.keypadLabel')}</Text>
      <Text style={styles.rowDetail}>{t('calls.keypadHelp')}</Text>
      <View style={styles.keypad}>
        {KEYS.map(digit => (
          <Pressable
            key={digit}
            accessibilityRole="button"
            accessibilityLabel={t('calls.keypadAccessibility', { digit })}
            onPress={() => onPress?.(digit)}
            style={styles.key}
            testID={`${testID}-${digit}`}
          >
            <Text style={styles.keyLabel}>{digit}</Text>
          </Pressable>
        ))}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    gap: space.space4,
    padding: space.space5,
    borderWidth: 1,
    borderColor: color.gray200,
    borderRadius: radius.card,
    backgroundColor: color.white,
  },
  modeHeader: { gap: space.space2 },
  modeBody: {
    fontSize: typography.body.fontSize,
    lineHeight: typography.body.lineHeight,
    color: color.gray900,
  },
  row: { gap: space.space1 },
  rowLabel: {
    fontSize: typography.caption.fontSize,
    lineHeight: typography.caption.lineHeight,
    fontWeight: '600',
    color: color.gray700,
  },
  rowValue: {
    fontSize: typography.body.fontSize,
    lineHeight: typography.body.lineHeight,
    color: color.gray900,
  },
  rowDetail: {
    fontSize: typography.caption.fontSize,
    lineHeight: typography.caption.lineHeight,
    color: color.gray600,
  },
  callButton: {
    minHeight: minTouchTarget,
    borderRadius: radius.button,
    backgroundColor: color.primary500,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: space.space4,
  },
  callButtonDisabled: { backgroundColor: color.gray300 },
  callLabel: {
    fontSize: typography.bodyLarge.fontSize,
    lineHeight: typography.bodyLarge.lineHeight,
    fontWeight: '600',
    color: color.white,
  },
  // Legible rather than faded: a disabled call button has to read as "off for
  // a reason", with the reason stated above it, not as a rendering glitch.
  callLabelDisabled: { color: color.gray700 },
  keypad: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: space.space2,
    marginTop: space.space3,
  },
  key: {
    minWidth: minTouchTarget + space.space4,
    minHeight: minTouchTarget + space.space1,
    flexGrow: 1,
    flexBasis: '30%',
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 1,
    borderColor: color.gray300,
    borderRadius: radius.button,
    backgroundColor: color.gray50,
  },
  keyLabel: {
    fontSize: typography.numeral.fontSize,
    lineHeight: typography.numeral.lineHeight,
    fontWeight: '600',
    color: color.gray900,
  },
});
