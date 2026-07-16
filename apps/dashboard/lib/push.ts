import {initializeApp, type FirebaseApp} from "firebase/app";
import {
  getMessaging,
  getToken,
  isSupported,
  onMessage,
  type Messaging,
} from "firebase/messaging";

import {subscribeToPushTopic} from "./api";

const firebaseConfig = {
  apiKey: process.env.NEXT_PUBLIC_FIREBASE_API_KEY ?? "",
  authDomain: process.env.NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN ?? "",
  projectId: process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID ?? "",
  messagingSenderId: process.env.NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID ?? "",
  appId: process.env.NEXT_PUBLIC_FIREBASE_APP_ID ?? "",
};

// The static service worker under public/ can't read process.env at request
// time, so its Firebase config travels as query params on the registration
// URL instead of being hardcoded into a committed file per deployment.
function serviceWorkerUrl(): string {
  const params = new URLSearchParams(firebaseConfig);
  return `/firebase-messaging-sw.js?${params.toString()}`;
}

let app: FirebaseApp | undefined;
let messaging: Messaging | undefined;

function firebaseApp(): FirebaseApp {
  if (!app) app = initializeApp(firebaseConfig);
  return app;
}

export type PushSubscriptionOutcome =
  | "subscribed"
  | "permission_denied"
  | "unsupported"
  | "error";

/**
 * Must only be called from a direct user action (a button press), never on
 * page load — Notification.requestPermission() shown unprompted is exactly
 * the anti-pattern AC-19.1 review flagged this needing to avoid.
 */
export async function enableSOSPushAlerts(): Promise<PushSubscriptionOutcome> {
  if (typeof Notification === "undefined" || !("serviceWorker" in navigator)) {
    return "unsupported";
  }
  if (!(await isSupported().catch(() => false))) {
    return "unsupported";
  }
  const permission = await Notification.requestPermission();
  if (permission !== "granted") {
    return "permission_denied";
  }
  try {
    const registration = await navigator.serviceWorker.register(serviceWorkerUrl());
    messaging = getMessaging(firebaseApp());
    const token = await getToken(messaging, {
      vapidKey: process.env.NEXT_PUBLIC_FIREBASE_VAPID_KEY,
      serviceWorkerRegistration: registration,
    });
    if (!token) return "error";
    await subscribeToPushTopic(token);
    return "subscribed";
  } catch {
    return "error";
  }
}

/**
 * Surfaces a push while the dashboard tab is open and focused. Background
 * delivery (tab closed or unfocused) is handled entirely by the service
 * worker registered in enableSOSPushAlerts, independent of this listener.
 */
export function listenForForegroundSOSPush(
  onAlert: (title: string, body: string) => void,
): () => void {
  if (!messaging) return () => undefined;
  return onMessage(messaging, (payload) => {
    onAlert(
      payload.notification?.title ?? "SOS alert",
      payload.notification?.body ?? "",
    );
  });
}
