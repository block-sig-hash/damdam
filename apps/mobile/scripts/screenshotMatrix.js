/**
 * Derives the expected screenshot matrix directly from the Maestro flows.
 *
 * US-42 / AC-42.2. CI previously asserted only `count == 32`, which passes for
 * any 32 PNGs -- including 32 copies of one screen, or a set where a missing
 * screen is masked by an unrelated file. The expected *set* is what matters,
 * and it is already stated unambiguously by the flows themselves: each
 * `takeScreenshot: <name>` names exactly one expected image, and a flow's
 * `tags:` decide which platform runs it.
 *
 * Deriving from the flows rather than hardcoding a list means the matrix
 * cannot silently drift from what CI actually runs, and the redesign chunks
 * (08, 27) change the matrix by changing flows -- no magic number to update.
 * Nothing here hardcodes 32.
 *
 * Maestro selects flows with `--exclude-tags`: the iOS job excludes
 * `android-only`, the Android job excludes `ios-only` (see ci.yml and
 * scripts/run-maestro-android-ci.sh).
 */

'use strict';

const fs = require('fs');
const path = require('path');

const EXCLUDED_TAG_BY_PLATFORM = {
  ios: 'android-only',
  android: 'ios-only',
};

const PLATFORMS = Object.keys(EXCLUDED_TAG_BY_PLATFORM);

/**
 * Parse one Maestro flow file into its tags and the screenshots it captures.
 *
 * Deliberately a small line parser rather than a YAML dependency: these files
 * have a fixed, simple shape, and the screenshot harness should not add a
 * runtime dependency to the mobile app's tree just to read them.
 */
function parseFlow(contents) {
  const tags = [];
  const screenshots = [];
  let inTagsBlock = false;

  for (const rawLine of contents.split('\n')) {
    const line = rawLine.replace(/\s+$/, '');
    if (line === '') {
      continue;
    }

    if (inTagsBlock) {
      const tagMatch = line.match(/^\s+-\s*(\S+)\s*$/);
      if (tagMatch) {
        tags.push(tagMatch[1]);
        continue;
      }
      inTagsBlock = false;
    }

    if (/^tags:\s*$/.test(line)) {
      inTagsBlock = true;
      continue;
    }

    const shotMatch = line.match(/^-\s*takeScreenshot:\s*(\S+)\s*$/);
    if (shotMatch) {
      screenshots.push(shotMatch[1]);
    }
  }

  return {tags, screenshots};
}

function readFlows(flowsDir) {
  return fs
    .readdirSync(flowsDir)
    .filter(name => name.endsWith('.yaml') || name.endsWith('.yml'))
    .sort()
    .map(name => ({
      name,
      ...parseFlow(fs.readFileSync(path.join(flowsDir, name), 'utf8')),
    }));
}

/**
 * @returns {{platform: string, flows: string[], screenshots: string[]}}
 *   `screenshots` is the sorted, exact set of PNG basenames (no extension)
 *   that a successful run on `platform` must produce.
 */
function expectedMatrix(platform, flowsDir) {
  if (!Object.prototype.hasOwnProperty.call(EXCLUDED_TAG_BY_PLATFORM, platform)) {
    throw new Error(
      `Unknown platform "${platform}"; expected one of ${PLATFORMS.join(', ')}`,
    );
  }
  const excludedTag = EXCLUDED_TAG_BY_PLATFORM[platform];
  const selected = readFlows(flowsDir).filter(
    flow => !flow.tags.includes(excludedTag),
  );

  const screenshots = [];
  const seen = new Map();
  for (const flow of selected) {
    for (const shot of flow.screenshots) {
      if (seen.has(shot)) {
        throw new Error(
          `Duplicate screenshot name "${shot}" in ${flow.name} and ` +
            `${seen.get(shot)}: names must be unique or one capture ` +
            'silently overwrites the other in the collected directory.',
        );
      }
      seen.set(shot, flow.name);
      screenshots.push(shot);
    }
  }

  if (screenshots.length === 0) {
    throw new Error(
      `No screenshots are declared for platform "${platform}" in ${flowsDir}. ` +
        'That is a harness misconfiguration, not an empty matrix.',
    );
  }

  return {
    platform,
    flows: selected.map(flow => flow.name),
    screenshots: screenshots.sort(),
  };
}

module.exports = {PLATFORMS, EXCLUDED_TAG_BY_PLATFORM, parseFlow, expectedMatrix};
