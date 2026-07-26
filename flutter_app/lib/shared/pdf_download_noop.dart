import 'dart:typed_data';

/// Native builds go through the share sheet and never call this.
void downloadBytes(Uint8List bytes, String filename, String mimeType) {
  throw UnsupportedError('downloadBytes is web-only; native uses the share sheet');
}
