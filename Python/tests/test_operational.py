
import pytest
import asyncio
from unittest.mock import MagicMock, patch
from orchestrator import app, health_check
from streaming_engine import StreamTokenizer

@pytest.mark.asyncio
async def test_health_check_endpoint():
    """Verify /api/health returns correct structure"""
    with patch('orchestrator.streaming_engine') as mock_engine:
        with patch('orchestrator.piper_engine') as mock_piper:
            mock_engine.llm = MagicMock()
            # Mock both qsize() and __len__() for DequeSpeechQueue compatibility
            mock_engine.voice.speech_queue.qsize.return_value = 5
            mock_engine.voice.speech_queue.__len__ = MagicMock(return_value=5)
            
            res = await health_check()
            assert res['status'] == 'healthy'
            assert res['model_loaded'] is True
            assert res['piper_ready'] is True
            assert res['queue_size'] == 5
            assert 'uptime' in res

def test_tokenizer_continuation_fix():
    """Verify tokenizer continuation logic (Patch v8.9)"""
    # Scenario: Abbreviation continuation ("Mr." + " Jones")
    # If we don't cancel pending, the timer might flush "Mr. Jones" as a fragment.
    
    tokenizer = StreamTokenizer()
    tokenizer._pending_boundary = True
    tokenizer.buffer = "Mr."
    
    # " Jones" -> Starts with space (not alnum). 
    # Old logic: keeps pending=True.
    # New logic: skips space, sees 'J', cancels pending=False.
    sentences = tokenizer.process(" Jones")
    
    # We expect "Mr." and " Jones" to merge, no split.
    assert len(sentences) == 0 
    assert tokenizer.buffer == "Mr. Jones"
    
    # CRITICAL: Pending should be CANCELLED so we don't flush explicitly
    assert not tokenizer._pending_boundary
    
    # Scenario: Deferral logic ("He said." + '"')
    # Should maintain pending because " is closer
    tokenizer = StreamTokenizer()
    tokenizer._pending_boundary = True
    tokenizer._pending_boundary_deadline = 9999999999
    tokenizer.buffer = "He said."
    
    sentences = tokenizer.process('"')
    # Expect deferral (boundary not resolved yet)
    assert len(sentences) == 0
    assert tokenizer._pending_boundary
    assert tokenizer.buffer == 'He said."'

def test_explicit_flush():
    """Verify flush returns buffer content"""
    tokenizer = StreamTokenizer()
    tokenizer.buffer = "Trailing text"
    tokenizer.in_quotes = True
    tokenizer._pending_boundary = True
    
    res = tokenizer.flush()
    assert res == ["Trailing text"]
    assert tokenizer.buffer == ""
    assert not tokenizer.in_quotes
    assert not tokenizer._pending_boundary
