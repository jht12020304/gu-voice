import 'dart:typed_data';

import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:share_plus/share_plus.dart';

import 'pdf_download.dart';

/// Save/share a PNG (research figure export).
///
/// Same split as `sharePdfBytes`: web goes through an anchor download because desktop
/// browsers largely do not implement `navigator.share(files)`.
Future<void> sharePngBytes(Uint8List bytes, String filename) async {
  if (kIsWeb) {
    downloadBytes(bytes, filename, 'image/png');
    return;
  }
  final file = XFile.fromData(bytes, mimeType: 'image/png', name: filename);
  await SharePlus.instance.share(ShareParams(files: [file]));
}
