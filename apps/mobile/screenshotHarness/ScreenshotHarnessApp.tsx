import React, { useState } from 'react';
import { Pressable, SafeAreaView, ScrollView, StatusBar, StyleSheet, Text } from 'react-native';
import { color, space, typography } from '../src/theme/tokens';
import { installHarnessFetchMock } from './fetchMock';
import { HARNESS_REGISTRY } from './registry';

installHarnessFetchMock();

/**
 * Test-only entry point (screenshotHarness/README.md) -- registered by
 * index.js instead of the real App only when SCREENSHOT_HARNESS_MODE is
 * inlined true at build time, which CI's screenshot job is the only
 * thing that ever sets. Renders a picker of every registered screen
 * (see registry.tsx); a Maestro flow taps `harness-target-<key>`, waits
 * for that screen's own testID to appear, then screenshots it -- one
 * APK/IPA build serves every target, no per-screen rebuild needed.
 */
export function ScreenshotHarnessApp(): React.JSX.Element {
  const [selectedKey, setSelectedKey] = useState<string | null>(null);

  const selected = selectedKey ? HARNESS_REGISTRY[selectedKey] : null;

  return (
    <SafeAreaView style={styles.root}>
      <StatusBar barStyle="dark-content" backgroundColor={color.gray50} />
      {selected ? (
        selected.render()
      ) : (
        <ScrollView testID="harness-picker" contentContainerStyle={styles.list}>
          <Text style={styles.heading}>Screenshot harness</Text>
          {Object.entries(HARNESS_REGISTRY).map(([key, target]) => (
            <Pressable
              key={key}
              testID={`harness-target-${key}`}
              onPress={() => setSelectedKey(key)}
              style={styles.item}
            >
              <Text style={styles.itemLabel}>{target.label}</Text>
            </Pressable>
          ))}
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: color.gray50 },
  list: { padding: space.space5, gap: space.space3 },
  heading: {
    fontSize: typography.heading1.fontSize,
    lineHeight: typography.heading1.lineHeight,
    fontWeight: typography.heading1.fontWeight,
    color: color.gray900,
    marginBottom: space.space2,
  },
  item: {
    minHeight: 52,
    justifyContent: 'center',
    paddingHorizontal: space.space4,
    borderWidth: 1,
    borderColor: color.gray200,
    borderRadius: 12,
    backgroundColor: color.white,
  },
  itemLabel: {
    fontSize: typography.body.fontSize,
    lineHeight: typography.body.lineHeight,
    color: color.gray900,
  },
});
