// =============================================================================
// 麥克風錄音按鈕
// =============================================================================

interface MicButtonProps {
  state: 'idle' | 'recording' | 'processing' | 'disabled';
  onPress?: () => void;
  onPressIn?: () => void;
  onPressOut?: () => void;
  mode?: 'hold' | 'toggle';
  size?: 'md' | 'lg';
}

export default function MicButton({
  state,
  onPress,
  onPressIn,
  onPressOut,
  mode = 'toggle',
  size = 'lg',
}: MicButtonProps) {
  const isRecording = state === 'recording';
  const isProcessing = state === 'processing';
  const isDisabled = state === 'disabled';

  const sizeClasses = size === 'lg' ? 'h-20 w-20' : 'h-14 w-14';
  const iconSize = size === 'lg' ? 'h-8 w-8' : 'h-6 w-6';

  const handleMouseDown = () => {
    if (mode === 'hold') onPressIn?.();
  };

  const handleMouseUp = () => {
    if (mode === 'hold') onPressOut?.();
  };

  const handleClick = () => {
    if (mode === 'toggle') onPress?.();
  };

  return (
    <div className="relative inline-flex items-center justify-center">
      {/* 錄音中的脈動動畫 */}
      {isRecording && (
        <>
          <div className="absolute inset-0 animate-ping rounded-full bg-red-400 opacity-20" style={{ animationDuration: '1.5s' }} />
          <div className="absolute inset-[-8px] animate-pulse rounded-full border-2 border-red-300 opacity-50" />
        </>
      )}

      <button
        className={`relative z-10 flex items-center justify-center rounded-full transition-all ${sizeClasses} ${
          isRecording
            ? 'bg-red-500 text-white shadow-lg shadow-red-200'
            : isProcessing
              ? 'bg-yellow-500 text-white'
              : isDisabled
                ? 'bg-gray-200 text-gray-400 cursor-not-allowed'
                : 'bg-blue-600 text-white shadow-lg shadow-blue-200 hover:bg-blue-700 active:scale-95'
        }`}
        onClick={handleClick}
        onMouseDown={handleMouseDown}
        onMouseUp={handleMouseUp}
        onTouchStart={handleMouseDown}
        onTouchEnd={handleMouseUp}
        disabled={isDisabled || isProcessing}
        aria-label={isRecording ? '停止錄音' : '開始錄音'}
      >
        {isProcessing ? (
          <div className={`animate-spin rounded-full border-2 border-white border-t-transparent ${iconSize}`} />
        ) : isRecording ? (
          /* 停止圖示 */
          <svg className={iconSize} fill="currentColor" viewBox="0 0 24 24">
            <rect x="6" y="6" width="12" height="12" rx="2" />
          </svg>
        ) : (
          /* 麥克風圖示 */
          <svg className={iconSize} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z"
            />
          </svg>
        )}
      </button>
    </div>
  );
}
