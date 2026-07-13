/**
 * Design tokens ported from docs/design-system.md. Keep this file's
 * values in sync with that document — it is the source of truth,
 * this module is just its React Native representation.
 */

export const color = {
  primary700: '#073E45',
  primary500: '#0B6B66',
  primary100: '#E3F1F1',

  accent500: '#C68A2E',

  success700: '#167A52',
  success500: '#1E8A5F',
  success100: '#E4F5EC',

  warning500: '#D9531E',
  warning100: '#FBEAE0',

  error700: '#C0392B',
  error100: '#FBE7E4',

  info500: '#3B7DBF',
  info100: '#E7F0F9',

  gray900: '#14181A',
  gray700: '#445050',
  gray600: '#5A6666',
  gray500: '#728080',
  gray300: '#C4CACA',
  gray200: '#DDE1E1',
  gray100: '#EDEFEF',
  gray50: '#F7F8F8',
  white: '#FFFFFF',
} as const;

export const space = {
  space1: 4,
  space2: 8,
  space3: 12,
  space4: 16,
  space5: 20,
  space6: 24,
  space8: 32,
  space10: 40,
  space12: 48,
  space16: 64,
} as const;

export const radius = {
  button: 12,
  card: 16,
} as const;

export const minTouchTarget = 48;

type TextStyleToken = {
  fontSize: number;
  lineHeight: number;
  fontWeight: '400' | '500' | '600' | '700';
};

export const typography: Record<
  'display' | 'heading1' | 'heading2' | 'heading3' | 'bodyLarge' | 'body' | 'caption' | 'numeral',
  TextStyleToken
> = {
  display: { fontSize: 32, lineHeight: 40, fontWeight: '700' },
  heading1: { fontSize: 28, lineHeight: 36, fontWeight: '700' },
  heading2: { fontSize: 22, lineHeight: 30, fontWeight: '600' },
  heading3: { fontSize: 18, lineHeight: 26, fontWeight: '600' },
  bodyLarge: { fontSize: 17, lineHeight: 26, fontWeight: '400' },
  body: { fontSize: 16, lineHeight: 24, fontWeight: '400' },
  caption: { fontSize: 14, lineHeight: 20, fontWeight: '500' },
  numeral: { fontSize: 24, lineHeight: 28, fontWeight: '700' },
};

export const fontFamily = 'Inter';
