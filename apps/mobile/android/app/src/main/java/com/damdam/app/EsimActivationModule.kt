package com.damdam.app

import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.os.Build
import android.telephony.SubscriptionInfo
import android.telephony.SubscriptionManager
import android.telephony.euicc.EuiccManager
import com.facebook.react.bridge.Arguments
import com.facebook.react.bridge.Promise
import com.facebook.react.bridge.ReactApplicationContext
import com.facebook.react.bridge.ReactContextBaseJavaModule
import com.facebook.react.bridge.ReactMethod

class EsimActivationModule(private val context: ReactApplicationContext) :
  ReactContextBaseJavaModule(context) {
  override fun getName() = "EsimActivationModule"

  @ReactMethod
  fun getActivationCapability(iccid: String, promise: Promise) {
    val result = Arguments.createMap()
    val subscription = manageableSubscription(iccid)
    val euiccEnabled = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
      (context.getSystemService(Context.EUICC_SERVICE) as? EuiccManager)?.isEnabled == true
    } else false
    // accessibleSubscriptionInfoList + canManageSubscription is the target-
    // profile carrier-privilege check. TelephonyManager.hasCarrierPrivileges()
    // only checks active subscriptions and would incorrectly reject the
    // inactive DamDam profile that this operation is meant to turn on.
    val canSwitch = euiccEnabled && subscription != null
    result.putBoolean("canSwitch", canSwitch)
    result.putString(
      "reason",
      when {
        Build.VERSION.SDK_INT < Build.VERSION_CODES.P -> "android_version"
        !euiccEnabled -> "euicc_unavailable"
        subscription == null -> "subscription_not_manageable"
        else -> "supported"
      },
    )
    promise.resolve(result)
  }

  @ReactMethod
  fun activateProfile(iccid: String, promise: Promise) {
    if (Build.VERSION.SDK_INT < Build.VERSION_CODES.P) {
      promise.reject("ESIM_ACTIVATION_UNSUPPORTED", "Use the manual activation guide on this device.")
      return
    }
    val manager = context.getSystemService(Context.EUICC_SERVICE) as? EuiccManager
    val subscription = manageableSubscription(iccid)
    if (manager?.isEnabled != true || subscription == null) {
      promise.reject("ESIM_ACTIVATION_MANUAL", "Use the manual activation guide on this device.")
      return
    }

    val action = "com.damdam.app.ESIM_SWITCH_RESULT.${subscription.subscriptionId}"
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
              promise.reject("ESIM_ACTIVITY", "Open DamDam to confirm eSIM activation.")
              return
            }
            try {
              manager.startResolutionActivity(
                activity,
                subscription.subscriptionId,
                resultIntent,
                callbackIntent(action, subscription.subscriptionId),
              )
            } catch (error: Exception) {
              receiverContext.unregisterReceiver(receiver)
              promise.reject("ESIM_RESOLUTION", "The system confirmation could not open.", error)
            }
          }
          else -> {
            receiverContext.unregisterReceiver(receiver)
            promise.reject("ESIM_ACTIVATION", "The device did not activate the eSIM.")
          }
        }
      }
    }
    try {
      if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
        context.registerReceiver(receiver, IntentFilter(action), Context.RECEIVER_NOT_EXPORTED)
      } else {
        @Suppress("DEPRECATION")
        context.registerReceiver(receiver, IntentFilter(action))
      }
      manager.switchToSubscription(
        subscription.subscriptionId,
        callbackIntent(action, subscription.subscriptionId),
      )
    } catch (error: SecurityException) {
      runCatching { context.unregisterReceiver(receiver) }
      promise.reject("ESIM_ACTIVATION_MANUAL", "Use the manual activation guide on this device.", error)
    }
  }

  @ReactMethod
  fun isNetworkValidated(promise: Promise) {
    val connectivity = context.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
    val capabilities = connectivity.getNetworkCapabilities(connectivity.activeNetwork)
    promise.resolve(capabilities?.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED) == true)
  }

  private fun manageableSubscription(iccid: String): SubscriptionInfo? {
    if (Build.VERSION.SDK_INT < Build.VERSION_CODES.P) return null
    val manager = context.getSystemService(Context.TELEPHONY_SUBSCRIPTION_SERVICE) as? SubscriptionManager
      ?: return null
    return try {
      manager.accessibleSubscriptionInfoList
        ?.firstOrNull { it.isEmbedded && it.iccId == iccid && manager.canManageSubscription(it) }
    } catch (_: SecurityException) {
      null
    }
  }

  private fun callbackIntent(action: String, requestCode: Int): PendingIntent =
    PendingIntent.getBroadcast(
      context,
      requestCode,
      Intent(action).setPackage(context.packageName),
      PendingIntent.FLAG_UPDATE_CURRENT or
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) PendingIntent.FLAG_MUTABLE else 0,
    )
}
