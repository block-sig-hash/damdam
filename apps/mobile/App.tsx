import React from 'react';
import { SafeAreaView, StatusBar, StyleSheet, View } from 'react-native';
import { AuthenticatedApp } from './src/navigation/AuthenticatedApp';
import { OnboardingNavigator } from './src/navigation/OnboardingNavigator';
import { PinUnlockScreen } from './src/screens/PinUnlock/PinUnlockScreen';
import { useSessionGate } from './src/hooks/useSessionGate';
import { PostHogMonitoringProvider } from './src/monitoring/PostHogMonitoringProvider';
import { color } from './src/theme/tokens';

/**
 * AC-23.1/AC-23.2/AC-23.3/AC-23.4 -- useSessionGate decides whether a
 * persisted session exists, is still within its 30-day inactivity
 * window, and whether the app-open/foreground-resume PIN gate applies,
 * per docs/frontend-mobile.md's PIN Unlock screen note (Screen 31).
 */
function App(): React.JSX.Element {
  const { phase, session, onOnboarded, onPinUnlocked } = useSessionGate();

  let content: React.JSX.Element;
  if (phase === 'loading') {
    content = <View style={styles.root} />;
  } else if (phase === 'pin-gate' && session) {
    content = (
      <PinUnlockScreen phoneNumber={session.phoneNumber} onUnlocked={onPinUnlocked} />
    );
  } else if (phase === 'authenticated' && session) {
    content = (
      <AuthenticatedApp
        accessToken={session.accessToken}
        departureDate={session.departureDate}
        packageId={session.packageId}
      />
    );
  } else {
    content = <OnboardingNavigator onAuthenticated={onOnboarded} />;
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
