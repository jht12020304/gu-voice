// =============================================================================
// 音訊串流 Hook（自動 VAD）
// 當 enabled=true 時自動開啟麥克風持續監聽，偵測到語音自動錄製、
// 偵測到停頓自動結束並送出。AI 回應期間可透過 muteVAD/unmuteVAD 暫停。
// =============================================================================

import { useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { audioStreamService } from '../services/audioStream';
import { useConversationStore } from '../stores/conversationStore';
import { conversationWS } from '../services/websocket';

/**
 * L-19：回報 MediaRecorder 實際輸出的容器格式，而非硬填 'wav'。
 *
 * 與 audioStream service 的 `pickSupportedMimeType` 候選順序保持一致：
 * Safari/iOS 用 audio/mp4，Chrome/Firefox 偏好 audio/webm。回報真實 MIME 主字串
 * （去掉 `;codecs=...`），讓 audio_chunk.format 與實際容器相符。
 *
 * 後端不信任此欄位（以 magic bytes 嗅測實際容器），此處僅為避免送出與實際不符的
 * 誤導值；無法判定時退回 ''（空字串＝未知，勝過謊報 'wav'）。
 */
function detectRecorderFormat(): string {
  if (typeof MediaRecorder === 'undefined') return '';
  const candidates = [
    'audio/mp4',
    'audio/webm;codecs=opus',
    'audio/webm',
    'audio/wav',
  ];
  for (const mime of candidates) {
    try {
      if (MediaRecorder.isTypeSupported(mime)) {
        // 去掉 codecs 參數，只回報容器 MIME（如 audio/webm）
        return mime.split(';')[0];
      }
    } catch {
      // 某些瀏覽器在不支援時會 throw，忽略
    }
  }
  return '';
}

export function useAudioStream(enabled: boolean) {
  const { t } = useTranslation(['conversation', 'common']);
  const {
    isRecording,
    setRecording,
    setRecordingDuration,
    setWaveformData,
    updateSTTPartial,
    setSttProcessing,
    setError,
  } = useConversationStore();

  // 開啟 / 關閉麥克風（根據 enabled）
  useEffect(() => {
    if (!enabled) {
      audioStreamService.closeMic();
      setRecording(false);
      setWaveformData([]);
      setRecordingDuration(0);
      return;
    }

    let cancelled = false;
    // L-19：本次錄音實際使用的容器格式（webm/mp4…），回報給後端取代硬填 'wav'。
    const recorderFormat = detectRecorderFormat();

    (async () => {
      try {
        await audioStreamService.openMic({
          onWaveformData: (data) => {
            setWaveformData(data);
          },
          onDurationUpdate: (seconds) => {
            setRecordingDuration(seconds);
          },
          onSpeechStart: () => {
            setRecording(true);
          },
          onSpeechEnd: () => {
            setRecording(false);
            updateSTTPartial('');
            // #3：進入「正在辨識」狀態（長語音轉錄期間顯示提示，避免看起來像當機）。
            // 由 ConversationPage 在 stt_final / ai_response_start / error / 重連時清除。
            setSttProcessing(true);
            // 通知後端這段錄音結束，觸發 STT + LLM
            conversationWS.send('audio_chunk', {
              audioData: '',
              chunkIndex: -1,
              isFinal: true,
              format: recorderFormat,
              sampleRate: 16000,
            });
            // 送出後即暫停 VAD，等待 AI 回應（由外部 unmuteVAD 恢復）
            audioStreamService.setMuted(true);
          },
          onChunk: (chunk, chunkIndex) => {
            conversationWS.send('audio_chunk', {
              audioData: chunk,
              chunkIndex,
              isFinal: false,
              format: recorderFormat,
              sampleRate: 16000,
            });
          },
          onError: (error) => {
            console.error('[Voice] mic error:', error);
            if (error.name === 'NotAllowedError' || error.name === 'PermissionDeniedError') {
              setError(t('conversation:error.micPermission'));
            } else if (error.name === 'NotFoundError') {
              setError(t('conversation:error.micNotFound'));
            } else {
              setError(t('conversation:error.micGeneric', { message: error.message }));
            }
          },
        });
      } catch (error) {
        if (!cancelled) {
          console.error('[Voice] 無法開啟麥克風:', error);
          const err = error as { name?: string; message?: string };
          if (err.name === 'NotAllowedError' || err.name === 'PermissionDeniedError') {
            setError(t('conversation:error.micPermission'));
          } else if (err.name === 'NotFoundError') {
            setError(t('conversation:error.micNotFound'));
          } else {
            setError(t('conversation:error.micGeneric', { message: err.message ?? t('common:unknownError') }));
          }
        }
      }
    })();

    return () => {
      cancelled = true;
      audioStreamService.closeMic();
    };
  }, [enabled, setRecording, setRecordingDuration, setWaveformData, updateSTTPartial, setSttProcessing, setError, t]);

  /** 完全停止 VAD 偵測（如斷線時） */
  const muteVAD = useCallback(() => {
    audioStreamService.setMuted(true, 'hard');
  }, []);

  /** 恢復正常 VAD 偵測 */
  const unmuteVAD = useCallback(() => {
    audioStreamService.setMuted(false);
  }, []);

  /**
   * 進入 barge-in 模式：AI 播放 TTS 期間仍保持 VAD，但用較高門檻，
   * 使用者可大聲說話打斷 AI。
   */
  const enableBargeIn = useCallback(() => {
    audioStreamService.setMuted(true, 'soft');
  }, []);

  return {
    isRecording,
    muteVAD,
    unmuteVAD,
    enableBargeIn,
  };
}
