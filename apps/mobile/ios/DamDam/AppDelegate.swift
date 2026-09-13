import UIKit
import React
import React_RCTAppDelegate
import ReactAppDependencyProvider

@main
class AppDelegate: UIResponder, UIApplicationDelegate {
  var window: UIWindow?

  var reactNativeDelegate: ReactNativeDelegate?
  var reactNativeFactory: RCTReactNativeFactory?
  private var privacyCover: UIView?

  func applicationWillResignActive(_ application: UIApplication) {
    guard let window = window, privacyCover == nil else { return }
    // UIKit takes the app-switcher snapshot before a JS AppState callback is
    // guaranteed to render. Cover synchronously so installation material stays
    // out of that snapshot, including during system installation prompts.
    let cover = UIView(frame: window.bounds)
    cover.backgroundColor = .systemBackground
    cover.autoresizingMask = [.flexibleWidth, .flexibleHeight]
    window.addSubview(cover)
    privacyCover = cover
  }

  func applicationDidBecomeActive(_ application: UIApplication) {
    privacyCover?.removeFromSuperview()
    privacyCover = nil
  }

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

    return true
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
