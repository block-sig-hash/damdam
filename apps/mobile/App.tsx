import React, { useState } from 'react';
import { SafeAreaView, StatusBar, StyleSheet } from 'react-native';
import { AuthenticatedApp } from './src/navigation/AuthenticatedApp';
import {
  type AuthenticatedMobileSession,
  OnboardingNavigator,
} from './src/navigation/OnboardingNavigator';
import { PostHogMonitoringProvider } from './src/monitoring/PostHogMonitoringProvider';
import { color } from './src/theme/tokens';

function App(): React.JSX.Element {
  const [session, setSession] = useState<AuthenticatedMobileSession>();
  return (
    <PostHogMonitoringProvider>
      <SafeAreaView style={styles.root}>
        <StatusBar barStyle="dark-content" backgroundColor={color.gray50} />
        {session ? (
          <AuthenticatedApp {...session} />
        ) : (
          <OnboardingNavigator onAuthenticated={setSession} />
        )}
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
