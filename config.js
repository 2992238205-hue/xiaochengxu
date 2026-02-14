// Default to server mode so the app always loads the latest books from backend APIs.
// This avoids "old JS / old content" issues on mobile browsers without asking users to use incognito.
window.APP_CONFIG = window.APP_CONFIG || {};

if (!window.APP_CONFIG.apiBaseUrl) {
  // Nginx should reverse proxy `/api/*` to the Flask backend (port 5000).
  window.APP_CONFIG.apiBaseUrl = "/api";
}

if (typeof window.APP_CONFIG.userCanUpload !== "boolean") {
  // Default to admin-only uploads via `/admin.html`.
  window.APP_CONFIG.userCanUpload = false;
}
