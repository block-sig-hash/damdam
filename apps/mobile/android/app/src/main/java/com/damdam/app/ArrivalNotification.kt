package com.damdam.app

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat

object ArrivalNotification {
  const val COPY = "You've arrived in Saudi Arabia. Tap to activate your DamDam data — takes 30 seconds."
  private const val CHANNEL_ID = "esim_arrival"

  fun show(context: Context, packageId: String) {
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
      ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) !=
      PackageManager.PERMISSION_GRANTED
    ) return
    val manager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
      manager.createNotificationChannel(
        NotificationChannel(CHANNEL_ID, "eSIM arrival reminders", NotificationManager.IMPORTANCE_HIGH),
      )
    }
    val destination = Uri.parse("damdam://esim/activate?packageId=$packageId")
    val tapIntent = PendingIntent.getActivity(
      context,
      packageId.hashCode(),
      Intent(Intent.ACTION_VIEW, destination, context, MainActivity::class.java),
      PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
    )
    val notification = NotificationCompat.Builder(context, CHANNEL_ID)
      .setSmallIcon(com.damdam.app.R.mipmap.ic_launcher)
      .setContentTitle("Activate your DamDam eSIM")
      .setContentText(COPY)
      .setStyle(NotificationCompat.BigTextStyle().bigText(COPY))
      .setContentIntent(tapIntent)
      .setAutoCancel(true)
      .build()
    manager.notify(packageId.hashCode(), notification)
  }
}
