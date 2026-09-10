/**
 * Reference contrast ratios this implementation must reproduce.
 *
 * A contrast helper checked only against itself will certify an illegible
 * palette without complaint, so these are values published independently of
 * this repository:
 *
 * - **21:1 for black on white and 1:1 for identical colours** are definitional
 *   in WCAG 2.1 ("contrast ratios can range from 1 to 21").
 * - **`#767676` = 4.54 and `#777777` = 4.48 on white** are the pair WebAIM
 *   documents as the boundary of AA body text — the lighter one fails and the
 *   darker one passes. An implementation that got the curve subtly wrong would
 *   not land either side of 4.5 in the right place.
 * - **`#949494` = 3.03** is WebAIM's documented AA-large boundary.
 * - **`#595959` = 7.0** is its documented AAA body-text boundary.
 * - **`#0000FF` on white = 8.59**, and the same either way round, which is what
 *   proves the ratio is order-independent.
 *
 * Sources: WCAG 2.1 (W3C Recommendation, 5 June 2018), §1.4.3 and the
 * relative-luminance definition; WebAIM Contrast Checker documented boundary
 * values. Checked 10 September 2026.
 */

'use strict';

module.exports = [
  { foreground: '#000000', background: '#FFFFFF', ratio: 21.0 },
  { foreground: '#FFFFFF', background: '#FFFFFF', ratio: 1.0 },
  { foreground: '#767676', background: '#FFFFFF', ratio: 4.54 },
  { foreground: '#777777', background: '#FFFFFF', ratio: 4.48 },
  { foreground: '#949494', background: '#FFFFFF', ratio: 3.03 },
  { foreground: '#595959', background: '#FFFFFF', ratio: 7.0 },
  { foreground: '#0000FF', background: '#FFFFFF', ratio: 8.59 },
  { foreground: '#FFFFFF', background: '#0000FF', ratio: 8.59 },
];
