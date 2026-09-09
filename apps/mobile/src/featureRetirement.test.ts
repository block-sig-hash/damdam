/**
 * US-30 / AC-30.3, AC-30.5 -- the retired features leave no live reference.
 *
 * Removing screens is easy to do incompletely: a stale import, a client module
 * nothing renders any more, or a background task still opening the retired
 * queue database. This walks the shipped source and fails on any of them, so a
 * later change cannot quietly reintroduce a path to a withdrawn feature.
 */

import {readdirSync, readFileSync, statSync} from 'fs';
import {join} from 'path';

const SRC = join(__dirname);

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap(entry => {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) return sourceFiles(path);
    return /\.tsx?$/.test(entry) && !/\.test\.tsx?$/.test(entry) ? [path] : [];
  });
}

const files = sourceFiles(SRC);
const shipped = files.map(path => ({path, text: readFileSync(path, 'utf8')}));

const RETIRED_MODULES = [
  'checkInOutbox',
  'sosOutbox',
  'outboxOwnership',
  'checkInLocation',
  'checkInBackground',
  'arrivalPrompts',
  'checkInClient',
  'sosClient',
  'familyContactClient',
  'emergencyContactClient',
  'SosConfirmScreen',
  'SosSentScreen',
  'EmergencyEssentials',
  'useEmergencyContact',
  'callKit',
  'voiceGateway',
  'deviceContacts',
  'cliClient',
  'voiceClient',
  'DialPadScreen',
  'ActiveCallScreen',
  'CliManageScreen',
  'CliVerifyEntryScreen',
  'CliVerifyConfirmScreen',
  'CliConsentScreen',
];

describe('retired feature surface', () => {
  it('ships no source file for a retired module', () => {
    const survivors = files.filter(path =>
      RETIRED_MODULES.some(module => path.includes(module)),
    );
    expect(survivors).toEqual([]);
  });

  it.each(RETIRED_MODULES)('has no import of %s', module => {
    const importers = shipped
      .filter(file => new RegExp(`from '[^']*${module}'`).test(file.text))
      .map(file => file.path);
    expect(importers).toEqual([]);
  });

  it('opens no retired queue database', () => {
    // The device-local queue file is deliberately left on disk rather than
    // deleted -- see docs/implementation/retirement/RETENTION-PLAN.md.
    // Nothing may read it.
    const readers = shipped
      .filter(file => file.text.includes('damdam-safety.sqlite'))
      .map(file => file.path);
    expect(readers).toEqual([]);
  });

  it('ships no current-client geofence contract', () => {
    const paymentClient = readFileSync(join(SRC, 'api', 'paymentClient.ts'), 'utf8');
    expect(paymentClient).not.toContain('PackageGeofence');
    expect(paymentClient).not.toContain('getPackageGeofence');
  });

  it('does not package libraries used only by retired safety queues', () => {
    const packageJson = JSON.parse(
      readFileSync(join(SRC, '..', 'package.json'), 'utf8'),
    ) as {dependencies: Record<string, string>; devDependencies: Record<string, string>};
    for (const dependency of [
      '@react-native-community/geolocation',
      'react-native-background-fetch',
      'react-native-nitro-modules',
      'react-native-nitro-sqlite',
      'react-native-uuid',
      'sql.js',
    ]) {
      expect(packageJson.dependencies?.[dependency]).toBeUndefined();
      expect(packageJson.devDependencies?.[dependency]).toBeUndefined();
    }
  });

  it('requests no permission for a retired feature', () => {
    const manifest = readFileSync(
      join(SRC, '..', 'android', 'app', 'src', 'main', 'AndroidManifest.xml'),
      'utf8',
    );
    for (const permission of [
      'ACCESS_FINE_LOCATION',
      'ACCESS_BACKGROUND_LOCATION',
      'READ_CONTACTS',
      'RECORD_AUDIO',
      'MODIFY_AUDIO_SETTINGS',
      'FOREGROUND_SERVICE_PHONE_CALL',
    ]) {
      expect(manifest).not.toContain(permission);
    }
  });

  it('declares no VoIP background mode', () => {
    // PushKit woke the app for an incoming WebRTC call. Native dialling needs
    // no background mode at all.
    const plist = readFileSync(
      join(SRC, '..', 'ios', 'DamDam', 'Info.plist'),
      'utf8',
    );
    expect(plist).not.toContain('voip');
  });

  it('declares no iOS usage description for a retired feature', () => {
    const plist = readFileSync(
      join(SRC, '..', 'ios', 'DamDam', 'Info.plist'),
      'utf8',
    );
    for (const key of [
      'NSLocationWhenInUseUsageDescription',
      'NSLocationAlwaysAndWhenInUseUsageDescription',
      'NSContactsUsageDescription',
      'NSMicrophoneUsageDescription',
    ]) {
      expect(plist).not.toContain(key);
    }
  });
});
