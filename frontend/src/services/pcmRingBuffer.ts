// =============================================================================
// PCM 環形緩衝（#1 pre-roll 擷取用，純函式、無 DOM 依賴）
//
// 持續寫入麥克風的 Float32 PCM；只保留「最近 capacity 個樣本」（環形覆蓋最舊）。
// 用途：在偵測到「開始說話」的瞬間，回頭取出開口「前」約 300-500ms 的音訊當 pre-roll，
// 補回現行 VAD 因 minSpeechMs 確認窗 + MediaRecorder 啟動延遲而吃掉的句首。
// =============================================================================

export class PcmRingBuffer {
  private readonly buf: Float32Array;
  private readonly capacity: number;
  private writePos = 0;
  private filled = 0;

  /** @param capacity 最多保留的樣本數（建議 = 實際取樣率 × pre-roll 秒數，如 48000×0.5） */
  constructor(capacity: number) {
    if (!Number.isInteger(capacity) || capacity <= 0) {
      throw new Error('PcmRingBuffer capacity must be a positive integer');
    }
    this.capacity = capacity;
    this.buf = new Float32Array(capacity);
  }

  /** 寫入一段樣本；超過容量時環形覆蓋最舊。 */
  write(samples: Float32Array): void {
    for (let i = 0; i < samples.length; i++) {
      this.buf[this.writePos] = samples[i];
      this.writePos = (this.writePos + 1) % this.capacity;
      if (this.filled < this.capacity) this.filled++;
    }
  }

  /** 目前可讀樣本數（最多 capacity）。 */
  available(): number {
    return this.filled;
  }

  /**
   * 取出「最近 n 個」樣本（時間序，舊→新）。n 大於現有量時回傳全部現有樣本。
   * 不改動緩衝狀態（純讀）。
   */
  readLast(n: number): Float32Array {
    const count = Math.min(n, this.filled);
    const out = new Float32Array(count);
    if (count === 0) return out;
    // 最新樣本的位置是 writePos-1；往回數 count 個即起點。
    let start = (this.writePos - count) % this.capacity;
    if (start < 0) start += this.capacity;
    for (let i = 0; i < count; i++) {
      out[i] = this.buf[(start + i) % this.capacity];
    }
    return out;
  }

  /** 清空（換場次 / 重新開麥時用）。 */
  clear(): void {
    this.writePos = 0;
    this.filled = 0;
  }
}
