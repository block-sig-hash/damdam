/**
 * The design system's accessibility claims, checked rather than asserted.
 *
 * `docs/design-system.md` §1 states a contrast ratio for every colour and
 * derives a hard rule from them — semantic alerts never render as coloured
 * text on white, because `warning-500` and `success-500` do not clear body
 * contrast. That rule is only trustworthy if the numbers behind it are true,
 * and a table of hand-written ratios in a markdown file goes stale the first
 * time somebody nudges a hex.
 *
 * So nothing here trusts a stored ratio. Every figure is computed from the
 * colour itself, and the *classification* in `tokens.json` is what gets
 * checked. Add a colour to `bodyTextOnWhite` that cannot carry body text and
 * this suite fails before the colour reaches a screen.
 */

const fs = require('fs');
const path = require('path');

const {
  contrastRatio,
  relativeLuminance,
  AA_BODY_TEXT,
  AA_LARGE_TEXT,
} = require('../../../../design-tokens/contrast.js');
const vectors = require('../../../../design-tokens/contrast.vectors.js') as {
  foreground: string;
  background: string;
  ratio: number;
}[];
const source = require('../../../../design-tokens/tokens.json') as {
  color: Record<string, string>;
  contrastRoles: {
    bodyTextOnWhite: string[];
    largeTextOrIconOnly: string[];
    tintBackground: string[];
    filledButton: Record<string, string>;
  };
  space: Record<string, number>;
  typography: Record<string, unknown>;
};
const { mobileTokens } = require('../../../../design-tokens/build.js');

import { color, contrastRoles, minTouchTarget, space, typography } from './tokens';

const WHITE = '#FFFFFF';

describe('the contrast helper agrees with published values', () => {
  it.each(vectors.map(v => [v.foreground, v.background, v.ratio] as const))(
    '%s on %s is %s:1',
    (foreground: string, background: string, ratio: number) => {
      expect(contrastRatio(foreground, background)).toBeCloseTo(ratio, 1);
    },
  );

  it('is order-independent', () => {
    expect(contrastRatio('#0B6B66', WHITE)).toBeCloseTo(
      contrastRatio(WHITE, '#0B6B66'),
      10,
    );
  });

  it('refuses a value it cannot parse rather than returning a plausible number', () => {
    expect(() => relativeLuminance('0B6B66')).toThrow();
    expect(() => relativeLuminance('#0B6')).toThrow();
    expect(() => relativeLuminance('')).toThrow();
  });
});

describe('every colour keeps the promise its classification makes', () => {
  it.each(source.contrastRoles.bodyTextOnWhite)(
    '%s carries body text on white (>= 4.5:1)',
    (name: string) => {
      const ratio = contrastRatio(source.color[name], WHITE);
      expect(ratio).toBeGreaterThanOrEqual(AA_BODY_TEXT);
    },
  );

  it.each(source.contrastRoles.largeTextOrIconOnly)(
    '%s is legible at large sizes but is NOT allowed body text',
    (name: string) => {
      const ratio = contrastRatio(source.color[name], WHITE);
      expect(ratio).toBeGreaterThanOrEqual(AA_LARGE_TEXT);
      // The half that matters. If one of these ever clears 4.5:1 it should be
      // promoted deliberately, not left mis-filed where a reviewer reading the
      // list would draw the wrong conclusion about the tint rule.
      expect(ratio).toBeLessThan(AA_BODY_TEXT);
    },
  );

  it.each(source.contrastRoles.tintBackground)(
    '%s is a light enough fill for gray900 body text',
    (name: string) => {
      expect(contrastRatio(source.color.gray900, source.color[name])).toBeGreaterThanOrEqual(
        AA_BODY_TEXT,
      );
    },
  );

  it.each(Object.entries(source.contrastRoles.filledButton))(
    'a filled %s button is legible with %s text',
    (fill: string, label: string) => {
      expect(contrastRatio(source.color[label], source.color[fill])).toBeGreaterThanOrEqual(
        AA_BODY_TEXT,
      );
    },
  );

  it('never lets the accent become a foreground colour', () => {
    // Desert Gold is 2.97:1 on white -- under even the 3:1 non-text floor. It
    // is a filled badge and nothing else: as an icon, a border or text on a
    // white surface it fails AA outright. This test exists because the colour
    // reads as "dark enough" by eye, which is exactly how it would get used.
    expect(contrastRatio(source.color.accent500, WHITE)).toBeLessThan(AA_LARGE_TEXT);
    expect(source.contrastRoles.bodyTextOnWhite).not.toContain('accent500');
    expect(source.contrastRoles.largeTextOrIconOnly).not.toContain('accent500');
    expect(source.contrastRoles.tintBackground).not.toContain('accent500');
    // Its one permitted use, and the pairing that makes it legible.
    expect(source.contrastRoles.filledButton.accent500).toBe('gray900');
  });

  it('classifies every colour it defines', () => {
    const classified = new Set([
      ...source.contrastRoles.bodyTextOnWhite,
      ...source.contrastRoles.largeTextOrIconOnly,
      ...source.contrastRoles.tintBackground,
      ...Object.keys(source.contrastRoles.filledButton),
      'white',
      // Borders and dividers. Non-text, and deliberately below the 3:1
      // non-text threshold: they separate surfaces rather than convey
      // information, and nothing in this system depends on seeing one.
      'gray300',
      'gray200',
    ]);
    const unclassified = Object.keys(source.color).filter(name => !classified.has(name));
    expect(unclassified).toEqual([]);
  });
});

describe('the generated token module has not drifted from its source', () => {
  it('matches what design-tokens/build.js would write today', () => {
    const generated = mobileTokens();
    const onDisk = fs.readFileSync(
      path.join(__dirname, 'tokens.ts'),
      'utf8',
    );
    expect(onDisk).toBe(generated);
  });

  it('exposes the same colours the source defines', () => {
    expect(Object.keys(color)).toEqual(Object.keys(source.color));
    expect(Object.keys(space)).toEqual(Object.keys(source.space));
    expect(Object.keys(typography)).toEqual(Object.keys(source.typography));
  });

  it('keeps the touch-target floor at the accessibility minimum', () => {
    // 44dp is Apple's floor and 48dp is Android's; the system takes the
    // larger so one number satisfies both platforms.
    expect(minTouchTarget).toBeGreaterThanOrEqual(48);
  });

  it('re-exports the contrast roles so a component can be tested against them', () => {
    expect([...contrastRoles.bodyTextOnWhite]).toEqual(
      source.contrastRoles.bodyTextOnWhite,
    );
    expect([...contrastRoles.largeTextOrIconOnly]).toEqual(
      source.contrastRoles.largeTextOrIconOnly,
    );
  });
});

describe('the type scale stays readable when the system font is scaled up', () => {
  it('never sets a line height below its font size', () => {
    for (const [name, style] of Object.entries(typography)) {
      expect({ name, ok: style.lineHeight >= style.fontSize }).toEqual({
        name,
        ok: true,
      });
    }
  });

  it('keeps body text at or above 16px, the floor for comfortable reading', () => {
    expect(typography.body.fontSize).toBeGreaterThanOrEqual(16);
    expect(typography.bodyLarge.fontSize).toBeGreaterThanOrEqual(typography.body.fontSize);
  });

  it('keeps caption text above the 12px legibility floor', () => {
    expect(typography.caption.fontSize).toBeGreaterThanOrEqual(14);
  });
});
