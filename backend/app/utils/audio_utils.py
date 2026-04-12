"""
音訊處理工具函式
- 格式驗證
- 音訊時長計算
- 取樣率轉換
"""

import io
import struct
import wave
from typing import Optional


# 支援的音訊格式
SUPPORTED_FORMATS = {"wav", "webm", "ogg"}

# WAV 檔案魔術數字
WAV_MAGIC = b"RIFF"
WAV_WAVE = b"WAVE"


def validate_audio_format(data: bytes) -> tuple[bool, Optional[str]]:
    """
    驗證音訊資料格式

    Args:
        data: 音訊二進制資料

    Returns:
        (is_valid, error_message) — 驗證通過時 error_message 為 None
    """
    if not data or len(data) < 12:
        return False, "音訊資料為空或長度不足"

    # 檢查 WAV 格式
    if data[:4] == WAV_MAGIC and data[8:12] == WAV_WAVE:
        return True, None

    # 檢查 OGG 格式（OggS 標頭）
    if data[:4] == b"OggS":
        return True, None

    # 檢查 WebM 格式（EBML 標頭）
    if data[:4] == b"\x1a\x45\xdf\xa3":
        return True, None

    return False, "不支援的音訊格式，僅支援 WAV / OGG / WebM"


def calculate_duration(data: bytes) -> Optional[float]:
    """
    計算 WAV 音訊時長（秒）

    Args:
        data: WAV 格式的音訊二進制資料

    Returns:
        音訊時長（秒），非 WAV 格式回傳 None
    """
    if not data or len(data) < 44:
        return None

    # 僅支援 WAV 精確計算
    if data[:4] != WAV_MAGIC:
        return None

    try:
        with io.BytesIO(data) as buf:
            with wave.open(buf, "rb") as wf:
                frames = wf.getnframes()
                rate = wf.getframerate()
                if rate <= 0:
                    return None
                return round(frames / rate, 2)
    except Exception:
        return None


def convert_sample_rate(data: bytes, target_rate: int = 16000) -> Optional[bytes]:
    """
    轉換 WAV 音訊取樣率

    Args:
        data: 原始 WAV 音訊資料
        target_rate: 目標取樣率（預設 16000 Hz，STT 使用）

    Returns:
        轉換後的 WAV 音訊資料，失敗時回傳 None

    Note:
        使用簡單的線性插值進行重新取樣。
        生產環境建議使用 librosa 或 scipy 進行高品質重新取樣。
    """
    if not data or len(data) < 44:
        return None

    try:
        with io.BytesIO(data) as in_buf:
            with wave.open(in_buf, "rb") as wf:
                n_channels = wf.getnchannels()
                sample_width = wf.getsampwidth()
                original_rate = wf.getframerate()
                frames = wf.readframes(wf.getnframes())

        # 如果取樣率已經相同，直接回傳
        if original_rate == target_rate:
            return data

        # 解析 PCM 樣本
        if sample_width == 2:
            fmt = f"<{len(frames) // 2}h"
            samples = list(struct.unpack(fmt, frames))
        else:
            return None  # 僅支援 16-bit PCM

        # 計算重新取樣比率
        ratio = target_rate / original_rate
        new_length = int(len(samples) * ratio / n_channels) * n_channels

        # 線性插值重新取樣
        resampled: list[int] = []
        for i in range(new_length):
            original_idx = i / ratio
            idx = int(original_idx)
            frac = original_idx - idx

            if idx + 1 < len(samples):
                val = samples[idx] * (1 - frac) + samples[idx + 1] * frac
            else:
                val = samples[min(idx, len(samples) - 1)]

            resampled.append(int(max(-32768, min(32767, val))))

        # 寫入新的 WAV
        out_buf = io.BytesIO()
        with wave.open(out_buf, "wb") as wf_out:
            wf_out.setnchannels(n_channels)
            wf_out.setsampwidth(sample_width)
            wf_out.setframerate(target_rate)
            wf_out.writeframes(
                struct.pack(f"<{len(resampled)}h", *resampled)
            )

        return out_buf.getvalue()

    except Exception:
        return None
