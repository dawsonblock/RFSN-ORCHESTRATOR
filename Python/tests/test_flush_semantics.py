import pytest
from streaming_engine import StreamingVoiceSystem, StreamTokenizer

def test_flush_pending_enqueues_buffer():
    """Verify flush_pending() enqueues remaining tokenizer buffer"""
    voice = StreamingVoiceSystem(max_queue_size=5)
    
    # Simulate buffered text
    voice.tokenizer.buffer = "Final sentence without terminator"
    
    # Flush pending should enqueue it
    voice.flush_pending()
    
    # Check queue has the item
    assert voice.speech_queue.qsize() == 1
    
    # Buffer should be cleared
    assert voice.tokenizer.buffer == ""

def test_reset_clears_everything():
    """Verify reset() clears queue, tokenizer, and metrics"""
    voice = StreamingVoiceSystem(max_queue_size=5)
    
    # Add some state
    voice.speak("Test sentence")
    voice.tokenizer.buffer = "Buffered text"
    voice.metrics.first_token_ms = 100.0
    
    # Reset should clear everything
    voice.reset()
    
    assert voice.speech_queue.qsize() == 0
    assert voice.tokenizer.buffer == ""
    assert voice.metrics.first_token_ms == 0.0
