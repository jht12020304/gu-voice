// =============================================================================
// WAV 編碼器（#1 pre-roll 擷取用，純函式、無 DOM 依賴）
//
// 把連續的 Float32 PCM 樣本（[-1,1]）編成 16-bit PCM mono 的單一 WAV ArrayBuffer。
// 後端 _has_valid_audio_magic 以 magic bytes 嗅測容器，WAV 只需開頭為 "RIFF"
// （backend/app/websocket/conversation_handler.py: _AUDIO_MAGIC_WAV = b"RIFF"），
// 標準 RIFF/WAVE header 即可通過；Whisper 原生支援 WAV。
//
// 為何走 WAV 而非沿用 WebM：per-utterance 把「開口前的 pre-roll」與「現場語音」
// 接成同一段時，WebM 需要 init segment、片段直接拼接會壞掉容器（現行 late-chunk
// 丟棄機制就是為此存在）。WAV 是自包含、可直接拼接的 PCM，最穩。
//
// ⚠️ sampleRate 必須帶「實際的」AudioContext.sampleRate（getUserMedia 的 16000 只是
// hint，實機常是 44100/48000）。header 與真實取樣率不符 → Whisper 會聽到變調/變速。
// =============================================================================

/**
 * 將多段 Float32 PCM frames 串接後編成 16-bit PCM mono WAV。
 * @param frames 連續的 Float32Array 樣本段（順序即時間序）
 * @param sampleRate 實際取樣率（Hz），務必用 audioContext.sampleRate
 * @returns 完整 WAV 的 ArrayBuffer（含 44-byte header）
 */
export function encodeWav(frames: Float32Array[], sampleRate: number): ArrayBuffer {
  const totalSamples = frames.reduce((n, f) => n + f.length, 0);
  const dataBytes = totalSamples * 2; // 16-bit = 2 bytes/sample
  const buffer = new ArrayBuffer(44 + dataBytes);
  const view = new DataView(buffer);

  const writeAscii = (offset: number, s: string): void => {
    for (let i = 0; i < s.length; i++) view.setUint8(offset + i, s.charCodeAt(i));
  };

  const numChannels = 1;
  const bitsPerSample = 16;
  const byteRate = (sampleRate * numChannels * bitsPerSample) / 8;
  const blockAlign = (numChannels * bitsPerSample) / 8;

  // RIFF chunk descriptor
  writeAscii(0, 'RIFF');
  view.setUint32(4, 36 + dataBytes, true); // ChunkSize = 36 + Subchunk2Size
  writeAscii(8, 'WAVE');
  // fmt subchunk
  writeAscii(12, 'fmt ');
  view.setUint32(16, 16, true); // Subchunk1Size = 16 for PCM
  view.setUint16(20, 1, true); // AudioFormat = 1 (PCM)
  view.setUint16(22, numChannels, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, byteRate, true);
  view.setUint16(32, blockAlign, true);
  view.setUint16(34, bitsPerSample, true);
  // data subchunk
  writeAscii(36, 'data');
  view.setUint32(40, dataBytes, true);

  // PCM 樣本：Float32 [-1,1] → int16 LE（clamp 防爆音）
  let offset = 44;
  for (const frame of frames) {
    for (let i = 0; i < frame.length; i++) {
      let s = frame[i];
      if (s > 1) s = 1;
      else if (s < -1) s = -1;
      // 負值用 0x8000 量化、正值用 0x7FFF，避免溢位
      view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7fff, true);
      offset += 2;
    }
  }

  return buffer;
}

/** 把 ArrayBuffer 轉為 base64（送 WS audio_chunk 用；與既有 chunk 一致以 base64 傳輸）。 */
export function arrayBufferToBase64(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let binary = '';
  const CHUNK = 0x8000; // 分段避免 String.fromCharCode 參數過多爆掉
  for (let i = 0; i < bytes.length; i += CHUNK) {
    binary += String.fromCharCode.apply(
      null,
      bytes.subarray(i, i + CHUNK) as unknown as number[],
    );
  }
  return btoa(binary);
}
