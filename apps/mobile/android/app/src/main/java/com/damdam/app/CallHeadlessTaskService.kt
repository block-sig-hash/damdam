package com.damdam.app

import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Intent
import android.os.Build
import androidx.core.app.NotificationCompat
import com.facebook.react.HeadlessJsTaskService
import com.facebook.react.bridge.Arguments
import com.facebook.react.jstasks.HeadlessJsTaskConfig

// Deliberately distinct from the "com.damdam.app.calls" channel id passed to
// RNCallKeep.setup()'s android.foregroundService.channelId (callKit.ts's
// ensureAndroidCallingReady): Android NotificationChannel importance is
// immutable after first creation, and react-native-callkeep's own
// VoiceConnectionService.startForegroundService() creates that channel at
// IMPORTANCE_NONE (confirmed by reading its native source) -- if that ran
// first (e.g. the user makes an outbound call before ever receiving an
// inbound one), a shared channel id here would permanently pin this
// service's own notification to IMPORTANCE_NONE, silently making every
// future incoming-call wake notification invisible with no error signal.
private const val CHANNEL_ID = "com.damdam.app.calls.wake"
private const val FOREGROUND_NOTIFICATION_ID = 8721
private const val TASK_KEY = "DamDamIncomingCall"
private const val TASK_TIMEOUT_MS = 30000L

/**
 * Wakes the JS engine to handle an incoming-call FCM data message even if
 * the app was fully killed -- react-native-callkeep's own README:
 * "React Native Headless Tasks are a great way to execute React Native
 * code. Remember to start up the headless task as a Foreground Service."
 *
 * Started (see DamDamFirebaseMessagingService.kt) via
 * Context.startForegroundService(), which requires this service to call
 * startForeground() within a few seconds or the OS kills the process.
 * That promotion happens here, in onCreate(), deterministically in native
 * code -- not left to the JS headless task (callKit.ts's
 * handleAndroidIncomingCallPayload), which still has to finish booting the
 * JS bundle first, and not to RNCallKeep's own foregroundService config
 * (only wired once RNCallKeep.setup() actually runs, later, inside that
 * same task) -- either of those alone could plausibly miss Android's
 * timing window on a cold start.
 */
class CallHeadlessTaskService : HeadlessJsTaskService() {
  override fun onCreate() {
    super.onCreate()
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
      val manager = getSystemService(NotificationManager::class.java)
      val channel = NotificationChannel(
        CHANNEL_ID,
        getString(R.string.call_channel),
        NotificationManager.IMPORTANCE_HIGH,
      )
      manager?.createNotificationChannel(channel)
    }
    val notification = NotificationCompat.Builder(this, CHANNEL_ID)
      .setContentTitle("DamDam")
      .setContentText(getString(R.string.incoming_call))
      .setSmallIcon(R.mipmap.ic_launcher)
      .setPriority(NotificationCompat.PRIORITY_HIGH)
      .setCategory(NotificationCompat.CATEGORY_CALL)
      .setOngoing(true)
      .build()
    startForeground(FOREGROUND_NOTIFICATION_ID, notification)
  }

  override fun getTaskConfig(intent: Intent?): HeadlessJsTaskConfig? {
    val extras = intent?.extras ?: return null
    return HeadlessJsTaskConfig(
      TASK_KEY,
      Arguments.fromBundle(extras),
      TASK_TIMEOUT_MS,
      /* allowedInForeground = */ true,
    )
  }
}
