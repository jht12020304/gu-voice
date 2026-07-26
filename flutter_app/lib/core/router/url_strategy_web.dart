import 'package:flutter_web_plugins/url_strategy.dart';

/// Web build: drop the `#` so `/zh-TW/patient` is a real path the router can read.
void usePathUrlStrategyIfWeb() => usePathUrlStrategy();
