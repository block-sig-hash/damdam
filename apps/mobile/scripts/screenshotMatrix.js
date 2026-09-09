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
const YAML = require('yaml');

const EXCLUDED_TAG_BY_PLATFORM = {
  ios: 'android-only',
  android: 'ios-only',
};

const PLATFORMS = Object.keys(EXCLUDED_TAG_BY_PLATFORM);

/** Parse ordinary YAML, failing closed for dynamic/nested capture flows. */
function parseFlow(contents) {
  const documents = YAML.parseAllDocuments(contents);
  if (documents.length !== 2 || documents.some(doc => doc.errors.length)) {
    throw new Error('Expected valid Maestro config and command YAML documents');
  }
  const config = documents[0].toJS();
  const commands = documents[1].toJS();
  if (!config || Array.isArray(config) || !Array.isArray(commands)) {
    throw new Error('Expected a Maestro config object and command list');
  }
  const tags = config.tags || [];
  if (!Array.isArray(tags) || tags.some(tag => typeof tag !== 'string')) {
    throw new Error('Maestro tags must be a list of strings');
  }
  const screenshots = [];
  for (const command of commands) {
    if (typeof command === 'string') {
      continue;
    }
    if (!command || typeof command !== 'object' || Array.isArray(command)) {
      throw new Error('Unsupported Maestro command');
    }
    if ('runFlow' in command || 'repeat' in command || 'retry' in command) {
      throw new Error('Nested runFlow/repeat/retry requires explicit matrix support');
    }
    if ('takeScreenshot' in command) {
      const name = command.takeScreenshot;
      if (typeof name !== 'string' || !/^[a-zA-Z0-9][a-zA-Z0-9_.-]*$/.test(name)) {
        throw new Error('Screenshot names must be literal safe basenames');
      }
      screenshots.push(name);
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
