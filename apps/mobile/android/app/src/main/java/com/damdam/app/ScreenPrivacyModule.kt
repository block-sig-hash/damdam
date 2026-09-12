package com.damdam.app

import android.view.WindowManager
import com.facebook.react.bridge.Promise
import com.facebook.react.bridge.ReactApplicationContext
import com.facebook.react.bridge.ReactContextBaseJavaModule
import com.facebook.react.bridge.ReactMethod

/**
 * FLAG_SECURE, for the one screen that shows eSIM activation material.
 *
 * A Telnyx eSIM profile is one-time use and cannot be re-downloaded, so an
 * activation code that reaches a screenshot -- and from there a cloud photo
 * backup, a chat thread, or a shared gallery -- is a paid-for line somebody else
 * can install. There is nothing to rotate afterwards.
 *
 * FLAG_SECURE is the only thing Android offers here, and it covers three things
 * at once: the screenshot itself, screen recording, and the window's appearance
 * in the recent-apps thumbnail. It does not stop a second phone photographing
 * the screen, which is why the UI says so rather than implying the code is safe.
 *
 * Applied to the Activity window, so it must be cleared again when the screen is
 * left -- a flag left set makes every later screen unscreenshottable, including
 * the ones support asks customers to send.
 */
class ScreenPrivacyModule(private val context: ReactApplicationContext) :
  ReactContextBaseJavaModule(context) {
  override fun getName() = "ScreenPrivacyModule"

  @ReactMethod
  fun setSecure(secure: Boolean, promise: Promise) {
    val activity = context.currentActivity
    if (activity == null) {
      // Backgrounded between the call and here. Rejecting rather than resolving
      // is deliberate: the caller must not render the code believing the window
      // is protected when no window was touched.
      promise.reject("NO_ACTIVITY", "No foreground window to protect.")
      return
    }
    activity.runOnUiThread {
      try {
        if (secure) {
          activity.window.setFlags(
            WindowManager.LayoutParams.FLAG_SECURE,
            WindowManager.LayoutParams.FLAG_SECURE,
          )
        } else {
          activity.window.clearFlags(WindowManager.LayoutParams.FLAG_SECURE)
        }
        promise.resolve(secure)
      } catch (error: RuntimeException) {
        promise.reject("SCREEN_PRIVACY", "The window flag could not be changed.", error)
      }
    }
  }
}
