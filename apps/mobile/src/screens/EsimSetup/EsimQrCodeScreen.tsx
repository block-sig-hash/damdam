import React from 'react';
import {
  ActivityIndicator,
  Image,
  Linking,
  Platform,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { Banner } from '../../components/Banner/Banner';
import { PrimaryButton } from '../../components/PrimaryButton/PrimaryButton';
import { SecondaryButton } from '../../components/SecondaryButton/SecondaryButton';
import { color, radius, space, typography } from '../../theme/tokens';
import { useEsimProfile } from './useEsimProfile';

interface EsimQrCodeScreenProps {
  accessToken: string;
  packageId: string;
}

/**
 * US-11 Screen 17. The source spec only names this screen, so this minimal
 * layout follows design-system tokens and documents the assumptions in the PR.
 */
export function EsimQrCodeScreen({
  accessToken,
  packageId,
}: EsimQrCodeScreenProps): React.JSX.Element {
  const { phase, profile, error, retry, download, confirmManualDownload } =
    useEsimProfile(accessToken, packageId);

  if (phase === 'loading') {
    return (
      <View style={[styles.screen, styles.centered]} testID="esim-profile-loading">
        <ActivityIndicator size="large" color={color.primary500} />
        <Text style={styles.body}>Preparing your eSIM...</Text>
      </View>
    );
  }

  if (!profile) {
    return (
      <View style={styles.screen} testID="esim-profile-queued">
        <Text style={styles.title}>Your eSIM is queued</Text>
        <Banner
          tone="warning"
          message={error ?? 'We will retry automatically and notify you when it is ready.'}
        />
        <Text style={styles.body}>
          You can leave this screen. We will notify you when your QR code is ready.
        </Text>
        <View style={styles.action}>
          <PrimaryButton label="Try now" onPress={() => retry().catch(() => undefined)} />
        </View>
      </View>
    );
  }

  const downloaded = phase === 'downloaded' || profile.status === 'downloaded';
  return (
    <ScrollView
      style={styles.screen}
      contentContainerStyle={styles.content}
      testID="esim-qr-code-screen"
    >
      <Text style={styles.title}>Your eSIM is ready</Text>
      <Text style={styles.body}>Install it 2–7 days before your departure.</Text>
      {downloaded ? (
        <Banner tone="info" message="eSIM download recorded successfully." testID="esim-ready-notice" />
      ) : error ? (
        <Banner tone="error" message={error} />
      ) : null}

      <View style={styles.statusRow}>
        <View style={[styles.statusPill, downloaded && styles.statusPillDone]}>
          <Text style={[styles.statusText, downloaded && styles.statusTextDone]}>
            {downloaded ? 'Downloaded' : 'Ready to download'}
          </Text>
        </View>
      </View>

      <View style={styles.qrCard}>
        <Image
          source={{ uri: profile.qr_code_url }}
          accessibilityLabel="eSIM installation QR code"
          resizeMode="contain"
          style={styles.qrImage}
          testID="esim-qr-image"
        />
      </View>

      <View style={styles.detailCard}>
        <Text style={styles.detailLabel}>ICCID</Text>
        <Text selectable style={styles.detailValue}>{profile.iccid}</Text>
        <Text style={styles.detailLabel}>Activation code</Text>
        <Text selectable style={styles.codeValue}>{profile.activation_code_lpa}</Text>
      </View>

      {Platform.OS === 'android' ? (
        <View style={styles.action}>
          <PrimaryButton
            label={downloaded ? 'Downloaded' : 'Download to device'}
            onPress={() => download().catch(() => undefined)}
            disabled={downloaded}
            loading={phase === 'downloading'}
            testID="esim-download-button"
          />
        </View>
      ) : null}
      {Platform.OS === 'ios' && !downloaded ? (
        <View style={styles.action}>
          <SecondaryButton
            label="I installed this eSIM"
            onPress={() => confirmManualDownload().catch(() => undefined)}
            testID="esim-confirm-manual"
          />
        </View>
      ) : null}
      <View style={styles.action}>
        <SecondaryButton
          label="Save QR code"
          onPress={() => Linking.openURL(profile.qr_code_url).catch(() => undefined)}
          testID="esim-save-qr"
        />
      </View>
      <Text style={styles.note}>
        Keep this QR code saved offline. Open it full-screen, then use your device's Save Image action.
      </Text>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
    backgroundColor: color.gray50,
    paddingHorizontal: space.space5,
    paddingTop: space.space10,
  },
  content: { paddingBottom: space.space10 },
  centered: { alignItems: 'center', justifyContent: 'center' },
  title: {
    fontSize: typography.heading1.fontSize,
    lineHeight: typography.heading1.lineHeight,
    fontWeight: typography.heading1.fontWeight,
    color: color.gray900,
    marginBottom: space.space3,
  },
  body: {
    fontSize: typography.body.fontSize,
    lineHeight: typography.body.lineHeight,
    color: color.gray700,
    marginBottom: space.space4,
  },
  statusRow: {
    marginVertical: space.space4,
  },
  statusPill: {
    alignSelf: 'flex-start',
    borderRadius: 999,
    backgroundColor: color.info100,
    paddingHorizontal: space.space3,
    paddingVertical: space.space1,
  },
  statusPillDone: { backgroundColor: color.success100 },
  statusText: {
    fontSize: typography.caption.fontSize,
    lineHeight: typography.caption.lineHeight,
    fontWeight: '600',
    color: color.info500,
  },
  statusTextDone: { color: color.success700 },
  qrCard: {
    backgroundColor: color.white,
    borderRadius: radius.card,
    padding: space.space5,
    alignItems: 'center',
  },
  qrImage: { width: 240, height: 240 },
  detailCard: {
    backgroundColor: color.white,
    borderRadius: radius.card,
    padding: space.space4,
    marginTop: space.space4,
  },
  detailLabel: {
    fontSize: typography.caption.fontSize,
    lineHeight: typography.caption.lineHeight,
    fontWeight: typography.caption.fontWeight,
    color: color.gray600,
    marginTop: space.space2,
  },
  detailValue: {
    fontSize: typography.body.fontSize,
    lineHeight: typography.body.lineHeight,
    color: color.gray900,
  },
  codeValue: {
    fontSize: typography.caption.fontSize,
    lineHeight: typography.caption.lineHeight,
    color: color.gray900,
  },
  action: { marginTop: space.space4 },
  note: {
    marginTop: space.space3,
    fontSize: typography.caption.fontSize,
    lineHeight: typography.caption.lineHeight,
    color: color.gray600,
    textAlign: 'center',
  },
});
