package com.damdam.app

import com.facebook.react.bridge.Promise
import com.facebook.react.bridge.ReactApplicationContext
import com.facebook.react.bridge.ReactContextBaseJavaModule
import com.facebook.react.bridge.ReactMethod
import com.google.firebase.messaging.FirebaseMessaging

/**
 * Push installation for order and eSIM notifications.
 *
 * This also registered the Saudi arrival geofence until US-30 retired arrival
 * geofencing. The React Native module name is unchanged so the JS binding and
 * the native registration stay in step; renaming it needs an Android build,
 * which this change does not run.
 */
class ArrivalPromptModule(context: ReactApplicationContext) :
  ReactContextBaseJavaModule(context) {
  override fun getName() = "ArrivalPromptModule"

  @ReactMethod
  fun getFcmToken(promise: Promise) {
    try {
      FirebaseMessaging.getInstance().token
        .addOnSuccessListener { promise.resolve(it) }
        .addOnFailureListener { promise.reject("FCM_TOKEN", "Push registration is unavailable.", it) }
    } catch (error: IllegalStateException) {
      promise.reject("FCM_CONFIGURATION", "Push registration is not configured in this build.", error)
    }
  }
}
