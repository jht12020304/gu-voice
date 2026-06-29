// =============================================================================
// 音訊錄製服務（VAD 自動切段）
// 開啟麥克風後持續監聽，依能量偵測語音開始/結束，自動分段發送
//
// #1 pre-roll 擷取（VITE_VAD_PREROLL，預設開、可用 =false 退關）：
//   原本做法是「偵測到說話才現場建 MediaRecorder」，句首 ~minSpeechMs + recorder 啟動 +
//   第一個 250ms chunk 會被吃掉（病患回報「第一個字錄不到」）。ON 時改走連續 PCM
//   擷取：用 ScriptProcessor tap 持續把 PCM 寫進 ring buffer，開口瞬間回頭取 pre-roll，
//   整段（pre-roll + 現場）編成單一 WAV 送出，繞過 MediaRecorder/WebM 分段問題。
//   WAV 以實際 audioContext 取樣率編碼（見 prerollSampleRate），不會變調。
//   ⚠️ 改為預設開（真實麥克風測試確認句首截斷仍在）。任何 pre-roll 失敗都會 fallback 回
//      MediaRecorder 路徑，確保不會弄壞生產問診；若特定裝置（如舊 iOS Safari）異常，
//      可在該環境設 VITE_VAD_PREROLL=false 退回舊行為。
// =============================================================================

import { PcmRingBuffer } from './pcmRingBuffer';
import { encodeWav, arrayBufferToBase64 } from './wavEncoder';

/** build-time feature flag（對齊既有 VITE_ENABLE_MOCK 慣例）；預設開，設 'false' 退關。 */
const PREROLL_ENABLED = import.meta.env.VITE_VAD_PREROLL !== 'false';
/**
 * #4：關閉瀏覽器自動增益控制（AGC）。預設關（保持現行 AGC 開）。
 * 病患回報「講一句很不標準/很大聲的話後，接下來幾句辨識變差」——推測是 AGC 跨段把增益壓低、
 * 恢復慢，污染後續擷取。設 VITE_VAD_DISABLE_AGC=true 可在實機 A/B 驗證是否為 AGC 所致；
 * 確認有效並重新校準 VAD 門檻後再考慮預設開。
 */
const DISABLE_AGC = import.meta.env.VITE_VAD_DISABLE_AGC === 'true';
/** pre-roll 取多長（秒）— 補回句首被吃掉的部分。 */
const PREROLL_SECONDS = 0.4;
/** ring buffer 保留長度（秒）— 略大於 pre-roll 即可。 */
const PREROLL_RING_SECONDS = 1.0;

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

/**
 * 依序嘗試可用的 MediaRecorder MIME type。
 * Safari / iOS 不支援 audio/webm，只接受 audio/mp4；Chrome / Firefox 則偏好 audio/webm。
 * 全部都不支援時回傳 undefined，讓瀏覽器自動挑選預設格式。
 */
function pickSupportedMimeType(): string | undefined {
  if (typeof MediaRecorder === 'undefined') return undefined;
  const candidates = [
    'audio/mp4',
    'audio/webm;codecs=opus',
    'audio/webm',
    'audio/wav',
  ];
  for (const mime of candidates) {
    try {
      if (MediaRecorder.isTypeSupported(mime)) return mime;
    } catch {
      // 某些瀏覽器在不支援時會 throw，忽略即可
    }
  }
  return undefined;
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

  // #1 pre-roll 擷取狀態（僅 PREROLL_ENABLED 時使用）
  private pcmRing: PcmRingBuffer | null = null;
  private scriptNode: ScriptProcessorNode | null = null;
  private silentSink: GainNode | null = null;
  private liveFrames: Float32Array[] = [];
  private prerollSampleRate = 16000;
  /** 本段是否正以 pre-roll PCM 路徑擷取（決定 endSegment 要不要編 WAV 送出）。 */
  private capturingPcm = false;

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
    // 110→90：略縮「確認開始說話」窗口以減少句首被吃（#1 暫時緩解）。不取更低的 70，
    // 因為太低會讓雜訊/AGC 突波更常開出空段落，徒增空 STT 與佔用 LLM 配額；真正解是
    // pre-roll 連續擷取（Pass 2，需真實麥克風驗 STT）。空 STT 已由前端 re-arm VAD 防鎖死。
    minSpeechMs: 90,
    // 1200→2000：放寬「停頓視為講完」的容忍，避免長輩/思考時的自然停頓被誤判結束、
    // AI 搶話（#5）。代價是每輪句末多約 0.8s 延遲；真正解是停頓寬限視窗（Pass 2）。
    silenceEndMs: 2000,
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
          // #4：AGC 跨段自適應疑似污染後續辨識；可用 VITE_VAD_DISABLE_AGC=true 關閉驗證。
          autoGainControl: !DISABLE_AGC,
        },
      });

      // iOS Safari <14.5 沒有標準 AudioContext，僅暴露前綴版本 webkitAudioContext
      const AC =
        window.AudioContext ??
        (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
      if (!AC) {
        throw new Error('AudioContext not supported in this browser');
      }
      this.audioContext = new AC();
      if (this.audioContext.state === 'suspended') {
        await this.audioContext.resume();
      }
      const source = this.audioContext.createMediaStreamSource(this.stream);
      this.analyser = this.audioContext.createAnalyser();
      this.analyser.fftSize = 512;
      source.connect(this.analyser);

      // #1 pre-roll：flag ON 時掛一個連續 PCM tap，持續把樣本寫進 ring buffer。
      // 用「實際的」audioContext.sampleRate（getUserMedia 的 16000 只是 hint，實機常為
      // 44100/48000）；WAV header 也用這個值，避免 Whisper 聽到變調/變速。
      // 任何建立失敗都吞掉並維持 pcmRing=null → beginSegment 會自動走 MediaRecorder fallback。
      if (PREROLL_ENABLED) {
        try {
          this.prerollSampleRate = this.audioContext.sampleRate || 16000;
          this.pcmRing = new PcmRingBuffer(
            Math.max(1, Math.floor(this.prerollSampleRate * PREROLL_RING_SECONDS)),
          );
          // ScriptProcessor 已 deprecated 但相容性最廣（含 iOS）；本路徑本就在 flag 後、
          // 需真機驗證，未來可換 AudioWorklet。connect 到 0 增益 sink 才會觸發 onaudioprocess，
          // 同時避免把麥克風 routed 回喇叭造成回授。
          this.scriptNode = this.audioContext.createScriptProcessor(4096, 1, 1);
          this.silentSink = this.audioContext.createGain();
          this.silentSink.gain.value = 0;
          this.scriptNode.onaudioprocess = (ev: AudioProcessingEvent) => {
            const input = ev.inputBuffer.getChannelData(0);
            // 必須複製：inputBuffer 會被引擎重複使用，直接存參考會被後續覆寫。
            const copy = new Float32Array(input.length);
            copy.set(input);
            this.pcmRing?.write(copy);
            if (this.capturingPcm) this.liveFrames.push(copy);
          };
          source.connect(this.scriptNode);
          this.scriptNode.connect(this.silentSink);
          this.silentSink.connect(this.audioContext.destination);
        } catch (err) {
          // pre-roll 不可用 → 清掉、走 fallback，不影響主流程
          this.pcmRing = null;
          this.scriptNode = null;
          this.silentSink = null;
          // eslint-disable-next-line no-console
          console.warn('[Voice] pre-roll tap 建立失敗，改用 MediaRecorder 路徑:', err);
        }
      }

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
      // 此分支刻意不呼叫 endSegment；若正在 pre-roll 擷取，務必一併收掉，否則
      // capturingPcm 會殘留 true、liveFrames 無限累積（PCM 路徑的孤兒洩漏）。
      this.capturingPcm = false;
      this.liveFrames = [];
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

    // #1 pre-roll 路徑（flag ON 且 tap 健康）：用 ring 裡開口「前」的 PCM 當 pre-roll，
    // 之後 onaudioprocess 會持續把現場 PCM 推進 liveFrames；endSegment 才編成單一 WAV 送出。
    // 不建立 MediaRecorder，故無句首截斷、無 WebM 分段污染。失敗則落到下方 MediaRecorder。
    if (PREROLL_ENABLED && this.pcmRing) {
      const prerollSamples = Math.floor(this.prerollSampleRate * PREROLL_SECONDS);
      const preroll = this.pcmRing.readLast(prerollSamples);
      this.liveFrames = preroll.length > 0 ? [preroll] : [];
      this.capturingPcm = true;

      if (this.durationInterval) clearInterval(this.durationInterval);
      this.durationInterval = setInterval(() => {
        const seconds = (Date.now() - this.segmentStartTime) / 1000;
        this.callbacks.onDurationUpdate?.(seconds);
      }, 100);

      this.callbacks.onSpeechStart?.();
      return;
    }

    // Safari / iOS 不支援 audio/webm，僅支援 audio/mp4；依序挑第一個可用的 MIME。
    // 若所有候選都不支援，fallback 為 undefined，讓瀏覽器自選格式。
    const mimeType = pickSupportedMimeType();

    try {
      this.mediaRecorder = new MediaRecorder(
        this.stream,
        mimeType
          ? { mimeType, audioBitsPerSecond: 128000 }
          : { audioBitsPerSecond: 128000 },
      );
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
    // #4 防禦：清空 pre-roll ring，避免「上一句的尾巴」殘留被下一段的 0.4s pre-roll 取到而污染。
    // 本段的 pre-roll 已在 beginSegment 讀進 liveFrames，清空不影響本段，只影響後續。
    this.pcmRing?.clear();

    if (this.durationInterval) {
      clearInterval(this.durationInterval);
      this.durationInterval = null;
    }
    this.callbacks.onDurationUpdate?.(0);

    // #1 pre-roll 路徑：把 pre-roll + 現場 PCM 編成單一 WAV，當作這段唯一的 chunk 送出，
    // 隨後 onSpeechEnd 會送 isFinal=true。任何編碼/送出錯誤都吞掉、仍照常 onSpeechEnd
    // （後端收到空音訊 → 回空 STT → 前端 re-arm VAD，不會卡住）。
    if (this.capturingPcm) {
      this.capturingPcm = false;
      const frames = this.liveFrames;
      this.liveFrames = [];
      // notify=false 代表 closeMic/teardown：此時不會再送 isFinal，送了 WAV chunk 也只會
      // 滯留在後端 buffer（連線即將關閉），故僅在 notify 時才編碼送出。
      if (notify) {
        try {
          const totalSamples = frames.reduce((n, f) => n + f.length, 0);
          if (totalSamples > 0) {
            const wav = encodeWav(frames, this.prerollSampleRate);
            this.callbacks.onChunk?.(arrayBufferToBase64(wav), 0);
          }
        } catch (err) {
          // eslint-disable-next-line no-console
          console.warn('[Voice] pre-roll WAV 編碼/送出失敗，本段以空音訊收尾:', err);
        }
        this.callbacks.onSpeechEnd?.();
      }
      return;
    }

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

    // #1 pre-roll tap 拆除（順序：先斷 handler 再 disconnect，避免殘留 onaudioprocess）
    if (this.scriptNode) {
      this.scriptNode.onaudioprocess = null;
      try {
        this.scriptNode.disconnect();
      } catch {
        // ignore
      }
      this.scriptNode = null;
    }
    if (this.silentSink) {
      try {
        this.silentSink.disconnect();
      } catch {
        // ignore
      }
      this.silentSink = null;
    }
    this.pcmRing = null;
    this.liveFrames = [];
    this.capturingPcm = false;

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
