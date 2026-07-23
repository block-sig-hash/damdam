import React, { useState } from 'react';
import {useTranslation} from 'react-i18next';
import {i18n} from '../../i18n';
import { Linking, Modal, Pressable, StyleSheet, Text, View } from 'react-native';
import { color, minTouchTarget, radius, space, typography } from '../../theme/tokens';

export interface SosSentScreenProps {
  synced: boolean;
  htoPhone: string;
  timestamp: string;
  onCancel: () => void;
}

function formatTimestamp(timestamp: string): string {
  const parsed = new Date(timestamp);
  if (Number.isNaN(parsed.getTime())) return timestamp;
  return new Intl.DateTimeFormat(i18n.language, {dateStyle: 'medium', timeStyle: 'short'}).format(parsed);
}

export function SosSentScreen({ synced, htoPhone, timestamp, onCancel }: SosSentScreenProps): React.JSX.Element {
  const {t} = useTranslation('safety');
  const [confirmingCancel, setConfirmingCancel] = useState(false);

  return (
    <View style={styles.screen} testID="sos-sent-screen">
      <Text style={styles.headline}>{t('sos.sentTitle')}</Text>

      <View style={synced ? styles.syncedBanner : styles.pendingBanner}>
        <Text style={styles.bannerText}>
          {synced
            ? t('sos.notified')
            : t('sos.pending')}
        </Text>
      </View>

      <Text style={styles.timestamp}>{t('sos.sentAt', {timestamp: formatTimestamp(timestamp)})}</Text>

      <Pressable
        accessibilityRole="button"
        accessibilityLabel={t('sos.callNow')}
        onPress={() => {
          // Native dialer only — never the app's VoIP layer, so this still
          // works if the app's own calling feature is degraded.
          Linking.openURL(`tel:${htoPhone}`).catch(() => undefined);
        }}
        style={styles.callButton}
      >
        <Text style={styles.callLabel}>{t('sos.callNow')}</Text>
        <Text style={styles.callNumber}>{htoPhone}</Text>
      </Pressable>

      <Pressable
        accessibilityRole="button"
        accessibilityLabel={t('sos.cancel')}
        onPress={() => setConfirmingCancel(true)}
        style={styles.cancelButton}
      >
        <Text style={styles.cancelLabel}>{t('sos.cancel')}</Text>
      </Pressable>

      {/* Product-level confirmation is always a custom in-app modal, never a
          native Alert — docs/design-system.md §7. */}
      <Modal visible={confirmingCancel} transparent animationType="fade" onRequestClose={() => setConfirmingCancel(false)}>
        <View style={styles.modalOverlay}>
          <View style={styles.modalCard}>
            <Text style={styles.modalTitle}>{t('sos.cancelTitle')}</Text>
            <Text style={styles.modalBody}>
              {t('sos.cancelBody')}
            </Text>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel={t('sos.confirmCancellation')}
              onPress={() => {
                setConfirmingCancel(false);
                onCancel();
              }}
              style={styles.confirmCancelButton}
            >
              <Text style={styles.confirmCancelLabel}>{t('sos.confirmCancellation')}</Text>
            </Pressable>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel={t('sos.keepActive')}
              onPress={() => setConfirmingCancel(false)}
              style={styles.keepActiveButton}
            >
              <Text style={styles.keepActiveLabel}>{t('sos.keepActive')}</Text>
            </Pressable>
          </View>
        </View>
      </Modal>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
    backgroundColor: color.gray50,
    paddingHorizontal: space.space5,
    paddingVertical: space.space8,
    alignItems: 'center',
    gap: space.space5,
  },
  headline: { ...typography.display, color: color.gray900, textAlign: 'center' },
  pendingBanner: {
    width: '100%',
    borderLeftWidth: 4,
    borderLeftColor: color.gray700,
    backgroundColor: color.gray100,
    borderRadius: radius.button,
    padding: space.space4,
  },
  syncedBanner: {
    width: '100%',
    borderLeftWidth: 4,
    borderLeftColor: color.success700,
    backgroundColor: color.success100,
    borderRadius: radius.button,
    padding: space.space4,
  },
  bannerText: { ...typography.body, color: color.gray900 },
  timestamp: { ...typography.caption, color: color.gray600 },
  callButton: {
    width: '100%',
    minHeight: 64,
    borderRadius: radius.button,
    backgroundColor: color.primary500,
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: space.space3,
  },
  callLabel: { ...typography.bodyLarge, fontWeight: '600', color: color.white },
  callNumber: { ...typography.body, color: color.white },
  cancelButton: {
    width: '100%',
    minHeight: minTouchTarget,
    borderRadius: radius.button,
    borderWidth: 2,
    borderColor: color.error700,
    backgroundColor: color.white,
    alignItems: 'center',
    justifyContent: 'center',
  },
  cancelLabel: { ...typography.bodyLarge, fontWeight: '600', color: color.error700 },
  modalOverlay: {
    flex: 1,
    backgroundColor: 'rgba(20, 24, 26, 0.5)',
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: space.space5,
  },
  modalCard: {
    width: '100%',
    backgroundColor: color.white,
    borderRadius: radius.card,
    padding: space.space5,
    gap: space.space4,
  },
  modalTitle: { ...typography.heading3, color: color.gray900, textAlign: 'center' },
  modalBody: { ...typography.body, color: color.gray700, textAlign: 'center' },
  confirmCancelButton: {
    minHeight: minTouchTarget,
    borderRadius: radius.button,
    backgroundColor: color.error700,
    alignItems: 'center',
    justifyContent: 'center',
  },
  confirmCancelLabel: { ...typography.bodyLarge, fontWeight: '600', color: color.white },
  keepActiveButton: {
    minHeight: minTouchTarget,
    borderRadius: radius.button,
    alignItems: 'center',
    justifyContent: 'center',
  },
  keepActiveLabel: { ...typography.bodyLarge, fontWeight: '600', color: color.primary500 },
});
