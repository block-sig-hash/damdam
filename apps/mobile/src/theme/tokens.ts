/**
 * GENERATED FILE -- do not edit.
 *
 * Source: design-tokens/tokens.json
 * Regenerate: node design-tokens/build.js
 *
 * Editing this file by hand fails the token drift test in this app.
 */

export const color = {
  primary700: '#073E45',
  primary500: '#0B6B66',
  primary100: '#E3F1F1',
  accent500: '#C68A2E',
  success700: '#167A52',
  success500: '#1E8A5F',
  success100: '#E4F5EC',
  warning700: '#A63C11',
  warning500: '#D9531E',
  warning100: '#FBEAE0',
  error700: '#C0392B',
  error100: '#FBE7E4',
  info700: '#2C5F91',
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
  pill: 999,
} as const;

export const minTouchTarget = 48;
export const minInputHeight = 52;

type TextStyleToken = {
  fontSize: number;
  lineHeight: number;
  fontWeight: '400' | '500' | '600' | '700';
};

export type TypographyToken = 'display' | 'heading1' | 'heading2' | 'heading3' | 'bodyLarge' | 'body' | 'caption' | 'numeral';

export const typography: Record<TypographyToken, TextStyleToken> = {
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

/**
 * Which colours may carry body text, and which may not.
 *
 * Exported rather than left as a comment so a component can be tested against
 * it. `largeTextOrIconOnly` colours do not clear 4.5:1 on white, which is why
 * every semantic banner and badge in this system renders as a light tint fill
 * with `gray900` text and the saturated colour confined to the icon and
 * border.
 */
export const contrastRoles = {
  bodyTextOnWhite: [
    'primary700',
    'primary500',
    'success700',
    'warning700',
    'error700',
    'info700',
    'gray900',
    'gray700',
    'gray600',
  ],
  largeTextOrIconOnly: [
    'success500',
    'warning500',
    'info500',
    'gray500',
  ],
} as const;
