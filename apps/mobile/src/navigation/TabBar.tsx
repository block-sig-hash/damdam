import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import {
  color,
  minTouchTarget,
  space,
  typography,
} from '../theme/tokens';

/**
 * The four-destination tab bar (AC-37.1).
 *
 * Hand-built rather than `@react-navigation/bottom-tabs` for the reason
 * `OnboardingNavigator` gave for its own stack, which still holds: this app has
 * four destinations, no nested navigators and no gesture-driven transitions, and
 * the dependency brings a native-screens/gesture-handler/reanimated chain that
 * has to be linked and re-linked on both platforms for behaviour we would then
 * restyle to match the design system anyway.
 *
 * What it must not skip is the accessibility contract, because a hand-built tab
 * bar is exactly where that gets lost: every tab is a `tab` role inside a
 * `tablist`, carries `selected`, and clears the 48dp target the design system
 * requires.
 */

export interface TabDefinition<T extends string> {
  key: T;
  label: string;
  /** Rendered as a small count next to the label. Zero renders nothing. */
  badgeCount?: number;
  /** Announced instead of the label when the badge would otherwise be silent. */
  accessibilityLabel?: string;
}

interface TabBarProps<T extends string> {
  tabs: TabDefinition<T>[];
  active: T;
  onSelect: (key: T) => void;
}

export function TabBar<T extends string>({
  tabs,
  active,
  onSelect,
}: TabBarProps<T>): React.JSX.Element {
  return (
    <View
      accessibilityRole="tablist"
      testID="app-tab-bar"
      style={styles.bar}
    >
      {tabs.map(tab => {
        const isActive = tab.key === active;
        return (
          <Pressable
            key={tab.key}
            testID={`tab-${tab.key}`}
            accessibilityRole="tab"
            accessibilityState={{ selected: isActive }}
            accessibilityLabel={tab.accessibilityLabel ?? tab.label}
            onPress={() => onSelect(tab.key)}
            style={[styles.tab, isActive && styles.tabActive]}
          >
            <View style={styles.labelRow}>
              <Text
                numberOfLines={1}
                style={[styles.label, isActive && styles.labelActive]}
              >
                {tab.label}
              </Text>
              {tab.badgeCount ? (
                <View style={styles.badge} testID={`tab-${tab.key}-badge`}>
                  <Text style={styles.badgeText}>{tab.badgeCount}</Text>
                </View>
              ) : null}
            </View>
          </Pressable>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  bar: {
    flexDirection: 'row',
    borderTopWidth: 1,
    borderTopColor: color.gray200,
    backgroundColor: color.white,
  },
  tab: {
    flex: 1,
    minHeight: minTouchTarget,
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: space.space3,
    paddingHorizontal: space.space1,
    // A 3dp transparent top border on every tab, coloured only on the active
    // one, so selecting a tab does not shift the row by three pixels.
    borderTopWidth: 3,
    borderTopColor: 'transparent',
  },
  tabActive: {
    borderTopColor: color.primary500,
    backgroundColor: color.primary100,
  },
  labelRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.space1,
  },
  label: {
    fontSize: typography.caption.fontSize,
    lineHeight: typography.caption.lineHeight,
    fontWeight: typography.caption.fontWeight,
    // gray700, not gray500: an unselected tab is still body-sized text on a
    // white bar, and gray500 does not clear 4.5:1 there (theme/tokens.ts's
    // contrastRoles puts it in largeTextOrIconOnly).
    color: color.gray700,
  },
  labelActive: {
    color: color.primary700,
  },
  badge: {
    minWidth: 20,
    paddingHorizontal: space.space1,
    borderRadius: 10,
    backgroundColor: color.accent500,
    alignItems: 'center',
  },
  badgeText: {
    fontSize: typography.caption.fontSize,
    lineHeight: typography.caption.lineHeight,
    fontWeight: '700',
    color: color.gray900,
  },
});
