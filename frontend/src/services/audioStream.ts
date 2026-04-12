// =============================================================================
// 音訊錄製服務
// 使用 MediaRecorder + Web Audio API
// =============================================================================

export interface AudioStreamCallbacks {
  /** 收到音訊片段 (base64 encoded) */
  onChunk?: (chunk: string, chunkIndex: number) => void;
  /** 波形視覺化資料 */
  onWaveformData?: (data: number[]) => void;
  /** 錄音時長更新 (秒) */
  onDurationUpdate?: (seconds: number) => void;
  /** 錯誤 */
  onError?: (error: Error) => void;
}

class AudioStreamService {
  private mediaRecorder: MediaRecorder | null = null;
  private audioContext: AudioContext | null = null;
  private analyser: AnalyserNode | null = null;
  private stream: MediaStream | null = null;
  private chunks: Blob[] = [];
  private chunkIndex = 0;
  private animationFrame: number | null = null;
  private durationInterval: ReturnType<typeof setInterval> | null = null;
  private startTime = 0;
  private callbacks: AudioStreamCallbacks = {};

  /** 開始錄音 */
  async startRecording(callbacks: AudioStreamCallbacks): Promise<void> {
    this.callbacks = callbacks;
    this.chunks = [];
    this.chunkIndex = 0;

    try {
      // 取得麥克風權限
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          sampleRate: 16000,
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
        },
      });

      // 設定 Web Audio API 分析器（波形視覺化）
      this.audioContext = new AudioContext();
      const source = this.audioContext.createMediaStreamSource(this.stream);
      this.analyser = this.audioContext.createAnalyser();
      this.analyser.fftSize = 256;
      source.connect(this.analyser);

      // 開始波形更新
      this.startWaveformUpdates();

      // 建立 MediaRecorder
      const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
        ? 'audio/webm;codecs=opus'
        : 'audio/webm';

      this.mediaRecorder = new MediaRecorder(this.stream, {
        mimeType,
        audioBitsPerSecond: 128000,
      });

      this.mediaRecorder.ondataavailable = (event: BlobEvent) => {
        if (event.data.size > 0) {
          this.chunks.push(event.data);
          this.sendChunk(event.data);
        }
      };

      this.mediaRecorder.onerror = () => {
        this.callbacks.onError?.(new Error('MediaRecorder error'));
      };

      // 每 250ms 發送一個片段
      this.mediaRecorder.start(250);

      // 計時
      this.startTime = Date.now();
      this.durationInterval = setInterval(() => {
        const seconds = (Date.now() - this.startTime) / 1000;
        this.callbacks.onDurationUpdate?.(seconds);
      }, 100);
    } catch (error) {
      this.callbacks.onError?.(error instanceof Error ? error : new Error('Failed to start recording'));
      throw error;
    }
  }

  /** 停止錄音，回傳完整音訊 Blob */
  async stopRecording(): Promise<Blob> {
    return new Promise((resolve) => {
      if (!this.mediaRecorder || this.mediaRecorder.state === 'inactive') {
        resolve(new Blob(this.chunks, { type: 'audio/webm' }));
        this.cleanup();
        return;
      }

      this.mediaRecorder.onstop = () => {
        const blob = new Blob(this.chunks, { type: 'audio/webm' });
        this.cleanup();
        resolve(blob);
      };

      this.mediaRecorder.stop();
    });
  }

  /** 取消錄音 */
  cancelRecording(): void {
    if (this.mediaRecorder && this.mediaRecorder.state !== 'inactive') {
      this.mediaRecorder.stop();
    }
    this.cleanup();
  }

  /** 目前是否在錄音 */
  get isRecording(): boolean {
    return this.mediaRecorder?.state === 'recording';
  }

  // ---- 內部方法 ----

  private async sendChunk(blob: Blob): Promise<void> {
    try {
      const buffer = await blob.arrayBuffer();
      const base64 = btoa(
        new Uint8Array(buffer).reduce((data, byte) => data + String.fromCharCode(byte), ''),
      );
      this.callbacks.onChunk?.(base64, this.chunkIndex++);
    } catch {
      // 忽略 chunk 轉換錯誤
    }
  }

  private startWaveformUpdates(): void {
    if (!this.analyser) return;

    const bufferLength = this.analyser.frequencyBinCount;
    const dataArray = new Uint8Array(bufferLength);

    const update = () => {
      if (!this.analyser) return;
      this.analyser.getByteFrequencyData(dataArray);

      // 將 0-255 正規化為 0-1，並取前 32 個頻段
      const barCount = 32;
      const step = Math.floor(bufferLength / barCount);
      const waveformData: number[] = [];
      for (let i = 0; i < barCount; i++) {
        waveformData.push(dataArray[i * step] / 255);
      }

      this.callbacks.onWaveformData?.(waveformData);
      this.animationFrame = requestAnimationFrame(update);
    };

    this.animationFrame = requestAnimationFrame(update);
  }

  private cleanup(): void {
    // 停止波形更新
    if (this.animationFrame) {
      cancelAnimationFrame(this.animationFrame);
      this.animationFrame = null;
    }

    // 停止計時
    if (this.durationInterval) {
      clearInterval(this.durationInterval);
      this.durationInterval = null;
    }

    // 關閉音訊
    if (this.audioContext) {
      this.audioContext.close();
      this.audioContext = null;
    }
    this.analyser = null;

    // 停止媒體串流
    if (this.stream) {
      this.stream.getTracks().forEach((track) => track.stop());
      this.stream = null;
    }

    this.mediaRecorder = null;
  }
}

export const audioStreamService = new AudioStreamService();
