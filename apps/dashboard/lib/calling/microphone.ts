import { mediaSupport } from "./adapter";
import type { MicrophoneResult } from "./session";

/**
 * Ask the browser for the microphone, at the moment of the first call.
 *
 * Unlike the mobile side this is a real implementation today: `getUserMedia`
 * needs no SDK, so the browser's own prompt, its refusal and its "there is no
 * microphone attached" answer can all be handled now.
 *
 * The three outcomes are kept apart because their fixes are different:
 *
 * - **denied** — the person said no, or the site is blocked. Asking again may
 *   work; the browser's own site settings are the remedy.
 * - **no_device** — the machine has no microphone. Saying "allow access" here
 *   would send somebody to a settings page that cannot help them.
 * - **unsupported** — this browser cannot capture at all, or the page is not on
 *   a secure context. `getUserMedia` is only exposed over HTTPS, so a page
 *   served over plain HTTP has no microphone regardless of what anyone clicks.
 *
 * The track is stopped immediately. This call exists to obtain permission, not
 * to hold a capture open — leaving it running lights the browser's recording
 * indicator for as long as the tab lives, which is both alarming and untrue.
 */
export async function requestMicrophone(): Promise<MicrophoneResult> {
  if (mediaSupport() !== "supported") {
    return "unsupported";
  }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    for (const track of stream.getTracks()) {
      track.stop();
    }
    return "granted";
  } catch (error) {
    const name = (error as { name?: string })?.name;
    if (name === "NotFoundError" || name === "OverconstrainedError") {
      return "no_device";
    }
    if (name === "NotSupportedError") {
      return "unsupported";
    }
    return "denied";
  }
}
