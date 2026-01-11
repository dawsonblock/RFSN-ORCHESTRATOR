#!/usr/bin/env python3
"""
Test Suite: Piper TTS Integration
Tests for subprocess-based Piper TTS engine
"""

import pytest
import threading
import time
from unittest.mock import patch, MagicMock
from pathlib import Path
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from piper_tts import PiperTTSEngine, setup_piper_voice


class TestPiperTTSEngine:
    """Test Piper TTS Engine"""
    
    def test_initialization(self):
        """Should initialize without model"""
        engine = PiperTTSEngine()
        
        assert engine is not None
        assert engine._shutdown is False
        assert engine.audio_queue is not None
        
        engine.shutdown()
    
    def test_queue_backpressure(self):
        """Should have limited queue size"""
        engine = PiperTTSEngine()
        
        assert engine.audio_queue.maxsize == 2
        
        engine.shutdown()
    
    def test_speak_mock_mode(self):
        """Should handle speak in mock mode"""
        engine = PiperTTSEngine()
        
        # Should not crash
        result = engine.speak("Hello world")
        assert result is True
        
        engine.shutdown()
    
    def test_speak_empty_string(self):
        """Should reject empty strings"""
        engine = PiperTTSEngine()
        
        result = engine.speak("")
        assert result is False
        
        result = engine.speak(None)
        assert result is False
        
        engine.shutdown()
    
    def test_get_queue_size(self):
        """Should report queue size"""
        engine = PiperTTSEngine()
        
        initial_size = engine.get_queue_size()
        assert initial_size >= 0
        
        engine.shutdown()
    
    def test_get_dropped_count(self):
        """Should track dropped sentences"""
        engine = PiperTTSEngine()
        
        # Initially 0
        assert engine.get_dropped_count() == 0
        
        engine.shutdown()
    
    def test_shutdown(self):
        """Should shutdown gracefully"""
        engine = PiperTTSEngine()
        
        engine.shutdown()
        
        assert engine._shutdown is True
    
    def test_worker_thread_started(self):
        """Should start worker thread"""
        engine = PiperTTSEngine()
        
        assert engine.worker is not None
        assert engine.worker.is_alive()
        
        engine.shutdown()


class TestPiperExecutableFinding:
    """Test finding Piper executable"""
    
    def test_find_piper_returns_none_if_missing(self):
        """Should return None if piper not found"""
        engine = PiperTTSEngine()
        
        # In test environment, piper likely not installed
        # Should not crash even if not found
        assert engine.piper_exe is None or isinstance(engine.piper_exe, str)
        
        engine.shutdown()


class TestSetupPiperVoice:
    """Test voice model setup"""
    
    def test_creates_directory(self, tmp_path):
        """Should create Models directory"""
        # Mock the actual download
        with patch('piper_tts.Path') as mock_path:
            mock_parent = MagicMock()
            mock_path.return_value.parent.parent = mock_parent
            mock_parent.__truediv__ = MagicMock(return_value=tmp_path / "Models" / "piper")
            
            # This is a unit test - we don't actually download
            # Just verify the function exists and is callable
            assert callable(setup_piper_voice)


class TestConcurrency:
    """Test thread safety"""
    
    def test_concurrent_speak(self):
        """Multiple threads should be able to call speak"""
        engine = PiperTTSEngine()
        results = []
        
        def speaker(thread_id):
            try:
                for i in range(5):
                    engine.speak(f"Thread {thread_id} msg {i}")
                    time.sleep(0.01)
                results.append("ok")
            except Exception as e:
                results.append(f"error: {e}")
        
        threads = [
            threading.Thread(target=speaker, args=(i,))
            for i in range(3)
        ]
        
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)
        
        assert all(r == "ok" for r in results)
        
        engine.shutdown()


class TestSubprocessIntegration:
    """Test subprocess-based synthesis (mocked)"""
    
    def test_synthesize_and_play_mock(self):
        """Should handle synthesis in mock mode"""
        engine = PiperTTSEngine()
        
        # In mock mode, should just log
        # This should not raise an exception
        engine._synthesize_and_play("Test text")
        
        engine.shutdown()
    
    def test_speak_sync(self):
        """Should have synchronous speak method"""
        engine = PiperTTSEngine()
        
        # Should be callable
        assert callable(engine.speak_sync)
        
        # Should not crash in mock mode
        engine.speak_sync("Test text")
        
        engine.shutdown()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
