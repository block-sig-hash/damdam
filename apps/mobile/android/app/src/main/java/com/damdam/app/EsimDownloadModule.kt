package com.damdam.app

import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.Build
import android.telephony.euicc.DownloadableSubscription
import android.telephony.euicc.EuiccManager
import com.facebook.react.bridge.Promise
import com.facebook.react.bridge.ReactApplicationContext
import com.facebook.react.bridge.ReactContextBaseJavaModule
import com.facebook.react.bridge.ReactMethod

class EsimDownloadModule(private val context: ReactApplicationContext) :
  ReactContextBaseJavaModule(context) {
  override fun getName() = "EsimDownloadModule"

  @ReactMethod
  fun downloadProfile(activationCodeLpa: String, promise: Promise) {
    if (Build.VERSION.SDK_INT < Build.VERSION_CODES.P) {
      promise.reject("ESIM_UNSUPPORTED", "Android 9 or newer is required for eSIM download.")
      return
    }
    val manager = context.getSystemService(Context.EUICC_SERVICE) as? EuiccManager
    if (manager == null || !manager.isEnabled) {
      promise.reject("ESIM_UNSUPPORTED", "This device does not have an enabled eSIM manager.")
      return
    }
    var registeredReceiver: BroadcastReceiver? = null
    try {
      val action = "com.damdam.app.ESIM_DOWNLOAD_RESULT.${activationCodeLpa.hashCode()}"
      lateinit var receiver: BroadcastReceiver
      receiver = object : BroadcastReceiver() {
        override fun onReceive(receiverContext: Context, resultIntent: Intent) {
          when (resultCode) {
            EuiccManager.EMBEDDED_SUBSCRIPTION_RESULT_OK -> {
              receiverContext.unregisterReceiver(receiver)
              promise.resolve(null)
            }
            EuiccManager.EMBEDDED_SUBSCRIPTION_RESULT_RESOLVABLE_ERROR -> {
              val activity = context.currentActivity
              if (activity == null) {
                receiverContext.unregisterReceiver(receiver)
                promise.reject("ESIM_ACTIVITY", "Open DamDam to confirm eSIM installation.")
                return
              }
              try {
                manager.startResolutionActivity(
                  activity,
                  activationCodeLpa.hashCode(),
                  resultIntent,
                  callbackIntent(action, activationCodeLpa),
                )
              } catch (error: Exception) {
                receiverContext.unregisterReceiver(receiver)
                promise.reject("ESIM_RESOLUTION", "eSIM confirmation could not open.", error)
              }
            }
            else -> {
              receiverContext.unregisterReceiver(receiver)
              promise.reject("ESIM_DOWNLOAD", "The eSIM download was rejected by this device.")
            }
          }
        }
      }
      if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
        context.registerReceiver(receiver, IntentFilter(action), Context.RECEIVER_NOT_EXPORTED)
      } else {
        @Suppress("DEPRECATION")
        context.registerReceiver(receiver, IntentFilter(action))
      }
      registeredReceiver = receiver
      val callback = PendingIntent.getBroadcast(
        context,
        activationCodeLpa.hashCode(),
        Intent(action).setPackage(context.packageName),
        pendingIntentFlags(),
      )
      manager.downloadSubscription(
        DownloadableSubscription.forActivationCode(activationCodeLpa),
        true,
        callback,
      )
    } catch (error: SecurityException) {
      registeredReceiver?.let { runCatching { context.unregisterReceiver(it) } }
      promise.reject("ESIM_PERMISSION", "The device denied eSIM installation.", error)
    } catch (error: RuntimeException) {
      registeredReceiver?.let { runCatching { context.unregisterReceiver(it) } }
      promise.reject("ESIM_DOWNLOAD", "The eSIM download could not start.", error)
    }
  }

  private fun callbackIntent(action: String, activationCodeLpa: String): PendingIntent =
    PendingIntent.getBroadcast(
      context,
      activationCodeLpa.hashCode(),
      Intent(action).setPackage(context.packageName),
      pendingIntentFlags(),
    )

  private fun pendingIntentFlags(): Int =
    PendingIntent.FLAG_UPDATE_CURRENT or
      if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
        PendingIntent.FLAG_MUTABLE
      } else {
        0
      }
}
