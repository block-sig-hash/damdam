import UIKit
import React
import React_RCTAppDelegate
import ReactAppDependencyProvider
import PushKit

@main
class AppDelegate: UIResponder, UIApplicationDelegate {
  var window: UIWindow?

  var reactNativeDelegate: ReactNativeDelegate?
  var reactNativeFactory: RCTReactNativeFactory?

  // Held for the app's lifetime -- PKPushRegistry does not retain its own
  // delegate, and a deallocated registry stops receiving pushes.
  private var voipRegistry: PKPushRegistry?

  func application(
    _ application: UIApplication,
    didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil
  ) -> Bool {
    let delegate = ReactNativeDelegate()
    let factory = RCTReactNativeFactory(delegate: delegate)
    delegate.dependencyProvider = RCTAppDependencyProvider()

    reactNativeDelegate = delegate
    reactNativeFactory = factory

    window = UIWindow(frame: UIScreen.main.bounds)

    factory.startReactNative(
      withModuleName: "DamDam",
      in: window,
      launchOptions: launchOptions
    )

    // frontend-mobile.md §8.3 -- CallKit/PushKit setup happens here, not
    // only from JS, so a call answered from the lock screen (or a VoIP
    // push arriving) before the JS bridge finishes loading is still
    // handled correctly. See VoipCallKitBridge.h for why this goes
    // through a bridge class rather than calling RNCallKeep/
    // RNVoipPushNotificationManager directly from Swift.
    VoipCallKitBridge.setupCallKeep(appName: "DamDam")
    VoipCallKitBridge.registerVoipPushes()

    let registry = PKPushRegistry(queue: nil)
    registry.delegate = self
    registry.desiredPushTypes = [.voIP]
    voipRegistry = registry

    return true
  }
}

extension AppDelegate: PKPushRegistryDelegate {
  func pushRegistry(
    _ registry: PKPushRegistry,
    didUpdate pushCredentials: PKPushCredentials,
    for type: PKPushType
  ) {
    VoipCallKitBridge.notifyPushCredentialsUpdated(pushCredentials, ofType: type.rawValue)
  }

  func pushRegistry(_ registry: PKPushRegistry, didInvalidatePushTokenFor type: PKPushType) {
    // The system re-registers automatically and didUpdate fires again with
    // a fresh token -- no action needed here.
  }

  func pushRegistry(
    _ registry: PKPushRegistry,
    didReceiveIncomingPushWith payload: PKPushPayload,
    for type: PKPushType,
    completion: @escaping () -> Void
  ) {
    VoipCallKitBridge.reportIncomingCallFromPush(payload, ofType: type.rawValue)
    completion()
  }
}

class ReactNativeDelegate: RCTDefaultReactNativeFactoryDelegate {
  override func sourceURL(for bridge: RCTBridge) -> URL? {
    self.bundleURL()
  }

  override func bundleURL() -> URL? {
#if DEBUG
    RCTBundleURLProvider.sharedSettings().jsBundleURL(forBundleRoot: "index")
#else
    Bundle.main.url(forResource: "main", withExtension: "jsbundle")
#endif
  }
}
