// =============================================================================
// 音訊錄製服務（VAD 自動切段）
// 開啟麥克風後持續監聽，依能量偵測語音開始/結束，自動分段發送
// =============================================================================

export interface AudioStreamCallbacks {
  /** 收到音訊片段 (base64 encoded)，段內每 250ms 觸發一次 */
  onChunk?: (chunk: string, chunkIndex: number) => void;
  /** 波形視覺化資料（持續更新，不只在錄音時） */
  onWaveformData?: (data: number[]) => void;
  /** 當前段落錄音時長（秒） */
  onDurationUpdate?: (seconds: number) => void;
  /** VAD 偵測到使用者開始說話 */
  onSpeechStart?: () => void;
  /** VAD 偵測到使用者停止說話（段落結束） */
  onSpeechEnd?: () => void;
  /** 錯誤 */
  onError?: (error: Error) => void;
}

interface VADConfig {
  /** RMS 能量門檻（0-1），超過視為有語音 */
  threshold: number;
  /** 超過門檻持續多少毫秒才認定為「開始說話」，避免突發雜訊 */
  minSpeechMs: number;
  /** 低於門檻持續多少毫秒才認定為「停止說話」，避免正常語句中短停頓 */
  silenceEndMs: number;
}

class AudioStreamService {
  private stream: MediaStream | null = null;
  private audioContext: AudioContext | null = null;
  private analyser: AnalyserNode | null = null;

  private mediaRecorder: MediaRecorder | null = null;
  private chunks: Blob[] = [];
  private chunkIndex = 0;
  private segmentStartTime = 0;
  /**
   * 目前活動中的段落 id（0 表示沒有段落在錄音）。
   * 每次 beginSegment 遞增，endSegment 歸零。
   * sendChunk 是 async（await blob.arrayBuffer），可能在段落結束後才 resolve；
   * 那些「遲到」的 chunk 若送到後端，會被當成下一段的開頭，導致 complete_audio
   * 開頭缺少 WebM EBML magic bytes，進而被後端拒收（INVALID_AUDIO_FORMAT）。
   * 用這個 id 比對，丟棄已結束段落的殘留 chunk。
   */
  private activeSegmentId = 0;
  private nextSegmentId = 1;

  private animationFrame: number | null = null;
  private durationInterval: ReturnType<typeof setInterval> | null = null;

  private callbacks: AudioStreamCallbacks = {};

  // VAD 狀態
  private vadEnabled = false;
  /** 'hard' = 完全靜音（不偵測），'soft' = barge-in 模式（以較高門檻偵測，允許打斷 AI） */
  private vadMuteMode: 'none' | 'hard' | 'soft' = 'none';
  private isSpeaking = false;
  private lastAboveThresholdAt = 0;
  private speechStartCandidateAt = 0;

  private readonly vadConfig: VADConfig = {
    threshold: 0.035,
    minSpeechMs: 110,
    silenceEndMs: 1200,
  };

  /** Barge-in 模式下使用的門檻（約為一般門檻的 1.7×），避免把 TTS 聲音當成使用者輸入 */
  private readonly bargeInThreshold = 0.06;

  get isRecording(): boolean {
    return this.isSpeaking;
  }

  /**
   * 開啟麥克風並持續監聽（含波形 + VAD）。
   * 成功後會保持 stream/analyser 常駐，直到 closeMic() 才釋放。
   */
  async openMic(callbacks: AudioStreamCallbacks): Promise<void> {
    this.callbacks = callbacks;

    if (this.stream) {
      // 已開啟，僅更新 callbacks
      return;
    }

    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          sampleRate: 16000,
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });

      const AC =
        window.AudioContext ??
        (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
      this.audioContext = new AC();
      if (this.audioContext.state === 'suspended') {
        await this.audioContext.resume();
      }
      const source = this.audioContext.createMediaStreamSource(this.stream);
      this.analyser = this.audioContext.createAnalyser();
      this.analyser.fftSize = 512;
      source.connect(this.analyser);

      this.vadEnabled = true;
      this.vadMuteMode = 'none';
      this.isSpeaking = false;
      this.speechStartCandidateAt = 0;
      this.lastAboveThresholdAt = 0;

      this.startAnalyserLoop();
    } catch (error) {
      this.cleanup();
      const err = error instanceof Error ? error : new Error('Failed to open mic');
      this.callbacks.onError?.(err);
      throw err;
    }
  }

  /** 關閉麥克風並釋放所有資源 */
  closeMic(): void {
    this.vadEnabled = false;
    if (this.isSpeaking) {
      this.endSegment(/* notify */ false);
    }
    this.cleanup();
  }

  /**
   * 暫停／恢復 VAD 偵測。
   *   - 'hard'：完全停止偵測（斷線或不可用時）。
   *   - 'soft'：barge-in 模式，仍在偵測但用較高門檻，使用者大聲說話即可打斷 AI。
   *   - false（或不傳）：正常偵測。
   *
   * mode 僅在 muted=true 時有意義；預設 'hard' 以向後相容。
   */
  setMuted(muted: boolean, mode: 'hard' | 'soft' = 'hard'): void {
    const nextMode: 'none' | 'hard' | 'soft' = muted ? mode : 'none';
    if (this.vadMuteMode === nextMode) return;
    const prevMode = this.vadMuteMode;
    this.vadMuteMode = nextMode;

    // 進入 hard-mute 時立即結束任何進行中的段落。
    // soft-mute（barge-in）下則不應主動結束——那裡的「說話」是使用者刻意打斷，應讓流程自然進行。
    if (nextMode === 'hard' && this.isSpeaking) {
      this.endSegment(/* notify */ true);
    }

    // 離開 mute 或從 hard 切到 soft 時重置候選計時，避免誤觸發
    if (nextMode === 'none' || (prevMode === 'hard' && nextMode === 'soft')) {
      this.isSpeaking = false;
      this.speechStartCandidateAt = 0;
      this.lastAboveThresholdAt = performance.now();
    }
  }

  /** 立即結束當前段落（外部可手動終止，例如使用者主動點結束） */
  forceEndSegment(): void {
    if (this.isSpeaking) {
      this.endSegment(/* notify */ true);
    }
  }

  // ---- 內部方法 ----

  private startAnalyserLoop(): void {
    if (!this.analyser) return;

    const bufferLength = this.analyser.frequencyBinCount;
    const timeData = new Uint8Array(this.analyser.fftSize);
    const freqData = new Uint8Array(bufferLength);

    const update = () => {
      if (!this.analyser) return;

      // 波形視覺化（頻域）
      this.analyser.getByteFrequencyData(freqData);
      const barCount = 32;
      const step = Math.floor(bufferLength / barCount);
      const waveformData: number[] = [];
      for (let i = 0; i < barCount; i++) {
        waveformData.push(freqData[i * step] / 255);
      }
      this.callbacks.onWaveformData?.(waveformData);

      // VAD：時域 RMS 能量
      this.analyser.getByteTimeDomainData(timeData);
      let sum = 0;
      for (let i = 0; i < timeData.length; i++) {
        const v = (timeData[i] - 128) / 128;
        sum += v * v;
      }
      const rms = Math.sqrt(sum / timeData.length);

      this.processVAD(rms);

      this.animationFrame = requestAnimationFrame(update);
    };

    this.animationFrame = requestAnimationFrame(update);
  }

  private processVAD(rms: number): void {
    if (!this.vadEnabled) return;
    // hard-mute 時完全跳過偵測；soft-mute（barge-in）時仍偵測但用較高門檻。
    if (this.vadMuteMode === 'hard') return;

    const now = performance.now();
    const effectiveThreshold =
      this.vadMuteMode === 'soft' ? this.bargeInThreshold : this.vadConfig.threshold;
    const above = rms > effectiveThreshold;

    if (above) {
      this.lastAboveThresholdAt = now;

      if (!this.isSpeaking) {
        if (this.speechStartCandidateAt === 0) {
          this.speechStartCandidateAt = now;
        } else if (now - this.speechStartCandidateAt >= this.vadConfig.minSpeechMs) {
          this.beginSegment();
        }
      }
    } else {
      // 低於門檻：重置「準備開始」候選
      if (!this.isSpeaking) {
        this.speechStartCandidateAt = 0;
      } else if (now - this.lastAboveThresholdAt >= this.vadConfig.silenceEndMs) {
        this.endSegment(/* notify */ true);
      }
    }
  }

  private beginSegment(): void {
    if (this.isSpeaking || !this.stream) return;

    this.isSpeaking = true;
    this.chunks = [];
    this.chunkIndex = 0;
    this.segmentStartTime = Date.now();
    this.activeSegmentId = this.nextSegmentId++;
    const thisSegmentId = this.activeSegmentId;

    const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
      ? 'audio/webm;codecs=opus'
      : 'audio/webm';

    try {
      this.mediaRecorder = new MediaRecorder(this.stream, {
        mimeType,
        audioBitsPerSecond: 128000,
      });
    } catch (error) {
      this.isSpeaking = false;
      this.callbacks.onError?.(
        error instanceof Error ? error : new Error('Failed to create MediaRecorder'),
      );
      return;
    }

    this.mediaRecorder.ondataavailable = (event: BlobEvent) => {
      if (event.data.size > 0) {
        this.chunks.push(event.data);
        this.sendChunk(event.data, thisSegmentId);
      }
    };
    this.mediaRecorder.onerror = () => {
      this.callbacks.onError?.(new Error('MediaRecorder error'));
    };
    this.mediaRecorder.start(250);

    if (this.durationInterval) clearInterval(this.durationInterval);
    this.durationInterval = setInterval(() => {
      const seconds = (Date.now() - this.segmentStartTime) / 1000;
      this.callbacks.onDurationUpdate?.(seconds);
    }, 100);

    this.callbacks.onSpeechStart?.();
  }

  private endSegment(notify: boolean): void {
    if (!this.isSpeaking) return;

    this.isSpeaking = false;
    this.speechStartCandidateAt = 0;
    // 使 activeSegmentId 失效：在這之後 resolve 的 sendChunk 會看到 id 不符而被丟棄
    this.activeSegmentId = 0;

    if (this.durationInterval) {
      clearInterval(this.durationInterval);
      this.durationInterval = null;
    }
    this.callbacks.onDurationUpdate?.(0);

    const mr = this.mediaRecorder;
    this.mediaRecorder = null;
    if (mr) {
      // 關鍵：stop() 是 async，會再觸發一次 ondataavailable 把最後一小段資料送出來。
      // 我們已經向後端送了 isFinal=true，這個殘留事件若再進來會被當成「下一段」的
      // 開頭，污染 backend audio_buffer 導致下一輪 Whisper 解不出東西。
      // 先斷開 handlers 再 stop()，讓殘留事件無處可去。
      mr.ondataavailable = null;
      mr.onerror = null;
      mr.onstop = null;
      if (mr.state !== 'inactive') {
        try {
          mr.stop();
        } catch {
          // ignore
        }
      }
    }

    if (notify) {
      this.callbacks.onSpeechEnd?.();
    }
  }

  private async sendChunk(blob: Blob, segmentId: number): Promise<void> {
    try {
      const buffer = await blob.arrayBuffer();
      // 段落已結束（或換成下一段）→ 丟棄殘留的 chunk，避免污染下一段的
      // audio_buffer 開頭（缺少 WebM EBML magic 會讓後端直接拒收整段）
      if (this.activeSegmentId !== segmentId) return;
      const base64 = btoa(
        new Uint8Array(buffer).reduce((data, byte) => data + String.fromCharCode(byte), ''),
      );
      this.callbacks.onChunk?.(base64, this.chunkIndex++);
    } catch {
      // 忽略 chunk 轉換錯誤
    }
  }

  private cleanup(): void {
    if (this.animationFrame) {
      cancelAnimationFrame(this.animationFrame);
      this.animationFrame = null;
    }
    if (this.durationInterval) {
      clearInterval(this.durationInterval);
      this.durationInterval = null;
    }

    if (this.mediaRecorder && this.mediaRecorder.state !== 'inactive') {
      try {
        this.mediaRecorder.stop();
      } catch {
        // ignore
      }
    }
    this.mediaRecorder = null;

    if (this.audioContext) {
      this.audioContext.close().catch(() => {});
      this.audioContext = null;
    }
    this.analyser = null;

    if (this.stream) {
      this.stream.getTracks().forEach((track) => track.stop());
      this.stream = null;
    }

    this.chunks = [];
    this.chunkIndex = 0;
    this.isSpeaking = false;
    this.speechStartCandidateAt = 0;
    this.activeSegmentId = 0;
  }
}

export const audioStreamService = new AudioStreamService();
