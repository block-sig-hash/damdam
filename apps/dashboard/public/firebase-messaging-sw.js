// Handles SOS push delivery while the dashboard tab is closed or
// unfocused (AC-19.1/19.4). Config arrives as query params on the
// registration URL (see lib/push.ts) since this static file can't read
// process.env at request time.
importScripts("https://www.gstatic.com/firebasejs/12.16.0/firebase-app-compat.js");
importScripts("https://www.gstatic.com/firebasejs/12.16.0/firebase-messaging-compat.js");

const params = new URLSearchParams(self.location.search);

firebase.initializeApp({
  apiKey: params.get("apiKey"),
  authDomain: params.get("authDomain"),
  projectId: params.get("projectId"),
  messagingSenderId: params.get("messagingSenderId"),
  appId: params.get("appId"),
});

const messaging = firebase.messaging();

messaging.onBackgroundMessage((payload) => {
  const title = (payload.notification && payload.notification.title) || "DamDam SOS alert";
  const body = (payload.notification && payload.notification.body) || "";
  self.registration.showNotification(title, {
    body,
    data: payload.data,
    requireInteraction: true,
  });
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  event.waitUntil(
    self.clients
      .matchAll({type: "window", includeUncontrolled: true})
      .then((clients) => {
        const existing = clients.find((client) => "focus" in client);
        if (existing) return existing.focus();
        return self.clients.openWindow("/sos-alerts");
      }),
  );
});
