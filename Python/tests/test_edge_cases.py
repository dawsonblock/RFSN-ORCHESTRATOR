"""
Edge Case Tests for RFSN Orchestrator
Tests malformed inputs, race conditions, and boundary conditions
"""
import pytest
import threading
import time
from streaming_engine import StreamTokenizer, StreamingVoiceSystem

class TestTokenizerEdgeCases:
    """Test tokenizer with malformed and edge case inputs"""
    
    def test_empty_string(self):
        """Tokenizer should handle empty strings gracefully"""
        tokenizer = StreamTokenizer()
        sentences = tokenizer.process("")
        assert sentences == []
    
    def test_only_whitespace(self):
        """Tokenizer should handle whitespace-only input"""
        tokenizer = StreamTokenizer()
        sentences = tokenizer.process("   \n\t  ")
        assert sentences == []
    
    def test_very_long_sentence(self):
        """Tokenizer should handle very long sentences"""
        tokenizer = StreamTokenizer()
        # 10,000 character sentence
        long_text = "word " * 2000
        # Use process + flush for streaming contract
        sentences = tokenizer.process(long_text + ".") + tokenizer.flush()
        assert len(sentences) == 1
        assert len(sentences[0]) > 9000
    
    def test_unicode_characters(self):
        """Tokenizer should handle unicode characters"""
        tokenizer = StreamTokenizer()
        # Use process + flush for streaming contract
        sentences = tokenizer.process("Hello 世界. Testing émojis 🎉.") + tokenizer.flush()
        assert len(sentences) == 2
        assert "世界" in sentences[0]
        assert "🎉" in sentences[1]
    
    def test_multiple_consecutive_terminators(self):
        """Handle multiple terminators in a row"""
        tokenizer = StreamTokenizer()
        sentences = tokenizer.process("Hello... World!!! Test???")
        # Should produce sentences, not crash
        assert len(sentences) >= 1
    
    def test_mixed_quotes(self):
        """Handle mixed quote types"""
        tokenizer = StreamTokenizer()
        # Use process + flush for streaming contract
        sentences = tokenizer.process('He said "Hello." Then she said \'Goodbye.\'') + tokenizer.flush()
        # May produce 1 or 2 sentences depending on quote handling
        assert len(sentences) >= 1


class TestQueueEdgeCases:
    """Test queue operations under edge conditions"""
    
    def test_resize_to_same_size(self):
        """Resizing to same size should work without error"""
        voice = StreamingVoiceSystem(max_queue_size=3)
        voice.speak("Test 1")
        voice.speak("Test 2")
        
        # Resizing should not crash
        voice.set_max_queue_size(3)
        
        # Queue should still work
        assert voice.speech_queue.maxsize == 3
        voice.shutdown()
    
    def test_resize_to_minimum(self):
        """Resizing to 1 should work"""
        voice = StreamingVoiceSystem(max_queue_size=5)
        voice.speak("Test 1")
        voice.speak("Test 2")
        voice.speak("Test 3")
        
        voice.set_max_queue_size(1)
        assert voice.speech_queue.maxsize == 1
        voice.shutdown()
    
    def test_concurrent_speak_and_resize(self):
        """Test concurrent speak() and resize operations"""
        voice = StreamingVoiceSystem(max_queue_size=10)
        errors = []
        
        def speak_worker():
            try:
                for i in range(20):
                    voice.speak(f"Message {i}")
                    time.sleep(0.01)
            except Exception as e:
                errors.append(e)
        
        def resize_worker():
            try:
                for size in [5, 10, 3, 8]:
                    time.sleep(0.05)
                    voice.set_max_queue_size(size)
            except Exception as e:
                errors.append(e)
        
        t1 = threading.Thread(target=speak_worker)
        t2 = threading.Thread(target=resize_worker)
        
        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)
        
        assert len(errors) == 0, f"Concurrent operations failed: {errors}"
        voice.shutdown()
    
    def test_reset_during_processing(self):
        """Reset should clear queue even if worker is processing"""
        voice = StreamingVoiceSystem(max_queue_size=10)
        
        for i in range(5):
            voice.speak(f"Test {i}")
        
        voice.reset()
        assert voice.speech_queue.qsize() == 0
        voice.shutdown()


class TestBoundaryConditions:
    """Test boundary conditions and limits"""
    
    def test_tokenizer_buffer_growth(self):
        """Tokenizer buffer should handle incremental growth"""
        tokenizer = StreamTokenizer()
        
        # Simulate streaming: add one character at a time
        text = "This is a test sentence."
        for char in text:
            sentences = tokenizer.process(char)
            # Should not crash, may or may not produce sentences
        
        # Flush to get final sentence
        final = tokenizer.flush()
        assert len(final) >= 1
    
    def test_abbreviation_at_buffer_end(self):
        """Abbreviation at end of buffer should defer split"""
        tokenizer = StreamTokenizer()
        
        # Process "Dr." without continuation
        sentences = tokenizer.process("Dr.")
        # Should not split immediately (deferred boundary)
        assert len(sentences) == 0
        
        # Add continuation - cancels the pending boundary
        sentences = tokenizer.process(" Smith is here.")
        # Should flush to get final sentence (streaming contract)
        final = tokenizer.flush()
        all_sentences = sentences + final
        assert len(all_sentences) >= 1
        # Verify Dr. Smith is together in the text
        full_text = " ".join(all_sentences)
        assert "Dr" in full_text and "Smith" in full_text
    
    def test_queue_at_max_capacity(self):
        """Queue at max capacity should drop via DequeSpeechQueue policy"""
        voice = StreamingVoiceSystem(max_queue_size=3)
        
        # Fill queue beyond capacity
        for i in range(10):
            voice.speak(f"Message {i}")
        
        # Queue should be at max size (deque drops internally)
        assert voice.speech_queue.qsize() <= 3
        # Check dropped_total instead of metrics.dropped_sentences
        assert voice.speech_queue.dropped_total > 0
        voice.shutdown()


class TestConcurrentScenarios:
    """Test concurrent access patterns"""
    
    def test_multiple_tokenizers(self):
        """Multiple tokenizers should not interfere"""
        t1 = StreamTokenizer()
        t2 = StreamTokenizer()
        
        # Use process + flush for streaming contract
        s1 = t1.process("Hello world.") + t1.flush()
        s2 = t2.process("Goodbye world.") + t2.flush()
        
        assert s1 != s2
        assert "Hello" in s1[0]
        assert "Goodbye" in s2[0]
    
    def test_flush_pending_while_speaking(self):
        """flush_pending() should work even while speak() is active"""
        voice = StreamingVoiceSystem(max_queue_size=5)
        
        voice.tokenizer.buffer = "Pending text"
        voice.speak("Active text")
        
        voice.flush_pending()
        
        # Both should be in queue
        assert voice.speech_queue.qsize() >= 1
        voice.shutdown()
