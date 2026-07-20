package com.damdam.app

import android.content.Intent
import android.os.Build
import android.os.Bundle
import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage

class DamDamFirebaseMessagingService : FirebaseMessagingService() {
  override fun onMessageReceived(message: RemoteMessage) {
    val data = message.data
    if (isIncomingCallPayload(data)) {
      startIncomingCallTask(data)
      return
    }
    val packageId = data["package_id"] ?: return
    ArrivalNotification.show(this, packageId)
  }

  /**
   * Telnyx's own platform sends this push directly to the device once a
   * Portal-side FCM credential is configured for this SIP connection --
   * an ops step, not code, mirroring the iOS VoIP Push Certificate
   * requirement already flagged in the iOS PR. This does not go through
   * DamDam's own backend.
   *
   * Disclosed, not hidden: these key names (call_id/voice_sdk_id/metadata)
   * are inferred from @telnyx/react-native-voice-sdk's own JS-side
   * handling (client.ts reads payload.metadata.{call_id,voice_sdk_id}),
   * not independently confirmed against a real, live Telnyx push -- the
   * same category of disclosed assumption api-spec.md's own US-01 note
   * calls for confirming against a vendor's actual docs at implementation
   * time, not guessed once and trusted forever.
   */
  private fun isIncomingCallPayload(data: Map<String, String>): Boolean {
    return data.containsKey("call_id") ||
      data.containsKey("voice_sdk_id") ||
      data.containsKey("metadata")
  }

  private fun startIncomingCallTask(data: Map<String, String>) {
    val extras = Bundle()
    for ((key, value) in data) {
      extras.putString(key, value)
    }
    val serviceIntent = Intent(this, CallHeadlessTaskService::class.java)
    serviceIntent.putExtras(extras)
    // Must be startForegroundService, not startService: this can run while
    // the app is fully backgrounded or killed, and CallHeadlessTaskService
    // promotes itself to a foreground service in its own onCreate() -- see
    // that file's doc comment for why the ordering here matters.
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
      applicationContext.startForegroundService(serviceIntent)
    } else {
      applicationContext.startService(serviceIntent)
    }
  }
}
