package com.damdam.app

import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage

class DamDamFirebaseMessagingService : FirebaseMessagingService() {
  override fun onMessageReceived(message: RemoteMessage) {
    val packageId = message.data["package_id"] ?: return
    ArrivalNotification.show(this, packageId)
  }
}
