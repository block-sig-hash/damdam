/**
 * WCAG 2.1 relative luminance and contrast ratio.
 *
 * Shared by both apps' token tests so the two never disagree about what a
 * ratio is. The formula is WCAG 2.1 §"relative luminance" and
 * §"contrast ratio" verbatim; `contrast.vectors.js` holds the published
 * worked examples this implementation is checked against, because a
 * contrast helper that agrees only with itself will happily certify an
 * illegible palette.
 */

'use strict';

/** @param {string} hex `#RRGGBB` */
function relativeLuminance(hex) {
  const match = /^#([0-9a-fA-F]{6})$/.exec(hex.trim());
  if (!match) {
    throw new Error(`Expected #RRGGBB, got ${JSON.stringify(hex)}`);
  }
  const channels = [0, 2, 4]
    .map(offset => parseInt(match[1].slice(offset, offset + 2), 16) / 255)
    .map(channel =>
      channel <= 0.03928
        ? channel / 12.92
        : Math.pow((channel + 0.055) / 1.055, 2.4),
    );
  return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
}

/** Contrast ratio between two `#RRGGBB` colours, 1:1 to 21:1. */
function contrastRatio(foreground, background) {
  const a = relativeLuminance(foreground);
  const b = relativeLuminance(background);
  const lighter = Math.max(a, b);
  const darker = Math.min(a, b);
  return (lighter + 0.05) / (darker + 0.05);
}

/** WCAG 2.1 AA thresholds. */
const AA_BODY_TEXT = 4.5;
const AA_LARGE_TEXT = 3;
const AA_NON_TEXT = 3;

module.exports = {
  relativeLuminance,
  contrastRatio,
  AA_BODY_TEXT,
  AA_LARGE_TEXT,
  AA_NON_TEXT,
};
