/**
 * Validates a collected screenshot directory against the expected matrix.
 *
 * US-42 / AC-42.2. Replaces CI's `test "${#screenshots[@]}" -eq 32`, which
 * only ever proved that *some* 32 PNGs existed. This checks three things the
 * count check could not:
 *
 *   1. Exact coverage -- every expected screen/locale image is present, and
 *      nothing unexpected is. A missing screen masked by an unrelated PNG at
 *      the same count now fails, because the *names* are compared, not the
 *      total.
 *   2. Each expected file is a real, structurally intact PNG -- not zero
 *      bytes, not a truncated write, not a text file with a .png suffix.
 *   3. Each image has plausible capture dimensions, so a degenerate 1x1
 *      capture cannot pass as a rendered screen.
 *
 * What it deliberately does NOT do is compare pixels against baselines. There
 * are no committed baselines, and inventing them here would either be
 * meaningless (accept anything) or immediately flaky (reject every legitimate
 * UI change). Visual comparison belongs with the redesigned matrix in chunks
 * 08/27.
 *
 * Usage:
 *   node scripts/validateScreenshots.js --platform ios [--dir screenshots]
 *                                       [--flows maestro/screens]
 *                                       [--min-dimension 200]
 */

'use strict';

const fs = require('fs');
const path = require('path');
const {PNG} = require('pngjs');

const {expectedMatrix} = require('./screenshotMatrix');

const PNG_SIGNATURE = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
const DEFAULT_MIN_DIMENSION = 200;

/**
 * Check bounded capture dimensions, then decode pixels and verify chunk CRCs.
 * A surviving header/IEND alone does not establish that an image is readable.
 *
 * @returns {string|null} a human-readable problem, or null when the file is fine.
 */
function inspectPng(filePath, minDimension) {
  let stats;
  try {
    stats = fs.statSync(filePath);
  } catch {
    return 'file is missing';
  }
  if (!stats.isFile()) {
    return 'is not a regular file';
  }
  if (stats.size === 0) {
    return 'is empty (0 bytes)';
  }
  if (stats.size > 64 * 1024 * 1024) {
    return 'exceeds the supported capture size';
  }

  const buffer = fs.readFileSync(filePath);
  if (buffer.length < 33) {
    return `is too small to be a PNG (${buffer.length} bytes)`;
  }
  if (!buffer.subarray(0, 8).equals(PNG_SIGNATURE)) {
    return 'is not a PNG (bad signature)';
  }
  if (buffer.subarray(12, 16).toString('ascii') !== 'IHDR') {
    return 'has no IHDR header chunk';
  }

  const width = buffer.readUInt32BE(16);
  const height = buffer.readUInt32BE(20);
  if (width === 0 || height === 0) {
    return `has zero dimensions (${width}x${height})`;
  }
  if (width < minDimension || height < minDimension) {
    return (
      `is ${width}x${height}, smaller than the minimum plausible capture ` +
      `of ${minDimension}x${minDimension}`
    );
  }

  if (buffer.subarray(buffer.length - 8, buffer.length - 4).toString('ascii') !== 'IEND') {
    return 'is truncated (no IEND chunk at end of file)';
  }

  if (width * height > 25000000) {
    return 'exceeds the supported capture size';
  }
  try {
    PNG.sync.read(buffer, {checkCRC: true});
  } catch (error) {
    return `has invalid PNG data: ${error.message}`;
  }
  return null;
}

function listPngBasenames(dir) {
  let entries;
  try {
    entries = fs.readdirSync(dir);
  } catch {
    return null;
  }
  return entries
    .filter(name => name.toLowerCase().endsWith('.png'))
    .map(name => path.basename(name, path.extname(name)))
    .sort();
}

/**
 * @returns {{ok: boolean, problems: string[], summary: string}}
 */
function validate({platform, dir, flowsDir, minDimension = DEFAULT_MIN_DIMENSION}) {
  if (!Number.isInteger(minDimension) || minDimension <= 0) {
    throw new Error('min-dimension must be a positive integer');
  }
  const matrix = expectedMatrix(platform, flowsDir);
  const expected = matrix.screenshots;
  const problems = [];

  const actual = listPngBasenames(dir);
  if (actual === null) {
    return {
      ok: false,
      problems: [`screenshot directory "${dir}" does not exist or is unreadable`],
      summary: `${platform}: expected ${expected.length} screenshots, found none`,
    };
  }

  const actualSet = new Set(actual);
  if (actualSet.size !== actual.length) {
    problems.push('duplicate screenshot basenames with different extensions');
  }
  const expectedSet = new Set(expected);

  const missing = expected.filter(name => !actualSet.has(name));
  const unexpected = actual.filter(name => !expectedSet.has(name));

  for (const name of missing) {
    problems.push(`missing expected screenshot: ${name}.png`);
  }
  for (const name of unexpected) {
    problems.push(
      `unexpected screenshot not declared by any ${platform} flow: ${name}.png`,
    );
  }

  for (const name of expected) {
    if (!actualSet.has(name)) {
      continue;
    }
    const problem = inspectPng(path.join(dir, `${name}.png`), minDimension);
    if (problem) {
      problems.push(`invalid screenshot ${name}.png: ${problem}`);
    }
  }

  return {
    ok: problems.length === 0,
    problems,
    summary:
      `${platform}: expected ${expected.length} screenshots from ` +
      `${matrix.flows.length} flows, found ${actual.length} PNG file(s)`,
  };
}

function parseArgs(argv) {
  const args = {
    dir: 'screenshots',
    flowsDir: 'maestro/screens',
    minDimension: DEFAULT_MIN_DIMENSION,
  };
  for (let i = 0; i < argv.length; i += 1) {
    const flag = argv[i];
    const value = argv[i + 1];
    if (flag === '--platform') {
      args.platform = value;
      i += 1;
    } else if (flag === '--dir') {
      args.dir = value;
      i += 1;
    } else if (flag === '--flows') {
      args.flowsDir = value;
      i += 1;
    } else if (flag === '--min-dimension') {
      args.minDimension = Number(value);
      i += 1;
    } else {
      throw new Error(`Unknown argument: ${flag}`);
    }
  }
  if (!args.platform) {
    throw new Error('--platform is required (ios or android)');
  }
  return args;
}

function main(argv) {
  let result;
  try {
    result = validate(parseArgs(argv));
  } catch (error) {
    process.stderr.write(`Screenshot validation could not run: ${error.message}\n`);
    return 2;
  }

  process.stdout.write(`${result.summary}\n`);
  if (result.ok) {
    process.stdout.write('Screenshot matrix is complete and every image is valid.\n');
    return 0;
  }
  process.stderr.write('Screenshot matrix validation FAILED:\n');
  for (const problem of result.problems) {
    process.stderr.write(`  - ${problem}\n`);
  }
  return 1;
}

if (require.main === module) {
  process.exit(main(process.argv.slice(2)));
}

module.exports = {validate, inspectPng, parseArgs, main, DEFAULT_MIN_DIMENSION};
