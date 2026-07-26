import 'dart:typed_data';

import 'package:share_plus/share_plus.dart';

// Share/save PDF bytes. On native this opens the share sheet (save to Files, AirDrop,
// etc.); on web share_plus triggers a download. Mirrors the web anchor-download flow.
Future<void> sharePdfBytes(Uint8List bytes, String filename) async {
  final file = XFile.fromData(bytes, mimeType: 'application/pdf', name: filename);
  await SharePlus.instance.share(ShareParams(files: [file]));
}
