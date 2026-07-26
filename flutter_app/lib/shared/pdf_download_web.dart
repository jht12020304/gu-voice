import 'dart:js_interop';
import 'dart:typed_data';

import 'package:web/web.dart' as web;

/// Trigger a browser download via a temporary blob URL + anchor click.
void downloadBytes(Uint8List bytes, String filename, String mimeType) {
  final blob = web.Blob(
    [bytes.toJS].toJS,
    web.BlobPropertyBag(type: mimeType),
  );
  final url = web.URL.createObjectURL(blob);
  final anchor = web.document.createElement('a') as web.HTMLAnchorElement
    ..href = url
    ..download = filename;
  anchor.click();
  // Revoke on the next turn: revoking synchronously can cancel the download in Safari.
  Future<void>.delayed(const Duration(seconds: 1), () => web.URL.revokeObjectURL(url));
}
