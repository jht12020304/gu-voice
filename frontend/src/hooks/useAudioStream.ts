// =============================================================================
// 音訊串流 Hook（自動 VAD）
// 當 enabled=true 時自動開啟麥克風持續監聽，偵測到語音自動錄製、
// 偵測到停頓自動結束並送出。AI 回應期間可透過 muteVAD/unmuteVAD 暫停。
// =============================================================================

import { useEffect, useCallback } from 'react';
import { audioStreamService } from '../services/audioStream';
import { useConversationStore } from '../stores/conversationStore';
import { conversationWS } from '../services/websocket';

export function useAudioStream(enabled: boolean) {
  const {
    isRecording,
    setRecording,
    setRecordingDuration,
    setWaveformData,
    updateSTTPartial,
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
            // 通知後端這段錄音結束，觸發 STT + LLM
            conversationWS.send('audio_chunk', {
              audioData: '',
              chunkIndex: -1,
              isFinal: true,
              format: 'wav',
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
              format: 'wav',
              sampleRate: 16000,
            });
          },
          onError: (error) => {
            console.error('[Voice] mic error:', error);
            if (error.name === 'NotAllowedError' || error.name === 'PermissionDeniedError') {
              setError('請在瀏覽器設定允許麥克風權限，然後重新載入頁面');
            } else if (error.name === 'NotFoundError') {
              setError('找不到麥克風裝置，請確認已連接麥克風');
            } else {
              setError('麥克風發生錯誤：' + error.message);
            }
          },
        });
      } catch (error) {
        if (!cancelled) {
          console.error('[Voice] 無法開啟麥克風:', error);
          const err = error as { name?: string; message?: string };
          if (err.name === 'NotAllowedError' || err.name === 'PermissionDeniedError') {
            setError('請在瀏覽器設定允許麥克風權限，然後重新載入頁面');
          } else if (err.name === 'NotFoundError') {
            setError('找不到麥克風裝置，請確認已連接麥克風');
          } else {
            setError('麥克風發生錯誤：' + (err.message ?? '未知錯誤'));
          }
        }
      }
    })();

    return () => {
      cancelled = true;
      audioStreamService.closeMic();
    };
  }, [enabled, setRecording, setRecordingDuration, setWaveformData, updateSTTPartial, setError]);

  const muteVAD = useCallback(() => {
    audioStreamService.setMuted(true);
  }, []);

  const unmuteVAD = useCallback(() => {
    audioStreamService.setMuted(false);
  }, []);

  return {
    isRecording,
    muteVAD,
    unmuteVAD,
  };
}
