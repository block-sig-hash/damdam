package com.damdam.app

import android.app.PendingIntent
import android.content.Intent
import com.facebook.react.bridge.Promise
import com.facebook.react.bridge.ReactApplicationContext
import com.facebook.react.bridge.ReactContextBaseJavaModule
import com.facebook.react.bridge.ReactMethod
import com.google.android.gms.location.Geofence
import com.google.android.gms.location.GeofencingRequest
import com.google.android.gms.location.LocationServices
import com.google.firebase.messaging.FirebaseMessaging

class ArrivalPromptModule(private val context: ReactApplicationContext) :
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

  @ReactMethod
  fun registerJeddahGeofence(packageId: String, promise: Promise) {
    val geofence = Geofence.Builder()
      .setRequestId("jeddah-arrival-$packageId")
      .setCircularRegion(JEDDAH_LATITUDE, JEDDAH_LONGITUDE, JEDDAH_RADIUS_METRES)
      .setExpirationDuration(Geofence.NEVER_EXPIRE)
      .setTransitionTypes(Geofence.GEOFENCE_TRANSITION_ENTER)
      .build()
    val request = GeofencingRequest.Builder()
      .setInitialTrigger(GeofencingRequest.INITIAL_TRIGGER_ENTER)
      .addGeofence(geofence)
      .build()
    try {
      LocationServices.getGeofencingClient(context)
        .addGeofences(request, geofencePendingIntent(packageId))
        .addOnSuccessListener { promise.resolve(null) }
        .addOnFailureListener { promise.reject("GEOFENCE_REGISTRATION", "Arrival alert could not be enabled.", it) }
    } catch (error: SecurityException) {
      promise.reject("GEOFENCE_PERMISSION", "Location permission is required for arrival alerts.", error)
    }
  }

  private fun geofencePendingIntent(packageId: String): PendingIntent = PendingIntent.getBroadcast(
    context,
    packageId.hashCode(),
    Intent(context, ArrivalGeofenceReceiver::class.java).putExtra("package_id", packageId),
    PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_MUTABLE,
  )

  companion object {
    private const val JEDDAH_LATITUDE = 21.4858
    private const val JEDDAH_LONGITUDE = 39.1925
    private const val JEDDAH_RADIUS_METRES = 150_000f
  }
}
