{{flutter_js}}
{{flutter_build_config}}

// Deliberately omit serviceWorkerSettings. Flutter's generated service worker is
// deprecated and, on a clinic kiosk, a stale shell is worse than a cold reload.
// Vercel serves the entry files with no-cache while immutable engine assets remain
// CDN-cacheable.
_flutter.loader.load();
