/**
 * US-42 / AC-42.2 — negative coverage for the screenshot completeness check.
 *
 * The old CI assertion was `test "${#screenshots[@]}" -eq 32`. Each test below
 * describes a broken artifact that the count check accepted and this validator
 * must reject. They are written against real files on disk, because the thing
 * being tested is precisely how the validator reads real capture output.
 */

'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const zlib = require('zlib');

const {expectedMatrix, parseFlow} = require('./screenshotMatrix');
const {validate, inspectPng} = require('./validateScreenshots');

const FLOWS_DIR = path.join(__dirname, '..', 'maestro', 'screens');

const CRC_TABLE = (() => {
  const table = new Int32Array(256);
  for (let n = 0; n < 256; n += 1) {
    let c = n;
    for (let k = 0; k < 8; k += 1) {
      c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    }
    table[n] = c;
  }
  return table;
})();

function crc32(buffer) {
  let c = 0xffffffff;
  for (const byte of buffer) {
    c = CRC_TABLE[(c ^ byte) & 0xff] ^ (c >>> 8);
  }
  return (c ^ 0xffffffff) >>> 0;
}

function chunk(type, data) {
  const typeAndData = Buffer.concat([Buffer.from(type, 'ascii'), data]);
  const length = Buffer.alloc(4);
  length.writeUInt32BE(data.length);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(typeAndData));
  return Buffer.concat([length, typeAndData, crc]);
}

/** Build a real, structurally valid greyscale PNG of the requested size. */
function makePng(width = 400, height = 800) {
  const signature = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
  const ihdrData = Buffer.alloc(13);
  ihdrData.writeUInt32BE(width, 0);
  ihdrData.writeUInt32BE(height, 4);
  ihdrData[8] = 8; // bit depth
  ihdrData[9] = 0; // greyscale
  const raw = Buffer.alloc((width + 1) * height); // filter byte + row, all zeroes
  return Buffer.concat([
    signature,
    chunk('IHDR', ihdrData),
    chunk('IDAT', zlib.deflateSync(raw)),
    chunk('IEND', Buffer.alloc(0)),
  ]);
}

function makeCompleteDir(platform) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), `shots-${platform}-`));
  const {screenshots} = expectedMatrix(platform, FLOWS_DIR);
  for (const name of screenshots) {
    fs.writeFileSync(path.join(dir, `${name}.png`), makePng());
  }
  return {dir, screenshots};
}

const run = (platform, dir, overrides = {}) =>
  validate({platform, dir, flowsDir: FLOWS_DIR, ...overrides});

const dirs = [];
afterAll(() => {
  for (const dir of dirs) {
    fs.rmSync(dir, {recursive: true, force: true});
  }
});
const track = dir => {
  dirs.push(dir);
  return dir;
};

describe('expected matrix derivation', () => {
  it.each(['ios', 'android'])(
    'derives a non-empty %s matrix from the flows, not a hardcoded count',
    platform => {
      const {screenshots, flows} = expectedMatrix(platform, FLOWS_DIR);
      expect(screenshots.length).toBeGreaterThan(0);
      expect(new Set(screenshots).size).toBe(screenshots.length);
      expect(flows.length).toBeGreaterThan(0);
    },
  );

  it('gives each platform its own platform-specific screens', () => {
    const ios = expectedMatrix('ios', FLOWS_DIR).screenshots;
    const android = expectedMatrix('android', FLOWS_DIR).screenshots;

    // The tagged eSIM flows are the real platform divergence in this matrix.
    expect(ios.some(name => name.includes('ios'))).toBe(true);
    expect(android.some(name => name.includes('android'))).toBe(true);
    expect(ios.filter(name => name.includes('android-'))).toEqual([]);
    expect(android.filter(name => name.includes('-ios-'))).toEqual([]);
  });

  it('reads tags and screenshot names out of a flow', () => {
    const parsed = parseFlow(
      [
        'appId: com.damdam.app',
        'tags:',
        '  - ios-only',
        '---',
        '- launchApp',
        '- takeScreenshot: example-en',
        '- stopApp',
      ].join('\n'),
    );
    expect(parsed.tags).toEqual(['ios-only']);
    expect(parsed.screenshots).toEqual(['example-en']);
  });

  it('rejects an unknown platform rather than validating nothing', () => {
    expect(() => expectedMatrix('web', FLOWS_DIR)).toThrow(/Unknown platform/);
  });
});

describe.each(['ios', 'android'])('validate(%s)', platform => {
  it('accepts a complete set of valid captures', () => {
    const {dir} = makeCompleteDir(platform);
    track(dir);
    const result = run(platform, dir);
    expect(result.problems).toEqual([]);
    expect(result.ok).toBe(true);
  });

  it('rejects an empty output directory', () => {
    const dir = track(fs.mkdtempSync(path.join(os.tmpdir(), 'shots-empty-')));
    const result = run(platform, dir);
    expect(result.ok).toBe(false);
    expect(result.problems.length).toBeGreaterThan(0);
    expect(result.problems.every(p => p.startsWith('missing expected'))).toBe(true);
  });

  it('rejects a directory that does not exist at all', () => {
    const result = run(platform, path.join(os.tmpdir(), 'definitely-not-here-42'));
    expect(result.ok).toBe(false);
    expect(result.problems[0]).toMatch(/does not exist or is unreadable/);
  });

  it('rejects a missing image replaced by an unrelated PNG at the same count', () => {
    // This is the case the old `-eq 32` check passed: the total is right, the
    // coverage is not.
    const {dir, screenshots} = makeCompleteDir(platform);
    track(dir);
    const dropped = screenshots[0];
    fs.rmSync(path.join(dir, `${dropped}.png`));
    fs.writeFileSync(path.join(dir, 'unrelated-screen-en.png'), makePng());

    const before = fs.readdirSync(dir).length;
    expect(before).toBe(screenshots.length); // count is still "correct"

    const result = run(platform, dir);
    expect(result.ok).toBe(false);
    expect(result.problems).toContain(`missing expected screenshot: ${dropped}.png`);
    expect(result.problems).toContain(
      `unexpected screenshot not declared by any ${platform} flow: unrelated-screen-en.png`,
    );
  });

  it('rejects a zero-byte expected image', () => {
    const {dir, screenshots} = makeCompleteDir(platform);
    track(dir);
    const target = screenshots[1];
    fs.writeFileSync(path.join(dir, `${target}.png`), Buffer.alloc(0));

    const result = run(platform, dir);
    expect(result.ok).toBe(false);
    expect(result.problems).toContain(
      `invalid screenshot ${target}.png: is empty (0 bytes)`,
    );
  });

  it('rejects a corrupt expected image that is not a PNG at all', () => {
    const {dir, screenshots} = makeCompleteDir(platform);
    track(dir);
    const target = screenshots[2];
    fs.writeFileSync(
      path.join(dir, `${target}.png`),
      Buffer.from('this is not an image, it is an error page'.repeat(4)),
    );

    const result = run(platform, dir);
    expect(result.ok).toBe(false);
    expect(result.problems).toContain(
      `invalid screenshot ${target}.png: is not a PNG (bad signature)`,
    );
  });

  it('rejects a truncated image whose header survived the interrupted write', () => {
    const {dir, screenshots} = makeCompleteDir(platform);
    track(dir);
    const target = screenshots[3];
    const truncated = makePng().subarray(0, 120);
    fs.writeFileSync(path.join(dir, `${target}.png`), truncated);

    const result = run(platform, dir);
    expect(result.ok).toBe(false);
    expect(result.problems).toContain(
      `invalid screenshot ${target}.png: is truncated (no IEND chunk at end of file)`,
    );
  });

  it('rejects a degenerate 1x1 capture that is otherwise a valid PNG', () => {
    const {dir, screenshots} = makeCompleteDir(platform);
    track(dir);
    const target = screenshots[4];
    fs.writeFileSync(path.join(dir, `${target}.png`), makePng(1, 1));

    const result = run(platform, dir);
    expect(result.ok).toBe(false);
    expect(result.problems.join('\n')).toMatch(
      new RegExp(`invalid screenshot ${target}\\.png: is 1x1`),
    );
  });

  it('reports every problem at once rather than stopping at the first', () => {
    const {dir, screenshots} = makeCompleteDir(platform);
    track(dir);
    fs.rmSync(path.join(dir, `${screenshots[0]}.png`));
    fs.writeFileSync(path.join(dir, `${screenshots[1]}.png`), Buffer.alloc(0));

    const result = run(platform, dir);
    expect(result.problems.length).toBe(2);
  });
});

describe('inspectPng', () => {
  it('accepts a well-formed capture', () => {
    const dir = track(fs.mkdtempSync(path.join(os.tmpdir(), 'shots-one-')));
    const file = path.join(dir, 'ok.png');
    fs.writeFileSync(file, makePng(400, 800));
    expect(inspectPng(file, 200)).toBeNull();
  });

  it('reports a missing file rather than throwing', () => {
    expect(inspectPng(path.join(os.tmpdir(), 'nope-1234.png'), 200)).toBe(
      'file is missing',
    );
  });
});
