// =============================================================================
// 音訊錄製 Hook
// =============================================================================

import { useCallback, useRef } from 'react';
import { audioStreamService } from '../services/audioStream';
import { useConversationStore } from '../stores/conversationStore';
import { conversationWS } from '../services/websocket';

export function useAudioStream() {
  const {
    isRecording,
    setRecording,
    setRecordingDuration,
    setWaveformData,
    updateSTTPartial,
  } = useConversationStore();
  const isRecordingRef = useRef(false);

  const startRecording = useCallback(async () => {
    if (isRecordingRef.current) return;
    isRecordingRef.current = true;
    setRecording(true);

    try {
      await audioStreamService.startRecording({
        onChunk: (chunk, chunkIndex) => {
          // 透過 WebSocket 發送音訊片段
          conversationWS.send('audio_chunk', {
            audioData: chunk,
            chunkIndex,
            isFinal: false,
            format: 'wav',
            sampleRate: 16000,
          });
        },
        onWaveformData: (data) => {
          setWaveformData(data);
        },
        onDurationUpdate: (seconds) => {
          setRecordingDuration(seconds);
        },
        onError: (error) => {
          console.error('錄音錯誤:', error);
          isRecordingRef.current = false;
          setRecording(false);
        },
      });
    } catch (error) {
      console.error('啟動錄音失敗:', error);
      isRecordingRef.current = false;
      setRecording(false);
    }
  }, [setRecording, setRecordingDuration, setWaveformData]);

  const stopRecording = useCallback(async () => {
    if (!isRecordingRef.current) return null;
    isRecordingRef.current = false;
    setRecording(false);

    const blob = await audioStreamService.stopRecording();

    // 發送結束標記
    conversationWS.send('audio_chunk', {
      audioData: '',
      chunkIndex: -1,
      isFinal: true,
      format: 'wav',
      sampleRate: 16000,
    });

    // 清除波形和 STT
    setWaveformData([]);
    setRecordingDuration(0);
    updateSTTPartial('');

    return blob;
  }, [setRecording, setRecordingDuration, setWaveformData, updateSTTPartial]);

  const cancelRecording = useCallback(() => {
    isRecordingRef.current = false;
    setRecording(false);
    audioStreamService.cancelRecording();
    setWaveformData([]);
    setRecordingDuration(0);
    updateSTTPartial('');
  }, [setRecording, setRecordingDuration, setWaveformData, updateSTTPartial]);

  return {
    isRecording,
    startRecording,
    stopRecording,
    cancelRecording,
  };
}
