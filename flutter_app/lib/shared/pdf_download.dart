// Anchor-download is web-only; `dart:html`/`package:web` must never be imported on
// native, hence the conditional export.
export 'pdf_download_noop.dart' if (dart.library.js_interop) 'pdf_download_web.dart';
