import { Backspace, ClockCounterClockwise, Phone, UserList } from 'phosphor-react-native';
import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  FlatList,
  Modal,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import {
  getCallHistory,
  getVoiceEligibility,
  type CallHistoryItem,
  type VoiceEligibility,
} from '../../api/voiceClient';
import { Banner } from '../../components/Banner/Banner';
import { useNetworkQuality } from '../../hooks/useNetworkQuality';
import { loadDialContacts, type DialContact } from '../../services/deviceContacts';
import { telnyxVoiceGateway, type VoiceCallSession, type VoiceGateway } from '../../services/voiceGateway';
import { color, minTouchTarget, radius, space, typography } from '../../theme/tokens';

const KEYS = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '*', '0', '#'];

interface DialPadScreenProps {
  accessToken: string;
  pstnMinutesRemaining: number;
  onCallStarted: (call: VoiceCallSession, recipientName?: string) => void;
  voiceGateway?: VoiceGateway;
  contactsLoader?: () => Promise<DialContact[]>;
}

function isDialable(number: string): boolean {
  return /^(?:0\d{10}|\+234\d{10})$/.test(number);
}

export function DialPadScreen({
  accessToken,
  pstnMinutesRemaining,
  onCallStarted,
  voiceGateway = telnyxVoiceGateway,
  contactsLoader = loadDialContacts,
}: DialPadScreenProps): React.JSX.Element {
  const network = useNetworkQuality();
  const [number, setNumber] = useState('');
  const [contactName, setContactName] = useState<string>();
  const [eligibility, setEligibility] = useState<VoiceEligibility>();
  const [checking, setChecking] = useState(false);
  const [calling, setCalling] = useState(false);
  const [error, setError] = useState<string>();
  const [contacts, setContacts] = useState<DialContact[]>([]);
  const [contactsVisible, setContactsVisible] = useState(false);
  const [history, setHistory] = useState<CallHistoryItem[]>([]);
  const [historyY, setHistoryY] = useState(0);
  const scroll = useRef<ScrollView>(null);

  useEffect(() => {
    getCallHistory(accessToken, 20).then(setHistory).catch(() => undefined);
  }, [accessToken]);

  useEffect(() => {
    setEligibility(undefined);
    if (!isDialable(number) || !network.connected) return;
    let active = true;
    setChecking(true);
    getVoiceEligibility(accessToken, number)
      .then((result) => active && setEligibility(result))
      .catch((reason: Error) => active && setError(reason.message))
      .finally(() => active && setChecking(false));
    return () => {
      active = false;
    };
  }, [accessToken, network.connected, number]);

  const currentMinutes = eligibility?.pstn_minutes_remaining ?? pstnMinutesRemaining;
  const noMinutesForPstn = currentMinutes <= 0 && eligibility?.call_type !== 'app_to_app';
  const disabled =
    !network.connected || !isDialable(number) || checking || calling || noMinutesForPstn;
  const disabledHint = useMemo(() => {
    if (!network.connected) return undefined;
    if (noMinutesForPstn && isDialable(number)) {
      return 'No PSTN minutes remain. DamDam-to-DamDam calls are still free.';
    }
    return undefined;
  }, [network.connected, noMinutesForPstn, number]);

  async function openContacts(): Promise<void> {
    setError(undefined);
    try {
      setContacts(await contactsLoader());
      setContactsVisible(true);
    } catch {
      setError('Contacts are unavailable. You can still enter a number.');
    }
  }

  async function call(): Promise<void> {
    if (disabled) return;
    setCalling(true);
    setError(undefined);
    try {
      const session = await voiceGateway.startCall(accessToken, number, contactName);
      onCallStarted(session, contactName);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Calling is temporarily unavailable.');
    } finally {
      setCalling(false);
    }
  }

  function chooseContact(contact: DialContact): void {
    const compact = contact.phoneNumber.replace(/[\s()-]/g, '');
    setNumber(compact.startsWith('+234') ? compact : compact.replace(/^234/, '+234'));
    setContactName(contact.name);
    setContactsVisible(false);
  }

  return (
    <ScrollView
      ref={scroll}
      contentContainerStyle={styles.screen}
      keyboardShouldPersistTaps="handled"
    >
      <Text style={styles.title}>Call</Text>
      {!network.connected ? (
        <Banner tone="error" message="Calling requires an internet connection" testID="offline-banner" />
      ) : null}
      {currentMinutes > 0 && currentMinutes < 5 ? (
        <Banner
          tone="warning"
          message={`Only ${currentMinutes.toFixed(1)} PSTN minutes remaining`}
          testID="low-minutes-banner"
        />
      ) : null}
      {error ? <Banner tone="error" message={error} /> : null}

      <View style={styles.numberRow}>
        <Text style={styles.number} numberOfLines={1} testID="dialed-number">
          {number || 'Enter a number'}
        </Text>
        <Pressable
          accessibilityLabel="Delete digit"
          onPress={() => setNumber((value) => value.slice(0, -1))}
          style={styles.iconButton}
          testID="delete-digit"
        >
          <Backspace color={color.gray700} size={28} weight="bold" />
        </Pressable>
      </View>

      <View style={styles.shortcutRow}>
        <Pressable onPress={openContacts} style={styles.shortcut} testID="open-contacts">
          <UserList color={color.primary500} size={26} weight="bold" />
          <Text style={styles.shortcutLabel}>Contacts</Text>
        </Pressable>
        <Pressable
          onPress={() => scroll.current?.scrollTo({ y: historyY, animated: true })}
          style={styles.shortcut}
          testID="open-recents"
        >
          <ClockCounterClockwise color={color.primary500} size={26} weight="bold" />
          <Text style={styles.shortcutLabel}>Recent</Text>
        </Pressable>
      </View>

      <View style={styles.keypad}>
        {KEYS.map((key) => (
          <Pressable
            key={key}
            onPress={() => {
              setContactName(undefined);
              setNumber((value) => value + key);
            }}
            style={({ pressed }) => [styles.key, pressed && styles.keyPressed]}
            testID={`dial-key-${key}`}
          >
            <Text style={styles.keyLabel}>{key}</Text>
          </Pressable>
        ))}
      </View>

      <Pressable
        accessibilityRole="button"
        accessibilityLabel="Start call"
        accessibilityState={{ disabled }}
        disabled={disabled}
        onPress={call}
        style={[styles.callButton, disabled && styles.callButtonDisabled]}
        testID="start-call"
      >
        <Phone color={disabled ? color.gray500 : color.white} size={30} weight="fill" />
        <Text style={[styles.callLabel, disabled && styles.callLabelDisabled]}>
          {calling ? 'Connecting…' : eligibility?.call_type === 'app_to_app' ? 'Call free' : 'Call'}
        </Text>
      </Pressable>
      {disabledHint ? <Text style={styles.disabledHint}>{disabledHint}</Text> : null}

      <View
        style={styles.history}
        onLayout={(event) => setHistoryY(event.nativeEvent.layout.y)}
      >
        <Text style={styles.sectionTitle}>Recent calls</Text>
        {history.slice(0, 20).map((item) => (
          <Pressable
            key={item.id}
            onPress={() => setNumber(item.to_number ?? '')}
            style={styles.historyItem}
          >
            <Text style={styles.historyNumber}>{item.to_number ?? 'DamDam user'}</Text>
            <Text style={styles.historyMeta}>
              {item.call_type === 'app_to_app' ? 'Free' : `${item.pstn_minutes_charged.toFixed(2)} min`}
            </Text>
          </Pressable>
        ))}
      </View>

      <Modal visible={contactsVisible} animationType="slide" onRequestClose={() => setContactsVisible(false)}>
        <View style={styles.contactModal}>
          <View style={styles.contactHeader}>
            <Text style={styles.sectionTitle}>Choose a contact</Text>
            <Pressable onPress={() => setContactsVisible(false)} style={styles.closeButton}>
              <Text style={styles.closeLabel}>Close</Text>
            </Pressable>
          </View>
          <FlatList
            data={contacts}
            keyExtractor={(item) => item.id}
            ListEmptyComponent={<Text style={styles.emptyText}>No contacts available</Text>}
            renderItem={({ item }) => (
              <Pressable onPress={() => chooseContact(item)} style={styles.contactItem}>
                <Text style={styles.historyNumber}>{item.name}</Text>
                <Text style={styles.historyMeta}>{item.phoneNumber}</Text>
              </Pressable>
            )}
          />
        </View>
      </Modal>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  screen: { flexGrow: 1, backgroundColor: color.gray50, padding: space.space5, gap: space.space4 },
  title: { ...typography.heading1, color: color.gray900 },
  numberRow: {
    minHeight: 64,
    borderBottomWidth: 1,
    borderBottomColor: color.gray200,
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.space3,
  },
  number: { ...typography.heading2, flex: 1, textAlign: 'center', color: color.gray900 },
  iconButton: { minWidth: minTouchTarget, minHeight: minTouchTarget, alignItems: 'center', justifyContent: 'center' },
  shortcutRow: { flexDirection: 'row', justifyContent: 'center', gap: space.space8 },
  shortcut: { minWidth: 80, minHeight: minTouchTarget, alignItems: 'center', justifyContent: 'center' },
  shortcutLabel: { ...typography.caption, color: color.primary500 },
  keypad: { flexDirection: 'row', flexWrap: 'wrap', justifyContent: 'space-between', rowGap: space.space3 },
  key: {
    width: '30%',
    minHeight: 56,
    borderRadius: radius.card,
    borderWidth: 1,
    borderColor: color.gray200,
    backgroundColor: color.white,
    alignItems: 'center',
    justifyContent: 'center',
  },
  keyPressed: { backgroundColor: color.primary100, transform: [{ scale: 0.98 }] },
  keyLabel: { ...typography.numeral, color: color.gray900 },
  callButton: {
    minHeight: 64,
    borderRadius: radius.button,
    backgroundColor: color.primary500,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: space.space2,
  },
  callButtonDisabled: { backgroundColor: color.gray300 },
  callLabel: { ...typography.bodyLarge, fontWeight: '600', color: color.white },
  callLabelDisabled: { color: color.gray500 },
  disabledHint: { ...typography.caption, textAlign: 'center', color: color.gray600 },
  history: { gap: space.space2, paddingTop: space.space2 },
  sectionTitle: { ...typography.heading3, color: color.gray900 },
  historyItem: {
    minHeight: minTouchTarget,
    borderBottomWidth: 1,
    borderBottomColor: color.gray200,
    justifyContent: 'center',
  },
  historyNumber: { ...typography.bodyLarge, color: color.gray900 },
  historyMeta: { ...typography.caption, color: color.gray600 },
  contactModal: { flex: 1, backgroundColor: color.gray50, padding: space.space5, gap: space.space4 },
  contactHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  closeButton: { minHeight: minTouchTarget, justifyContent: 'center', paddingHorizontal: space.space3 },
  closeLabel: { ...typography.bodyLarge, color: color.primary500 },
  contactItem: { minHeight: 64, borderBottomWidth: 1, borderBottomColor: color.gray200, justifyContent: 'center' },
  emptyText: { ...typography.body, color: color.gray600 },
});
