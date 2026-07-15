package com.damdam.app

import android.content.Context
import android.os.Build
import android.telephony.euicc.EuiccManager
import com.facebook.react.bridge.Promise
import com.facebook.react.bridge.ReactApplicationContext
import com.facebook.react.bridge.ReactContextBaseJavaModule
import com.facebook.react.bridge.ReactMethod

/**
 * Bridges Android's EuiccManager for AC-10.1 — the only platform
 * capability API this app needs from eSIM hardware; actual profile
 * download/switching (US-11/US-13) is a separate, larger native
 * surface not implemented here.
 *
 * prd.md §5.4 refers to this check as "hasEuicc()"; the public
 * Android SDK's actual capability method is EuiccManager.isEnabled()
 * (there is no method literally named hasEuicc() in the platform
 * API), which is what's called below — same capability, PRD is using
 * shorthand prose rather than the literal SDK method name.
 */
class EsimCompatibilityModule(reactContext: ReactApplicationContext) :
    ReactContextBaseJavaModule(reactContext) {

  override fun getName(): String = "EsimCompatibility"

  @ReactMethod
  fun hasEuicc(promise: Promise) {
    try {
      if (Build.VERSION.SDK_INT < Build.VERSION_CODES.P) {
        // EuiccManager was introduced in API 28 (Android 9). Devices
        // below that floor are treated as not eSIM-capable rather
        // than erroring, since hasEuicc() genuinely can't be asked.
        promise.resolve(false)
        return
      }
      val euiccManager =
          reactApplicationContext.getSystemService(Context.EUICC_SERVICE) as? EuiccManager
      promise.resolve(euiccManager?.isEnabled == true)
    } catch (error: Exception) {
      promise.reject("esim_compatibility_check_failed", error)
    }
  }
}
