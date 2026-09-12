import React, { useCallback, useEffect, useState } from 'react';
import { SafeAreaView, StatusBar, StyleSheet, View } from 'react-native';
import { AuthNavigator } from './src/navigation/AuthNavigator';
import { ConsumerApp } from './src/navigation/ConsumerApp';
import { PinUnlockScreen } from './src/screens/PinUnlock/PinUnlockScreen';
import { useSessionGate } from './src/hooks/useSessionGate';
import { PostHogMonitoringProvider } from './src/monitoring/PostHogMonitoringProvider';
import { color } from './src/theme/tokens';
import { i18n } from './src/i18n';

/**
 * The root: signed out, PIN-gated, or in the app (AC-37.1).
 *
 * `useSessionGate` still owns the session lifetime — persistence, the 30-day
 * inactivity ceiling and the PIN gate are US-23's work and unchanged. What
 * chunk 18 changes is the two branches around it: the signed-out branch is now
 * the email-first `AuthNavigator`, and the signed-in branch is the four-tab
 * `ConsumerApp` rather than the single eSIM-activation host.
 *
 * The PIN gate now applies only where a PIN actually exists on this device
 * (see `useSessionGate`'s `hasLocalPin`). An account created through the email
 * identity flow never set one, and showing it a keypad no entry can satisfy is
 * a locked door with no key.
 */
function App(): React.JSX.Element {
  const { phase, session, onOnboarded, onPinUnlocked, onSignedOut } =
    useSessionGate();
  const [emailHint, setEmailHint] = useState<string | undefined>(undefined);
  const [signingOut, setSigningOut] = useState(false);

  useEffect(() => {
    if (session?.locale && i18n.language !== session.locale) {
      i18n.changeLanguage(session.locale).catch(() => undefined);
    }
  }, [session?.locale]);

  /**
   * "Sign in with a different account", from the wrong-recipient invitation
   * screen. It clears the stored session but deliberately leaves the pending
   * deep link in place: the customer is on their way to sign in *as* the
   * invited address, and that link is the thing they are coming back for.
   */
  const switchAccount = useCallback(
    async (hint?: string) => {
      setSigningOut(true);
      setEmailHint(hint);
      try {
        await onSignedOut();
      } finally {
        setSigningOut(false);
      }
    },
    [onSignedOut],
  );

  let content: React.JSX.Element;
  if (phase === 'loading' || signingOut) {
    content = <View style={styles.root} />;
  } else if (
    phase === 'pin-gate' &&
    session &&
    session.userId &&
    session.phoneNumber
  ) {
    // A session stored before US-29 carries no userId, so its PIN cannot be
    // attributed to an account. Such a session falls through to sign-in rather
    // than unlocking against whatever PIN happens to be on the device — and so
    // does one with no phone number, whose "forgot your PIN" path would have
    // nothing to send an OTP to.
    content = (
      <PinUnlockScreen
        phoneNumber={session.phoneNumber}
        userId={session.userId}
        onUnlocked={onPinUnlocked}
      />
    );
  } else if (phase === 'authenticated' && session?.userId) {
    content = (
      <ConsumerApp
        accessToken={session.accessToken}
        currentUserId={session.userId}
        currentEmail={session.email ?? null}
        onSwitchAccount={switchAccount}
      />
    );
  } else {
    content = (
      <AuthNavigator initialEmail={emailHint} onAuthenticated={onOnboarded} />
    );
  }

  return (
    <PostHogMonitoringProvider>
      <SafeAreaView style={styles.root}>
        <StatusBar barStyle="dark-content" backgroundColor={color.gray50} />
        {content}
      </SafeAreaView>
    </PostHogMonitoringProvider>
  );
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
    backgroundColor: color.gray50,
  },
});

export default App;
