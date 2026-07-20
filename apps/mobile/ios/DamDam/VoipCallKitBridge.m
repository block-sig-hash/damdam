#import "VoipCallKitBridge.h"
#import <RNCallKeep/RNCallKeep.h>
#import "RNVoipPushNotificationManager.h"

@implementation VoipCallKitBridge

+ (void)setupCallKeepWithAppName:(NSString *)appName {
  // Native setup (rather than only RNCallKeep.setup() from JS) captures
  // events -- e.g. a call answered from the lock screen before the JS
  // bridge has finished loading -- that JS-side setup would miss. Per
  // RNCallKeep's own documented recommendation.
  [RNCallKeep setup:@{
    @"appName": appName,
    @"supportsVideo": @NO,
    @"maximumCallGroups": @1,
    @"maximumCallsPerCallGroup": @1,
  }];
}

+ (void)registerVoipPushes {
  // Registers for PushKit VoIP notifications ASAP. Doing this only from
  // JS is too late for some cold-start-from-push scenarios, per
  // react-native-voip-push-notification's own documented recommendation.
  [RNVoipPushNotificationManager voipRegistration];
}

+ (void)notifyPushCredentialsUpdated:(PKPushCredentials *)credentials ofType:(NSString *)type {
  [RNVoipPushNotificationManager didUpdatePushCredentials:credentials forType:type];
}

+ (void)reportIncomingCallFromPush:(PKPushPayload *)payload ofType:(NSString *)type {
  NSDictionary *dict = payload.dictionaryPayload;
  NSString *uuid = dict[@"uuid"] ?: [[NSUUID UUID] UUIDString];
  NSString *callerName = dict[@"callerName"] ?: @"DamDam call";
  NSString *handle = dict[@"handle"] ?: callerName;

  // Apple requires CallKit to be told about the incoming call before the
  // PushKit completion handler resolves (iOS 13+), or the app is
  // penalized -- and can be killed -- for accepting a VoIP push without
  // displaying a call. This must happen synchronously here, not deferred
  // to JS, which may not have finished loading yet on a cold start.
  [RNCallKeep reportNewIncomingCall:uuid
                              handle:handle
                          handleType:@"generic"
                            hasVideo:NO
                 localizedCallerName:callerName
                     supportsHolding:YES
                        supportsDTMF:YES
                    supportsGrouping:NO
                  supportsUngrouping:NO
                         fromPushKit:YES
                             payload:dict
               withCompletionHandler:nil];

  // Forwards the payload to JS (RNVoipPushNotification's 'notification'
  // event, or 'didLoadWithEvents' if JS hasn't finished loading yet) so
  // the Telnyx client can process it via processVoIPNotification() once
  // the app is ready -- see src/services/callKit.ts.
  [RNVoipPushNotificationManager didReceiveIncomingPushWithPayload:payload forType:type];
}

@end
