import React from 'react';
import { SafeAreaView, StatusBar, StyleSheet } from 'react-native';
import { OnboardingNavigator } from './src/navigation/OnboardingNavigator';
import { color } from './src/theme/tokens';

function App(): React.JSX.Element {
  return (
    <SafeAreaView style={styles.root}>
      <StatusBar barStyle="dark-content" backgroundColor={color.gray50} />
      <OnboardingNavigator />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
    backgroundColor: color.gray50,
  },
});

export default App;
