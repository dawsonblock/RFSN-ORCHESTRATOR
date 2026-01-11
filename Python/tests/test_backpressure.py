
import queue
import threading
import time
import pytest
from streaming_engine import StreamingVoiceSystem

class MockChunk:
    def __init__(self, text):
        self.text = text

def test_resize_coherent_trimming():
    """Verify that resizing preserves First+Last and trims middle correctly"""
    # Initialize with large queue
    vs = StreamingVoiceSystem("mock", max_queue_size=10)
    # Stop worker to manually control queue without consumption
    vs._shutdown = True 
    original_worker = vs.worker
    if original_worker.is_alive():
        original_worker.join(timeout=0.1)
    
    # Fill queue: 0..9 (10 items)
    items = [f"Sentence {i}" for i in range(10)]
    for item in items:
        vs.speech_queue.put(MockChunk(item))
    
    assert vs.speech_queue.qsize() == 10
    
    # Resize to 5
    # Expected: Keep First (0), Last (9), fill rest (3 slots) from end of middle -> 6, 7, 8
    # Result: 0, 6, 7, 8, 9
    vs.set_max_queue_size(5)
    
    # Drain and check new order
    new_items = []
    while not vs.speech_queue.empty():
        c = vs.speech_queue.get()
        if c is not vs._worker_wakeup:
            new_items.append(c.text)
    
    assert len(new_items) <= 6 # 5 items + potential sentinel
    
    # Clean sentinel if present
    clean_items = [x for x in new_items if isinstance(x, str)]
    
    assert len(clean_items) == 5
    assert clean_items[0] == "Sentence 0"  # First kept
    assert clean_items[-1] == "Sentence 9" # Last kept
    # Check middle items are the most recent ones
    assert clean_items[1] == "Sentence 6"
    assert clean_items[2] == "Sentence 7"
    assert clean_items[3] == "Sentence 8"

def test_resize_growth():
    """Verify that growing queue preserves all items"""
    vs = StreamingVoiceSystem("mock", max_queue_size=3)
    vs._shutdown = True
    
    # Fill queue: A, B, C
    vs.speech_queue.put(MockChunk("A"))
    vs.speech_queue.put(MockChunk("B"))
    vs.speech_queue.put(MockChunk("C"))
    
    # Grow to 10
    vs.set_max_queue_size(10)
    
    assert vs.speech_queue.qsize() >= 3
    
    # Verify content
    out = []
    while not vs.speech_queue.empty():
        c = vs.speech_queue.get()
        if c is not vs._worker_wakeup:
            out.append(c.text)
            
    assert out == ["A", "B", "C"]

def test_resize_wake_sentinel():
    """Verify that resizing puts a sentinel to wake the worker"""
    vs = StreamingVoiceSystem("mock", max_queue_size=5)
    vs._shutdown = True
    
    vs.set_max_queue_size(10)
    
    # Check if sentinel is in queue
    found_sentinel = False
    while not vs.speech_queue.empty():
        c = vs.speech_queue.get()
        if c is vs._worker_wakeup:
            found_sentinel = True
            
    assert found_sentinel
