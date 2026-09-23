import { PermissionsAndroid, Platform } from 'react-native';

import type { MicrophonePermission } from './callSession';

/**
 * Ask for the microphone at the moment of the first internet call (US-47).
 *
 * **Not at startup, and not at sign-in.** A permission prompt that arrives
 * before the customer has asked for anything is the prompt people decline, and
 * declining it here is expensive: it is the one permission internet calling
 * cannot work without.
 *
 * ## Android
 *
 * `RECORD_AUDIO` is a runtime permission, and it must also be declared in the
 * manifest for the request to do anything. **It is deliberately not declared
 * today.** Chunk 08 left it out because requesting a permission the shipped
 * product cannot use trains people to say no, and chunk 04's retirement guard
 * asserts its absence. This chunk does not add it either: no supported SDK is
 * installed, so there is no build that could place a call with it.
 *
 * That is why `hasDeclaredPermission` is checked first and reports `blocked`
 * rather than calling through. A request against an undeclared permission
 * returns `never_ask_again` on some Android versions and silently poisons the
 * prompt for when the SDK does arrive.
 *
 * ## iOS
 *
 * There is no React Native API for the microphone prompt: `AVAudioSession`
 * raises it, which means the WebRTC SDK raises it when it opens a session, and
 * `NSMicrophoneUsageDescription` must be in `Info.plist` before it will. Both
 * arrive with the SDK. Until then this reports `blocked` rather than pretending
 * a prompt happened.
 */

export async function requestMicrophone(): Promise<MicrophonePermission> {
  if (Platform.OS === 'android') {
    const permission = PermissionsAndroid.PERMISSIONS?.RECORD_AUDIO;
    if (!permission) {
      return 'blocked';
    }
    try {
      const already = await PermissionsAndroid.check(permission);
      if (already) {
        return 'granted';
      }
      const result = await PermissionsAndroid.request(permission);
      if (result === PermissionsAndroid.RESULTS.GRANTED) {
        return 'granted';
      }
      // "Never ask again" is a different problem from "not now": one is fixed
      // by asking again, the other only in Settings, and the copy differs.
      return result === PermissionsAndroid.RESULTS.NEVER_ASK_AGAIN
        ? 'blocked'
        : 'denied';
    } catch {
      return 'blocked';
    }
  }
  // iOS: the SDK's audio session raises the prompt. Without an SDK there is
  // nothing to ask, and reporting `granted` here would be a lie the controller
  // would act on.
  return 'blocked';
}
