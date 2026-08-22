{{flutter_js}}
{{flutter_build_config}}

// Deliberately omit serviceWorkerSettings. Flutter's generated service worker is
// deprecated and, on a clinic kiosk, a stale shell is worse than a cold reload.
// Vercel serves the entry files with no-cache while immutable engine assets remain
// CDN-cacheable.
// Take the boot overlay down once Flutter has actually painted, not merely loaded.
// `onEntrypointLoaded` fires too early — the engine still has to initialise and render —
// so removing it there just puts the blank gap back. Two rAFs after `runApp()` is one
// frame past the first Flutter frame.
function _dismissBootOverlay() {
  const el = document.getElementById('boot');
  if (!el || el.classList.contains('done')) return;
  el.classList.add('done');
  el.addEventListener('transitionend', () => el.remove(), { once: true });
}

// Belt and braces: if the entrypoint never loads (bundle 404, network drop mid-download)
// the callback below never runs, and an overlay that stays put is worse than the blank
// page it replaced — it would sit on top of a working app and swallow every tap. The
// class also sets `pointer-events: none`, so even a stuck overlay cannot block input.
setTimeout(_dismissBootOverlay, 20000);

_flutter.loader.load({
  onEntrypointLoaded: async function (engineInitializer) {
    const appRunner = await engineInitializer.initializeEngine();
    await appRunner.runApp();
    requestAnimationFrame(() => requestAnimationFrame(_dismissBootOverlay));
  },
});
