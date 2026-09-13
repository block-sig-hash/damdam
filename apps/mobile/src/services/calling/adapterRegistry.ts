import { UnavailableCallAdapter, type CallClientAdapter } from './adapter';

/**
 * Which calling adapter this build has. Today: none.
 *
 * The seam exists so that installing a supported Telnyx SDK is a change to
 * *this file* plus one new adapter module, rather than a change to the
 * controller, the screens or the tests. That is the point of the boundary
 * `CLAUDE.md` requires for vendor integrations.
 *
 * It returns `UnavailableCallAdapter` because no SDK is installed and none
 * could honestly be: D1 is open, there is no Telnyx account, and no native iOS
 * or Android build has exercised one. Returning a stub that resolved would make
 * every screen look finished and would be precisely the "mock passing itself
 * off as evidence" the test policy forbids.
 *
 * Replacing it needs, in order: a Telnyx account (D1), the SDK added to
 * `package.json` with its peer ranges checked against the versions in V01's
 * capability matrix, `RECORD_AUDIO` and `MODIFY_AUDIO_SETTINGS` in the Android
 * manifest, `NSMicrophoneUsageDescription` in `Info.plist`, chunk 04's
 * retirement guard amended to distinguish approved outbound calling from the
 * retired incoming surface, and iOS and Android builds that prove connect,
 * dial, DTMF, mute, routing and hangup on real hardware.
 */
export function resolveCallAdapter(): CallClientAdapter {
  return new UnavailableCallAdapter();
}
