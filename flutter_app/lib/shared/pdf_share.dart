import 'dart:typed_data';

import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:share_plus/share_plus.dart';

import 'pdf_download.dart';

/// Share/save PDF bytes.
///
/// Native: the OS share sheet (save to Files, AirDrop, …).
///
/// Web: share_plus routes through `navigator.share(files)`, which **most desktop
/// browsers do not implement** — it throws, the caller catches, and the doctor sees
/// nothing at all (TODO §G medium). So on web we trigger a real anchor download
/// instead, matching what the React app does.
Future<void> sharePdfBytes(Uint8List bytes, String filename) async {
  if (kIsWeb) {
    downloadBytes(bytes, filename, 'application/pdf');
    return;
  }
  final file = XFile.fromData(bytes, mimeType: 'application/pdf', name: filename);
  await SharePlus.instance.share(ShareParams(files: [file]));
}
