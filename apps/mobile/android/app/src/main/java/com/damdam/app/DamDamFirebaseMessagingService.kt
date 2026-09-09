package com.damdam.app

import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage

/**
 * Order and eSIM notifications.
 *
 * The incoming-call branch that woke CallHeadlessTaskService for a Telnyx
 * WebRTC call is removed with app calling (US-30, chunk 04D). Calls arrive on
 * the carrier line and are handled by the platform dialer, not by this app.
 */
class DamDamFirebaseMessagingService : FirebaseMessagingService() {
  override fun onMessageReceived(message: RemoteMessage) {
    val packageId = message.data["package_id"] ?: return
    ArrivalNotification.show(this, packageId)
  }
}
