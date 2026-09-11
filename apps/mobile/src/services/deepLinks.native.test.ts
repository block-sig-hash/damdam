/**
 * The JavaScript parser is irrelevant unless each platform gives matching URLs
 * to React Native. Keep the native declarations under the same regression gate
 * as the cold/warm link logic.
 */
import { readFileSync } from 'fs';
import { join } from 'path';

const MOBILE_ROOT = join(__dirname, '..', '..');

it('registers the DamDam scheme and verified web domains on Android', () => {
  const manifest = readFileSync(
    join(MOBILE_ROOT, 'android', 'app', 'src', 'main', 'AndroidManifest.xml'),
    'utf8',
  );

  expect(manifest).toContain('<data android:scheme="damdam" />');
  expect(manifest).toContain(
    '<data android:scheme="https" android:host="damdam.app" />',
  );
  expect(manifest).toContain(
    '<data android:scheme="https" android:host="www.damdam.app" />',
  );
  expect(manifest.match(/android:autoVerify="true"/g)).toHaveLength(2);
});

it('registers the DamDam scheme and associated web domains on iOS', () => {
  const plist = readFileSync(
    join(MOBILE_ROOT, 'ios', 'DamDam', 'Info.plist'),
    'utf8',
  );
  const entitlements = readFileSync(
    join(MOBILE_ROOT, 'ios', 'DamDam', 'DamDam.entitlements'),
    'utf8',
  );

  expect(plist).toContain('<key>CFBundleURLSchemes</key>');
  expect(plist).toContain('<string>damdam</string>');
  expect(entitlements).toContain('<string>applinks:damdam.app</string>');
  expect(entitlements).toContain('<string>applinks:www.damdam.app</string>');
});
