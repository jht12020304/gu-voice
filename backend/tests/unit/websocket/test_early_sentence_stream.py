"""The first safe sentence need not wait for the complete LLM response."""
import asyncio
import pytest
from .conftest import (run_text_turn, StubLLMEngine, StubDetector, _CaptureManager,
                      make_alert, make_settings)
from app.websocket.conversation_handler import _split_completed_sentences


@pytest.mark.parametrize('language,text', [
    ('zh-TW', '第一句。第二句。'), ('en-US', 'First sentence. Second sentence.'),
    ('ja-JP', '一文目です。二文目です。'), ('ko-KR', '첫 문장입니다. 두 번째 문장입니다.'),
    ('vi-VN', 'Câu đầu tiên. Câu thứ hai.'),
])
def test_safe_first_chunk_precedes_generation_end(monkeypatch, language, text):
    cap = _CaptureManager()
    sentences, tail = _split_completed_sentences(text)
    first = sentences[0]
    prefix = text[:len(first)] + (' ' if text[len(first):].startswith(' ') else '')
    async def generate(self, *_args):
        yield prefix
        for _ in range(100):
            if cap.chunk_texts():
                break
            await asyncio.sleep(.001)
        assert cap.chunk_texts(), 'Safe first sentence waited for LLM completion'
        yield text[len(prefix):]
    monkeypatch.setattr(StubLLMEngine, 'generate_response', generate)
    result = run_text_turn(monkeypatch, manager=cap, language=language)
    assert ''.join(cap.chunk_texts()) == text
    chunks = cap.messages_of_type('ai_response_chunk')
    assert [m['payload']['chunkIndex'] for m in chunks] == list(range(len(chunks)))
    assert result.conversation_history[-1]['content'] == text
    assert len(cap.messages_of_type('ai_response_end')) == 1


@pytest.mark.parametrize('gate', ['pending', 'high', 'critical', 'failed', 'wrap_up'])
def test_unsafe_or_rewritable_output_stays_buffered(monkeypatch, gate):
    cap = _CaptureManager()
    detector = StubDetector(delay=.05) if gate == 'pending' else (
        StubDetector(error=RuntimeError('detector down')) if gate == 'failed' else
        StubDetector(alerts=[make_alert(severity=gate)]) if gate in ('high', 'critical') else StubDetector())
    async def generate(self, *_args):
        yield 'First sentence. '
        await asyncio.sleep(.01)
        assert not cap.chunk_texts(), f'{gate} bypassed gate'
        yield 'May I ask another question?'
    monkeypatch.setattr(StubLLMEngine, 'generate_response', generate)
    settings = make_settings(MAX_PATIENT_TURNS_HARD_CAP=1) if gate == 'wrap_up' else None
    run_text_turn(monkeypatch, manager=cap, detector=detector, settings=settings,
                           red_flag_wait_timeout=.1)
    assert cap.messages_of_type('ai_response_end')
    if gate == 'wrap_up':
        assert 'May I ask' not in ''.join(cap.chunk_texts())
    if gate in ('high', 'critical'):
        types = [m['message']['type'] for m in cap.session_messages]
        assert types.index('red_flag_alert') < types.index('ai_response_chunk')


def test_partial_stream_failure_closes_and_persists_heard_text(monkeypatch):
    cap = _CaptureManager()
    async def generate(self, *_args):
        yield '已確認。'
        for _ in range(100):
            if cap.chunk_texts(): break
            await asyncio.sleep(.001)
        assert cap.chunk_texts()
        yield '尚未完成且未送出的內容'
        raise RuntimeError('connection interrupted')
    monkeypatch.setattr(StubLLMEngine, 'generate_response', generate)
    result = run_text_turn(monkeypatch, manager=cap)
    assert result.conversation_history[-1]['content'] == '已確認。'
    assert cap.messages_of_type('ai_response_end')[0]['payload']['fullText'] == '已確認。'
    assert any(m['msg_type'] == 'error' for m in cap.localized_calls)
    # Redis copy must match the DB copy, else the next turn reloads a history missing this reply.
    from app.websocket import conversation_handler as ch
    assert any('已確認。' in str(c.args[2]) for c in ch._save_conversation_history.await_args_list)


def test_gate_clearing_during_wait_window_does_not_double_emit(monkeypatch):
    """red_flag_task resolves [] after the LLM finished but inside the wait_for window:
    the done-callback starts early_sender, then the main path awaits it and drains again."""
    cap = _CaptureManager()
    text = '第一句。第二句。'
    async def generate(self, *_args):
        yield text
    monkeypatch.setattr(StubLLMEngine, 'generate_response', generate)
    run_text_turn(monkeypatch, manager=cap, detector=StubDetector(delay=.02),
                  red_flag_wait_timeout=.5)
    assert ''.join(cap.chunk_texts()) == text
    chunks = cap.messages_of_type('ai_response_chunk')
    assert [m['payload']['chunkIndex'] for m in chunks] == [0, 1]
    assert len(cap.messages_of_type('ai_response_end')) == 1


def test_sentence_periods_keep_decimals_and_abbreviations():
    assert _split_completed_sentences('Dr. Chen measured 3.5 mg. Next') == (['Dr. Chen measured 3.5 mg.'], ' Next')
    assert _split_completed_sentences('3.') == ([], '3.')
    assert _split_completed_sentences('Really? Yes!') == (['Really?', 'Yes!'], '')
