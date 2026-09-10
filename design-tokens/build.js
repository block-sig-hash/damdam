/**
 * Generates each app's token file from `tokens.json`.
 *
 * Two apps, two languages, one set of values. Before this, the dashboard's
 * `globals.css` carried its own hardcoded hexes -- `#17211b` where the mobile
 * app used `gray-900` `#14181A`, `#1f6b45` where it used `primary-500`
 * `#0B6B66` -- so "the design system" meant two different palettes depending on
 * which app you opened. Nothing warned anyone, because nothing compared them.
 *
 * Generating both and checking the result into git means the diff shows what
 * changed, and a drift test in each app's own suite fails if a generated file
 * is edited by hand. That is the same shape as the OpenAPI contract check the
 * API already uses, deliberately: reviewers here already know that pattern.
 *
 *   node design-tokens/build.js          # write
 *   node design-tokens/build.js --check  # verify, exit 1 on drift
 */

'use strict';

const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const tokens = require('./tokens.json');

const BANNER_LINES = [
  'GENERATED FILE -- do not edit.',
  '',
  'Source: design-tokens/tokens.json',
  'Regenerate: node design-tokens/build.js',
  '',
  'Editing this file by hand fails the token drift test in this app.',
];

/** kebab-case for CSS custom properties: `primary500` -> `primary-500`. */
function kebab(name) {
  return name.replace(/([a-z])(\d)/g, '$1-$2').replace(/([a-z])([A-Z])/g, '$1-$2').toLowerCase();
}

function block(lines, prefix, open, close) {
  return [open, ...lines.map(line => (line ? `${prefix}${line}` : prefix.trimEnd())), close].join(
    '\n',
  );
}

function mobileTokens() {
  const banner = block(BANNER_LINES, ' * ', '/**', ' */');
  const colors = Object.entries(tokens.color)
    .map(([name, value]) => `  ${name}: '${value}',`)
    .join('\n');
  const spaces = Object.entries(tokens.space)
    .map(([name, value]) => `  ${name}: ${value},`)
    .join('\n');
  const radii = Object.entries(tokens.radius)
    .map(([name, value]) => `  ${name}: ${value},`)
    .join('\n');
  const type = Object.entries(tokens.typography)
    .map(
      ([name, style]) =>
        `  ${name}: { fontSize: ${style.fontSize}, lineHeight: ${style.lineHeight}, fontWeight: '${style.fontWeight}' },`,
    )
    .join('\n');
  const typeNames = Object.keys(tokens.typography)
    .map(name => `'${name}'`)
    .join(' | ');

  return `${banner}

export const color = {
${colors}
} as const;

export const space = {
${spaces}
} as const;

export const radius = {
${radii}
} as const;

export const minTouchTarget = ${tokens.minTouchTarget};
export const minInputHeight = ${tokens.minInputHeight};

type TextStyleToken = {
  fontSize: number;
  lineHeight: number;
  fontWeight: '400' | '500' | '600' | '700';
};

export type TypographyToken = ${typeNames};

export const typography: Record<TypographyToken, TextStyleToken> = {
${type}
};

export const fontFamily = '${tokens.fontFamily}';

/**
 * Which colours may carry body text, and which may not.
 *
 * Exported rather than left as a comment so a component can be tested against
 * it. \`largeTextOrIconOnly\` colours do not clear 4.5:1 on white, which is why
 * every semantic banner and badge in this system renders as a light tint fill
 * with \`gray900\` text and the saturated colour confined to the icon and
 * border.
 */
export const contrastRoles = {
  bodyTextOnWhite: [
${tokens.contrastRoles.bodyTextOnWhite.map(name => `    '${name}',`).join('\n')}
  ],
  largeTextOrIconOnly: [
${tokens.contrastRoles.largeTextOrIconOnly.map(name => `    '${name}',`).join('\n')}
  ],
} as const;
`;
}

function dashboardTokens() {
  const banner = block(BANNER_LINES, '   ', '/*', '*/');
  const colors = Object.entries(tokens.color)
    .map(([name, value]) => `  --color-${kebab(name)}: ${value};`)
    .join('\n');
  const spaces = Object.entries(tokens.space)
    .map(([name, value]) => `  --${kebab(name)}: ${value}px;`)
    .join('\n');
  const radii = Object.entries(tokens.radius)
    .map(([name, value]) => `  --radius-${kebab(name)}: ${value}px;`)
    .join('\n');
  const type = Object.entries(tokens.typography)
    .map(
      ([name, style]) =>
        `  --type-${kebab(name)}-size: ${style.fontSize}px;\n` +
        `  --type-${kebab(name)}-line: ${style.lineHeight}px;\n` +
        `  --type-${kebab(name)}-weight: ${style.fontWeight};`,
    )
    .join('\n');

  return `${banner}

:root {
${colors}

${spaces}

${radii}

  --min-touch-target: ${tokens.minTouchTarget}px;
  --min-input-height: ${tokens.minInputHeight}px;

${type}

  --font-family: ${tokens.fontFamily}, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
}
`;
}

const OUTPUTS = [
  { file: 'apps/mobile/src/theme/tokens.ts', render: mobileTokens },
  { file: 'apps/dashboard/app/tokens.css', render: dashboardTokens },
];

function main() {
  const check = process.argv.includes('--check');
  const drifted = [];
  for (const output of OUTPUTS) {
    const target = path.join(ROOT, output.file);
    const rendered = output.render();
    if (check) {
      const current = fs.existsSync(target) ? fs.readFileSync(target, 'utf8') : null;
      if (current !== rendered) {
        drifted.push(output.file);
      }
      continue;
    }
    fs.mkdirSync(path.dirname(target), { recursive: true });
    fs.writeFileSync(target, rendered);
    process.stdout.write(`wrote ${output.file}\n`);
  }
  if (drifted.length) {
    process.stderr.write(
      `Generated token files differ from design-tokens/tokens.json:\n` +
        drifted.map(file => `  ${file}\n`).join('') +
        `Run: node design-tokens/build.js\n`,
    );
    process.exit(1);
  }
}

module.exports = { mobileTokens, dashboardTokens, OUTPUTS, ROOT };

if (require.main === module) {
  main();
}
