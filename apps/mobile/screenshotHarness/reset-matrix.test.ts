/**
 * @jest-environment node
 *
 * Keeps `reset-matrix.json` honest against the matrix CI actually derives.
 *
 * A manifest that says which screens are covered is only worth anything if
 * something checks it against reality. Two directions matter, and the second
 * is the one that decays quietly:
 *
 * 1. Everything claimed `implemented` really is captured, in both locales.
 * 2. Nothing listed `pending` is quietly present. A screen moves to
 *    `implemented` when a flow captures it — not when somebody edits a list.
 *
 * Chunk 27 turns this manifest into a release gate. It inherits a file that has
 * been checked all along rather than one written once and trusted.
 *
 * Runs in the node environment, like `scripts/validateScreenshots.test.js`:
 * the matrix deriver reads YAML, and the React Native preset resolves `yaml`
 * to its browser ESM build, which jest cannot require.
 */

import { join } from 'path';

import matrix from './reset-matrix.json';

const { expectedMatrix } = require('../scripts/screenshotMatrix') as {
  expectedMatrix: (
    platform: string,
    flowsDir: string,
  ) => { platform: string; flows: string[]; screenshots: string[] };
};

const FLOWS = join(__dirname, '..', 'maestro', 'screens');
const PLATFORMS = ['ios', 'android'] as const;

interface Group {
  owner: string;
  screens: string[];
  /** Defaults to every platform. Two eSIM screens exist on one only. */
  platforms?: string[];
  why?: string;
}

const implementedGroups = Object.entries(matrix.implemented).filter(
  ([key]) => key !== '$comment',
) as [string, Group][];

const pendingGroups = Object.entries(matrix.pending).filter(
  ([key]) => key !== '$comment',
) as [string, Group][];

const implementedScreens = implementedGroups.flatMap(([, group]) => group.screens);
const pendingScreens = pendingGroups.flatMap(([, group]) => group.screens);

/** The screens a given platform is expected to capture. */
function expectedOn(platform: string): string[] {
  return implementedGroups
    .filter(([, group]) => (group.platforms ?? [...PLATFORMS]).includes(platform))
    .flatMap(([, group]) => group.screens);
}

describe('the re-cut screenshot matrix', () => {
  it.each(PLATFORMS)('captures every implemented screen in both locales on %s', platform => {
    const captured = new Set(expectedMatrix(platform, FLOWS).screenshots);
    const missing = expectedOn(platform).flatMap(screen =>
      matrix.locales
        .map(locale => `${screen}-${locale}`)
        .filter(name => !captured.has(name)),
    );
    expect(missing).toEqual([]);
  });

  it.each(PLATFORMS)('captures nothing it has not declared on %s', platform => {
    const declared = new Set(
      expectedOn(platform).flatMap(screen =>
        matrix.locales.map(locale => `${screen}-${locale}`),
      ),
    );
    const undeclared = expectedMatrix(platform, FLOWS).screenshots.filter(
      name => !declared.has(name),
    );
    // An image nobody declared is an image nobody reviews.
    expect(undeclared).toEqual([]);
  });

  it.each(PLATFORMS)('does not quietly capture a screen still listed as pending on %s', platform => {
    const captured = expectedMatrix(platform, FLOWS).screenshots;
    const sneaked = pendingScreens.filter(screen =>
      captured.some(name => name === `${screen}-en` || name === `${screen}-fr`),
    );
    expect(sneaked).toEqual([]);
  });

  it('gives every pending group a named owner', () => {
    // Chunk 27's gate has to fail against somebody, not against a silence.
    for (const [name, group] of pendingGroups) {
      expect({ name, owner: group.owner }).toEqual({
        name,
        owner: expect.stringMatching(/chunk/i),
      });
      expect(group.screens.length).toBeGreaterThan(0);
    }
  });

  it('gives every implemented group a named owner and platform list', () => {
    for (const [name, group] of implementedGroups) {
      expect({ name, owner: group.owner }).toEqual({
        name,
        owner: expect.stringMatching(/chunk/i),
      });
      expect(group.platforms?.length ?? 0).toBeGreaterThan(0);
      for (const platform of group.platforms ?? []) {
        expect([...PLATFORMS]).toContain(platform);
      }
    }
  });

  it('declares a platform-specific screen on exactly the platform that has it', () => {
    // Found by this suite: two eSIM activation flows are tagged for one
    // platform, and claiming them for both leaves the other platform's matrix
    // permanently and misleadingly incomplete.
    const androidOnly = implementedGroups.find(([name]) => name === 'retainedAndroidOnly');
    const iosOnly = implementedGroups.find(([name]) => name === 'retainedIosOnly');
    expect(androidOnly?.[1].platforms).toEqual(['android']);
    expect(iosOnly?.[1].platforms).toEqual(['ios']);
  });

  it('lists no screen as both implemented and pending', () => {
    const overlap = implementedScreens.filter(screen => pendingScreens.includes(screen));
    expect(overlap).toEqual([]);
  });

  it('names no duplicate screen', () => {
    const all = [...implementedScreens, ...pendingScreens];
    const duplicates = all.filter((screen, index) => all.indexOf(screen) !== index);
    expect(duplicates).toEqual([]);
  });

  it('covers both locales, which is the requirement that keeps failing quietly', () => {
    // English always fits. French expansion is what the second locale is for.
    expect(matrix.locales).toEqual(['en', 'fr']);
  });

  it('still owes the reset product its own screens', () => {
    // A guard against this file being "completed" by deleting the pending list.
    // The reset journeys are the point of the redesign; until 18-24 land, the
    // matrix is deliberately incomplete and says so.
    expect(pendingScreens.length).toBeGreaterThan(0);
  });
});
