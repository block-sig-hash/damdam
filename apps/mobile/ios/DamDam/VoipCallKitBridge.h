#import <Foundation/Foundation.h>
#import <PushKit/PushKit.h>

NS_ASSUME_NONNULL_BEGIN

/**
 * Thin Objective-C shim so AppDelegate.swift can call into RNCallKeep and
 * RNVoipPushNotificationManager (both plain Objective-C libraries with no
 * Swift module overlay of their own) with an explicit, pinned Swift name
 * via NS_SWIFT_NAME -- Clang's automatic Objective-C -> Swift name
 * translation for third-party methods (e.g. whether
 * `didReceiveIncomingPushWithPayload:forType:` imports as
 * `didReceiveIncomingPush(with:forType:)` or something else) is not
 * something this code can verify without a real Swift compiler, so this
 * shim removes that specific uncertainty for the call sites that matter
 * most: the Apple-mandated synchronous CallKit report inside the PushKit
 * handler (frontend-mobile.md §8.3).
 */
@interface VoipCallKitBridge : NSObject

+ (void)setupCallKeepWithAppName:(NSString *)appName NS_SWIFT_NAME(setupCallKeep(appName:));

+ (void)registerVoipPushes NS_SWIFT_NAME(registerVoipPushes());

+ (void)notifyPushCredentialsUpdated:(PKPushCredentials *)credentials
                               ofType:(NSString *)type
    NS_SWIFT_NAME(notifyPushCredentialsUpdated(_:ofType:));

+ (void)reportIncomingCallFromPush:(PKPushPayload *)payload
                             ofType:(NSString *)type
    NS_SWIFT_NAME(reportIncomingCallFromPush(_:ofType:));

@end

NS_ASSUME_NONNULL_END
