// Path URL strategy is web-only; `flutter_web_plugins` must never be imported on
// native (it does not exist there), hence the conditional import.
export 'url_strategy_noop.dart' if (dart.library.js_interop) 'url_strategy_web.dart';
