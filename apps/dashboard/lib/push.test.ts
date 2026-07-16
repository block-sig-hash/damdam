import {afterEach, beforeEach, describe, expect, it, vi} from "vitest";

const getMessagingMock = vi.fn(() => ({__messaging: true}));
const getTokenMock = vi.fn();
const onMessageMock = vi.fn();
const isSupportedMock = vi.fn(async () => true);
const initializeAppMock = vi.fn(() => ({__app: true}));

vi.mock("firebase/app", () => ({initializeApp: initializeAppMock}));
vi.mock("firebase/messaging", () => ({
  getMessaging: getMessagingMock,
  getToken: getTokenMock,
  onMessage: onMessageMock,
  isSupported: isSupportedMock,
}));

const subscribeToPushTopicMock = vi.fn(async () => undefined);
vi.mock("./api", () => ({subscribeToPushTopic: subscribeToPushTopicMock}));

function stubNotification(permission: NotificationPermission) {
  const requestPermission = vi.fn(async () => permission);
  vi.stubGlobal("Notification", {permission, requestPermission});
  return requestPermission;
}

function stubServiceWorker(registration: unknown = {__registration: true}) {
  const register = vi.fn<(scriptUrl: string) => Promise<unknown>>(async () => registration);
  vi.stubGlobal("navigator", {
    ...globalThis.navigator,
    serviceWorker: {register},
  });
  return register;
}

describe("enableSOSPushAlerts", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.resetModules();
    isSupportedMock.mockResolvedValue(true);
  });
  afterEach(() => vi.unstubAllGlobals());

  it("returns unsupported when Notification is unavailable", async () => {
    vi.stubGlobal("Notification", undefined);
    stubServiceWorker();
    const {enableSOSPushAlerts} = await import("./push");

    expect(await enableSOSPushAlerts()).toBe("unsupported");
    expect(subscribeToPushTopicMock).not.toHaveBeenCalled();
  });

  it("returns unsupported when Firebase messaging isn't supported in this browser", async () => {
    isSupportedMock.mockResolvedValue(false);
    stubNotification("default");
    stubServiceWorker();
    const {enableSOSPushAlerts} = await import("./push");

    expect(await enableSOSPushAlerts()).toBe("unsupported");
    expect(subscribeToPushTopicMock).not.toHaveBeenCalled();
  });

  it("never prompts silently: requestPermission is only reachable via this call", async () => {
    const requestPermission = stubNotification("default");
    stubServiceWorker();
    const {enableSOSPushAlerts} = await import("./push");
    expect(requestPermission).not.toHaveBeenCalled();

    await enableSOSPushAlerts();

    expect(requestPermission).toHaveBeenCalledTimes(1);
  });

  it("returns permission_denied and never registers a service worker if denied", async () => {
    stubNotification("denied");
    const register = stubServiceWorker();
    const {enableSOSPushAlerts} = await import("./push");

    expect(await enableSOSPushAlerts()).toBe("permission_denied");
    expect(register).not.toHaveBeenCalled();
    expect(subscribeToPushTopicMock).not.toHaveBeenCalled();
  });

  it("registers the service worker, gets a token, and subscribes it when granted", async () => {
    stubNotification("granted");
    const registration = {__registration: true};
    const register = stubServiceWorker(registration);
    getTokenMock.mockResolvedValue("browser-fcm-token-123");
    const {enableSOSPushAlerts} = await import("./push");

    const outcome = await enableSOSPushAlerts();

    expect(outcome).toBe("subscribed");
    expect(register).toHaveBeenCalledTimes(1);
    expect(register.mock.calls[0][0]).toMatch(/^\/firebase-messaging-sw\.js\?/);
    expect(getTokenMock).toHaveBeenCalledWith(
      expect.anything(),
      expect.objectContaining({serviceWorkerRegistration: registration}),
    );
    expect(subscribeToPushTopicMock).toHaveBeenCalledWith("browser-fcm-token-123");
  });

  it("returns error and never subscribes an empty/missing token", async () => {
    stubNotification("granted");
    stubServiceWorker();
    getTokenMock.mockResolvedValue("");
    const {enableSOSPushAlerts} = await import("./push");

    expect(await enableSOSPushAlerts()).toBe("error");
    expect(subscribeToPushTopicMock).not.toHaveBeenCalled();
  });

  it("returns error if the backend subscription call fails, without throwing", async () => {
    stubNotification("granted");
    stubServiceWorker();
    getTokenMock.mockResolvedValue("browser-fcm-token-123");
    subscribeToPushTopicMock.mockRejectedValueOnce(new Error("503"));
    const {enableSOSPushAlerts} = await import("./push");

    await expect(enableSOSPushAlerts()).resolves.toBe("error");
  });
});

describe("listenForForegroundSOSPush", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.resetModules();
    isSupportedMock.mockResolvedValue(true);
  });
  afterEach(() => vi.unstubAllGlobals());

  it("surfaces the notification title/body from a foreground push payload", async () => {
    stubNotification("granted");
    stubServiceWorker();
    getTokenMock.mockResolvedValue("browser-fcm-token-123");
    let capturedListener: ((payload: unknown) => void) | undefined;
    onMessageMock.mockImplementation((_messaging, listener) => {
      capturedListener = listener;
      return () => undefined;
    });
    const {enableSOSPushAlerts, listenForForegroundSOSPush} = await import("./push");
    await enableSOSPushAlerts(); // establishes `messaging` for the listener below

    const onAlert = vi.fn();
    listenForForegroundSOSPush(onAlert);
    expect(capturedListener).toBeDefined();
    capturedListener?.({
      notification: {title: "URGENT: pilgrim SOS", body: "Amina Yusuf needs help now."},
    });

    expect(onAlert).toHaveBeenCalledWith("URGENT: pilgrim SOS", "Amina Yusuf needs help now.");
  });

  it("does nothing if no subscription has ever been established", async () => {
    const {listenForForegroundSOSPush} = await import("./push");
    const onAlert = vi.fn();

    const unsubscribe = listenForForegroundSOSPush(onAlert);

    expect(onMessageMock).not.toHaveBeenCalled();
    expect(() => unsubscribe()).not.toThrow();
  });
});
