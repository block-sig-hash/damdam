import React, { useState } from 'react';
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
  return parsed.toLocaleString();
}

export function SosSentScreen({ synced, htoPhone, timestamp, onCancel }: SosSentScreenProps): React.JSX.Element {
  const [confirmingCancel, setConfirmingCancel] = useState(false);

  return (
    <View style={styles.screen}>
      <Text style={styles.headline}>SOS sent — help is coming</Text>

      <View style={synced ? styles.syncedBanner : styles.pendingBanner}>
        <Text style={styles.bannerText}>
          {synced
            ? 'Your operator and family have been notified'
            : 'Sending... will notify your operator and family as soon as you have signal'}
        </Text>
      </View>

      <Text style={styles.timestamp}>Sent {formatTimestamp(timestamp)}</Text>

      <Pressable
        accessibilityRole="button"
        accessibilityLabel="Call now"
        onPress={() => {
          // Native dialer only — never the app's VoIP layer, so this still
          // works if the app's own calling feature is degraded.
          Linking.openURL(`tel:${htoPhone}`).catch(() => undefined);
        }}
        style={styles.callButton}
      >
        <Text style={styles.callLabel}>Call now</Text>
        <Text style={styles.callNumber}>{htoPhone}</Text>
      </Pressable>

      <Pressable
        accessibilityRole="button"
        accessibilityLabel="Cancel SOS"
        onPress={() => setConfirmingCancel(true)}
        style={styles.cancelButton}
      >
        <Text style={styles.cancelLabel}>Cancel SOS</Text>
      </Pressable>

      {/* Product-level confirmation is always a custom in-app modal, never a
          native Alert — docs/design-system.md §7. */}
      <Modal visible={confirmingCancel} transparent animationType="fade" onRequestClose={() => setConfirmingCancel(false)}>
        <View style={styles.modalOverlay}>
          <View style={styles.modalCard}>
            <Text style={styles.modalTitle}>Are you sure you want to cancel this SOS?</Text>
            <Text style={styles.modalBody}>
              Your operator and family were already notified. Only cancel if this was sent by mistake.
            </Text>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Confirm cancellation"
              onPress={() => {
                setConfirmingCancel(false);
                onCancel();
              }}
              style={styles.confirmCancelButton}
            >
              <Text style={styles.confirmCancelLabel}>Confirm cancellation</Text>
            </Pressable>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Keep SOS active"
              onPress={() => setConfirmingCancel(false)}
              style={styles.keepActiveButton}
            >
              <Text style={styles.keepActiveLabel}>Keep SOS active</Text>
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
