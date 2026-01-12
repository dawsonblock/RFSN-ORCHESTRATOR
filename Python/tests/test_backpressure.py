
import threading
import time
import pytest
from streaming_engine import StreamingVoiceSystem
from streaming_voice_system import VoiceChunk, DequeSpeechQueue


def test_resize_drops_to_fit():
    """Verify that resizing drops items to fit new maxsize"""
    q = DequeSpeechQueue(maxsize=10)
    
    # Fill queue with 10 items
    for i in range(10):
        q.put(VoiceChunk(text=f"Sentence {i}", npc_id="test", created_ts=time.time()))
    
    assert q.qsize() == 10
    assert q.dropped_total == 0
    
    # Resize to 5 - should drop 5 items
    q.set_maxsize(5)
    
    assert q.qsize() == 5
    assert q.dropped_total == 5
    
    # Verify we can still get all remaining items
    items = []
    while not q.empty():
        item = q.get(timeout=0.1)
        if item:
            items.append(item.text)
    
    assert len(items) == 5


def test_resize_growth_preserves_items():
    """Verify that growing queue preserves all items"""
    q = DequeSpeechQueue(maxsize=3)
    
    # Fill queue: A, B, C
    q.put(VoiceChunk(text="A", npc_id="test", created_ts=time.time()))
    q.put(VoiceChunk(text="B", npc_id="test", created_ts=time.time()))
    q.put(VoiceChunk(text="C", npc_id="test", created_ts=time.time()))
    
    assert q.qsize() == 3
    
    # Grow to 10
    q.set_maxsize(10)
    
    assert q.qsize() == 3  # All items preserved
    assert q.maxsize == 10
    
    # Verify content order
    out = []
    while not q.empty():
        item = q.get(timeout=0.1)
        if item:
            out.append(item.text)
            
    assert out == ["A", "B", "C"]


def test_drop_policy_under_backpressure():
    """Verify drop policy kicks in when queue is full"""
    q = DequeSpeechQueue(maxsize=3)
    
    # Fill beyond capacity
    for i in range(10):
        q.put(VoiceChunk(text=f"Msg {i}", npc_id="test", created_ts=time.time()))
    
    # Queue should be at max
    assert q.qsize() == 3
    
    # Should have dropped 7 items
    assert q.dropped_total == 7


def test_close_wakes_waiting_consumer():
    """Verify that close() wakes up a blocked consumer"""
    q = DequeSpeechQueue(maxsize=3)
    
    result = []
    
    def consumer():
        item = q.get(timeout=5.0)  # Should block until close
        result.append("done" if item is None else "got_item")
    
    t = threading.Thread(target=consumer)
    t.start()
    
    time.sleep(0.1)  # Let consumer start waiting
    q.close()
    t.join(timeout=1.0)
    
    assert result == ["done"]


def test_voice_system_uses_deque_queue():
    """Verify StreamingVoiceSystem uses DequeSpeechQueue"""
    vs = StreamingVoiceSystem(max_queue_size=5)
    
    assert isinstance(vs.speech_queue, DequeSpeechQueue)
    assert vs.speech_queue.maxsize == 5
    
    vs.shutdown()
