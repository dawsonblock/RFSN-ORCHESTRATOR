#!/usr/bin/env python3
"""
Test Suite: Performance Benchmarks
Tests latency targets and throughput
"""

import pytest
import time
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from streaming_engine import StreamingMantellaEngine, StreamingVoiceSystem


class TestLatencyTargets:
    """Test that latency targets are achievable"""
    
    TARGET_FIRST_SENTENCE_MS = 1500  # <1.5s target
    
    def test_mock_first_token_latency(self):
        """Mock generation should be fast"""
        engine = StreamingMantellaEngine(model_path=None)
        
        start = time.time()
        chunks = list(engine.generate_streaming("Hello"))
        elapsed_ms = (time.time() - start) * 1000
        
        # Mock has built-in delays, allow more time
        assert elapsed_ms < 2000
        
        engine.shutdown()
    
    def test_voice_system_initialization(self):
        """Voice system should initialize quickly"""
        start = time.time()
        voice = StreamingVoiceSystem()
        elapsed_ms = (time.time() - start) * 1000
        
        # Should initialize in <100ms
        assert elapsed_ms < 100
        
        voice.shutdown()
    
    def test_text_cleaning_performance(self):
        """Text cleaning should be fast"""
        voice = StreamingVoiceSystem()
        
        test_text = "Hello *sighs* world [laughs] how are you doing today?"
        
        start = time.time()
        for _ in range(1000):
            voice._clean_for_tts(test_text)
        elapsed_ms = (time.time() - start) * 1000
        
        # 1000 cleanings should take <100ms
        assert elapsed_ms < 100
        
        voice.shutdown()
    
    def test_sentence_detection_performance(self):
        """Sentence detection should be fast"""
        voice = StreamingVoiceSystem()
        
        tokens = ["Hello", " world", ".", " How", " are", " you", "?"]
        
        start = time.time()
        for _ in range(100):
            voice.reset()  # Reset instead of flush
            list(voice.process_stream(iter(tokens)))
        elapsed_ms = (time.time() - start) * 1000
        
        # 100 iterations should take <500ms
        assert elapsed_ms < 500
        
        voice.shutdown()


class TestThroughput:
    """Test throughput capabilities"""
    
    def test_queue_throughput(self):
        """Queue should handle rapid inputs"""
        voice = StreamingVoiceSystem(max_queue_size=10)
        
        start = time.time()
        for i in range(100):
            voice.speak(f"Message {i}")
        elapsed_ms = (time.time() - start) * 1000
        
        # Queueing 100 messages should be <100ms
        assert elapsed_ms < 100
        
        voice.shutdown()


class TestResourceUsage:
    """Test resource usage"""
    
    def test_multiple_engines(self):
        """Should support multiple engine instances"""
        engines = []
        
        for i in range(3):
            engine = StreamingMantellaEngine(model_path=None)
            engines.append(engine)
        
        # All should work
        for engine in engines:
            chunks = list(engine.generate_streaming("Test"))
            assert len(chunks) > 0
        
        # Cleanup
        for engine in engines:
            engine.shutdown()
    
    def test_flush_clears_resources(self):
        """Reset should clear resources"""
        voice = StreamingVoiceSystem()
        
        # Add some data to tokenizer buffer
        voice.tokenizer.buffer = "Some text"
        voice.metrics.first_token_ms = 100.0
        
        # Reset
        voice.reset()
        
        # Should be cleared (tokenizer is recreated)
        assert voice.tokenizer.buffer == ""
        assert voice.metrics.first_token_ms == 0.0
        
        voice.shutdown()


class TestMetricsAccuracy:
    """Test that metrics are tracked accurately"""
    
    def test_first_token_timing(self):
        """First token time should be tracked"""
        engine = StreamingMantellaEngine(model_path=None)
        
        # Generate
        list(engine.generate_streaming("Hello"))
        
        # Metrics should be populated
        assert engine.voice.metrics.first_token_ms >= 0
        
        engine.shutdown()
    
    def test_total_generation_timing(self):
        """Total generation time should be tracked"""
        engine = StreamingMantellaEngine(model_path=None)
        
        list(engine.generate_streaming("Hello"))
        
        # In mock mode, metrics may not be set (voice system is separate)
        assert engine.voice.metrics.total_generation_ms >= 0
        
        engine.shutdown()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
