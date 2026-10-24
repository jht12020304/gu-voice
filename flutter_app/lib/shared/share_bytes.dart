import 'dart:typed_data';

import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:share_plus/share_plus.dart';

import 'pdf_download.dart';

/// Share/save bytes（SOAP PDF、研究圖 PNG）。
///
/// Native: the OS share sheet (save to Files, AirDrop, …).
///
/// Web: share_plus routes through `navigator.share(files)`, which **most desktop
/// browsers do not implement** — it throws, the caller catches, and the doctor sees
/// nothing at all (TODO §G medium). So on web we trigger a real anchor download
/// instead, matching what the React app does.
Future<void> shareBytes(Uint8List bytes, String filename, String mimeType) async {
  if (kIsWeb) {
    downloadBytes(bytes, filename, mimeType);
    return;
  }
  final file = XFile.fromData(bytes, mimeType: mimeType, name: filename);
  await SharePlus.instance.share(ShareParams(files: [file]));
}
