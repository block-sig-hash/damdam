import { NativeModules, Platform } from 'react-native';

/**
 * Keeping an eSIM activation code out of the screenshot gallery (US-38, chunk 20).
 *
 * The stake is unusual. A Telnyx eSIM profile is one-time use and cannot be
 * re-downloaded, so an activation code that lands in a screenshot — and from
 * there in a cloud photo backup, a chat thread, or a shared gallery — is a
 * paid-for line somebody else can install, with no remedy but another purchase.
 * There is nothing to rotate.
 *
 * ## The platforms are not equal, and the UI must not pretend they are
 *
 * **Android** has `FLAG_SECURE`, which blocks the screenshot, screen recording
 * and the recent-apps thumbnail in one flag. That is real protection and this
 * module applies it.
 *
 * **iOS has no equivalent.** There is no public API to prevent a screenshot; an
 * app can only be *told* one was taken, after the fact. Anything claiming
 * otherwise is a private API or a rendering trick, and neither belongs on a
 * payment-adjacent screen. So on iOS this returns `unsupported` and the caller
 * is required to show the warning instead of silently rendering the code as if
 * it were protected.
 *
 * Neither platform stops a second phone photographing the screen. The copy says
 * so; a protection that overstates itself is worse than none, because somebody
 * relies on it.
 */

export type ScreenPrivacyResult =
  /** The window is protected for as long as `release` has not been called. */
  | 'protected'
  /** The platform offers nothing. The caller must warn instead. */
  | 'unsupported'
  /** The platform offers it and the call failed. Also a reason to warn. */
  | 'failed';

interface ScreenPrivacyNativeModule {
  setSecure(secure: boolean): Promise<boolean>;
}

function nativeModule(): ScreenPrivacyNativeModule | undefined {
  return NativeModules.ScreenPrivacyModule as
    | ScreenPrivacyNativeModule
    | undefined;
}

export async function protectScreen(): Promise<ScreenPrivacyResult> {
  if (Platform.OS !== 'android') {
    return 'unsupported';
  }
  const module = nativeModule();
  if (!module) {
    // A build without the native module is not a build that protects anything.
    // Reporting `failed` rather than `protected` keeps the warning on screen.
    return 'failed';
  }
  try {
    await module.setSecure(true);
    return 'protected';
  } catch {
    return 'failed';
  }
}

/**
 * Clear the flag on the way out.
 *
 * Not optional housekeeping: `FLAG_SECURE` is set on the Activity window, so a
 * flag left behind makes every later screen unscreenshottable — including the
 * ones support asks customers to send.
 */
export async function releaseScreen(): Promise<void> {
  if (Platform.OS !== 'android') {
    return;
  }
  try {
    await nativeModule()?.setSecure(false);
  } catch {
    // Nothing useful to do. The next foreground sets it again, and failing a
    // dismissal because a flag could not be cleared strands the customer on the
    // one screen they most want to leave.
  }
}
