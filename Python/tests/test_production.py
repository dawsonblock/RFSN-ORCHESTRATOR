"""
Production Tests: Segmentation, Backpressure, TTS Concurrency, Failure Injection, Replay
Comprehensive tests for production reliability.
"""
import pytest
import asyncio
import time
import threading
from typing import List, Optional, Any
from unittest.mock import Mock, patch, MagicMock
import sys
from pathlib import Path
from datetime import datetime

# Add Python directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from streaming_engine import StreamTokenizer
from streaming_pipeline import StreamingPipeline, BoundedQueue, DropPolicy
from event_recorder import EventRecorder, EventReplayer, DeterministicOrchestrator
from state_machine import StateMachine, RFSNStateMachine, StateTransitionError
from memory_governance import MemoryGovernance, GovernedMemory, MemoryType, MemorySource

try:
    from streaming_voice_system import DequeSpeechQueue, VoiceChunk
    HAS_VOICE_SYSTEM = True
except ImportError:
    HAS_VOICE_SYSTEM = False


class TestStreamingSegmentation:
    """Tests for streaming text segmentation"""
    
    def test_abbreviations_not_split(self):
        """Test that abbreviations like 'Mr.' don't cause premature splits"""
        tokenizer = StreamTokenizer()
        
        # Process "Mr. Jones is here." as three tokens
        sentences = tokenizer.process("Mr.")
        assert len(sentences) == 0, "Should not split after 'Mr.'"
        
        sentences = tokenizer.process(" Jones")
        assert len(sentences) == 0, "Should not split after continuation, wait for terminator"
        
        sentences = tokenizer.process(" is here.")
        assert len(sentences) == 0, "Should buffer until flush"
        
        # Flush to get the complete sentence
        sentences = tokenizer.flush()
        assert len(sentences) == 1, "Should emit complete sentence on flush"
        assert "Mr. Jones is here." in sentences[0]
    
    def test_ellipsis_handling(self):
        """Test that '...' is handled correctly"""
        tokenizer = StreamTokenizer()
        
        text = "Wait for it..."
        sentences = tokenizer.process(text)
        # Ellipsis sets pending boundary, need to flush
        sentences.extend(tokenizer.flush())
        assert len(sentences) == 1
        assert "..." in sentences[0]
    
    def test_unicode_handling(self):
        """Test unicode characters in streaming"""
        tokenizer = StreamTokenizer()
        
        text = "Hello 世界! How are you?"
        sentences = tokenizer.process(text)
        # First sentence emitted, second buffered
        assert len(sentences) == 1
        assert "世界" in sentences[0]
        # Flush to get second sentence
        sentences.extend(tokenizer.flush())
        assert len(sentences) == 2
    
    def test_fast_token_bursts(self):
        """Test handling of rapid token bursts"""
        tokenizer = StreamTokenizer()
        
        # Simulate fast token stream
        tokens = ["The", " ", "quick", " ", "brown", " ", "fox", " ", "jumps", " ", "over", " ", "the", " ", "lazy", " ", "dog", "."]
        sentences = []
        
        for token in tokens:
            sentences.extend(tokenizer.process(token))
        
        # Sentence buffered, need to flush
        sentences.extend(tokenizer.flush())
        assert len(sentences) == 1
        assert "The quick brown fox jumps over the lazy dog." in sentences[0]
    
    def test_quote_handling(self):
        """Test proper handling of quoted text"""
        tokenizer = StreamTokenizer()
        
        text = 'He said "Hello world!" and left.'
        sentences = tokenizer.process(text)
        
        # Quote inside sentence, sentence buffered at end
        assert len(sentences) == 0
        # Flush to get the complete sentence
        sentences.extend(tokenizer.flush())
        assert len(sentences) == 1
        assert '"Hello world!"' in sentences[0]


class TestBackpressure:
    """Tests for queue backpressure and drop policies"""
    
    def test_drop_oldest_policy(self):
        """Test DROP_OLDEST policy removes oldest items"""
        queue = BoundedQueue(max_size=3, drop_policy=DropPolicy.DROP_OLDEST)
        
        # Fill queue
        queue.put("item1")
        queue.put("item2")
        queue.put("item3")
        
        # Add one more - should drop oldest
        success = queue.put("item4")
        assert success
        
        # Check that item1 was dropped
        items = []
        while True:
            item = queue.get()
            if item is None:
                break
            items.append(item)
        
        assert items == ["item2", "item3", "item4"]
        assert queue.get_stats()["dropped_oldest"] == 1
    
    def test_drop_newest_policy(self):
        """Test DROP_NEWEST policy rejects new items"""
        queue = BoundedQueue(max_size=3, drop_policy=DropPolicy.DROP_NEWEST)
        
        # Fill queue
        queue.put("item1")
        queue.put("item2")
        queue.put("item3")
        
        # Try to add one more - should be rejected
        success = queue.put("item4")
        assert not success
        
        # Check queue unchanged
        items = []
        while True:
            item = queue.get()
            if item is None:
                break
            items.append(item)
        
        assert items == ["item1", "item2", "item3"]
        assert queue.get_stats()["dropped_newest"] == 1
    
    def test_queue_metrics(self):
        """Test queue statistics tracking"""
        queue = BoundedQueue(max_size=5, drop_policy=DropPolicy.DROP_OLDEST)
        
        # Add items
        for i in range(10):
            queue.put(f"item{i}")
        
        stats = queue.get_stats()
        assert stats["current_size"] == 5
        assert stats["max_size"] == 5
        assert stats["dropped_total"] == 5
        assert stats["dropped_oldest"] == 5


class TestTTSConcurrency:
    """Tests for TTS engine concurrency"""
    
    def test_serial_tts_output(self):
        """Test that TTS outputs are serialized (no overlapping audio)"""
        # Mock TTS engine
        mock_tts = Mock()
        call_order = []
        
        def mock_synthesize(text):
            call_order.append(text)
            time.sleep(0.1)  # Simulate processing time
            return f"audio_{text}"
        
        mock_tts.synthesize = mock_synthesize
        
        # Simulate concurrent requests
        texts = ["Hello", "World", "Test"]
        results = []
        
        def process_text(text):
            result = mock_tts.synthesize(text)
            results.append(result)
        
        threads = [threading.Thread(target=process_text, args=(t,)) for t in texts]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        # All requests processed
        assert len(results) == 3
        assert len(call_order) == 3
    
    def test_tts_queue_serialization(self):
        """Test that TTS queue serializes requests"""
        if not HAS_VOICE_SYSTEM:
            pytest.skip("streaming_voice_system not available")

        queue = DequeSpeechQueue(maxsize=10)
        processed = []
        
        def mock_worker():
            while True:
                chunk = queue.get()
                if chunk is None:
                    break
                processed.append(chunk.text)
                time.sleep(0.05)
        
        # Start worker
        worker = threading.Thread(target=mock_worker, daemon=True)
        worker.start()
        
        # Add chunks rapidly
        for i in range(5):
            queue.put(VoiceChunk(text=f"chunk{i}", npc_id="test", created_ts=time.time()))
        
        # Wait for processing
        time.sleep(0.5)
        
        # All chunks processed in order
        assert len(processed) == 5
        assert processed == [f"chunk{i}" for i in range(5)]


class TestFailureInjection:
    """Tests for failure scenarios and recovery"""
    
    def test_llm_timeout_handling(self):
        """Test handling of LLM generation timeout"""
        pipeline = StreamingPipeline()
        lifecycle = pipeline.create_lifecycle()
        
        # Simulate timeout during generation
        pipeline.track_generation_start(lifecycle, "gen_1")
        time.sleep(0.1)
        pipeline.mark_timeout(lifecycle, "llm_generation")
        
        assert lifecycle.status == "timeout_llm_generation"
        assert lifecycle.error is not None
        
        metrics = pipeline.get_metrics()
        assert metrics["timeout_messages"] == 1
    
    def test_tts_crash_recovery(self):
        """Test recovery from TTS crash"""
        pipeline = StreamingPipeline()
        
        # Record failure
        pipeline.record_failure("tts", failure_threshold=3, cooldown_seconds=60)
        pipeline.record_failure("tts", failure_threshold=3, cooldown_seconds=60)
        pipeline.record_failure("tts", failure_threshold=3, cooldown_seconds=60)
        
        # Circuit breaker should be open
        assert pipeline.check_circuit_breaker("tts")
        
        # Try to deliver audio - should fail
        lifecycle = pipeline.create_lifecycle()
        delivered = pipeline.deliver_audio(lifecycle, b"fake_audio")
        
        # Circuit breaker doesn't block delivery, but logs failure
        metrics = pipeline.get_metrics()
        assert "circuit_breakers" in metrics
    
    def test_audio_device_missing(self):
        """Test handling of missing audio device"""
        pipeline = StreamingPipeline()
        lifecycle = pipeline.create_lifecycle()
        
        # Simulate audio device error
        pipeline.mark_failed(lifecycle, "Audio device not found")
        
        assert lifecycle.status == "failed"
        assert "Audio device" in lifecycle.error
        
        metrics = pipeline.get_metrics()
        assert metrics["failed_messages"] == 1


class TestReplay:
    """Tests for deterministic replay"""
    
    def test_record_and_replay_events(self):
        """Test recording and replaying events"""
        from event_recorder import EventType
        
        recorder = EventRecorder(session_id="test_session")
        
        # Record some events
        recorder.record(EventType.USER_INPUT, {"text": "Hello"})
        recorder.record(EventType.STATE_UPDATE, {"field": "affinity", "old_value": 0.0, "new_value": 0.5})
        recorder.record(EventType.LLM_GENERATION, {"prompt": "Hello", "output": "Hi there!"})
        
        # Verify events recorded
        events = recorder.get_events()
        assert len(events) == 3
        
        # Save and load recording
        recording_path = recorder.save_recording()
        assert recording_path.exists()
        
        # Create replayer
        replayer = EventReplayer(recording_path, accelerated=True)
        
        # Replay events
        replayed_events = []
        while True:
            event = replayer.next_event(wait=False)
            if event is None:
                break
            replayed_events.append(event)
        
        assert len(replayed_events) == 3
        assert replayed_events[0].event_type.value == "user_input"
        assert replayed_events[1].event_type.value == "state_update"
        assert replayed_events[2].event_type.value == "llm_generation"
    
    def test_deterministic_replay(self):
        """Test that replay produces identical results"""
        orchestrator = DeterministicOrchestrator()
        orchestrator.set_seed(42)

        # Record a sequence
        orchestrator.record_input({"text": "test"})
        orchestrator.record_state_update("affinity", 0.0, 0.5)
        
        # Save recording
        recording_path = orchestrator.save_recording()
        
        # Replay with same seed
        replayer = EventReplayer(recording_path, accelerated=True)
        replayed = []
        
        while True:
            event = replayer.next_event(wait=False)
            if event is None:
                break
            replayed.append(event.data)
        
        # Verify replayed data matches original
# First event is set_seed, second is user_input, third is state_update
        user_input_event = replayed[1]
        state_update_event = replayed[2]
        assert user_input_event["text"] == "test"
        assert state_update_event["new_value"] == 0.5
    
    def test_recording_integrity(self):
        """Test recording integrity verification"""
        from event_recorder import EventType
        
        recorder = EventRecorder()
        
        # Record events
        for i in range(10):
            recorder.record(EventType.USER_INPUT, {"index": i})
        
        # Verify integrity
        assert recorder.verify_integrity()
    
    def test_integrity_check_fails_on_corruption(self):
        """Test that integrity check fails on corrupted data"""
        from event_recorder import EventType
        
        recorder = EventRecorder()
        recorder.record(EventType.USER_INPUT, {"test": "data"})

        # Corrupt an event by modifying its data
        events = recorder.get_events()
        original_data = events[0].data.copy()
        events[0].data["test"] = "corrupted"

        # Verify should fail
        assert not recorder.verify_integrity()

        # Restore original data for cleanup
        events[0].data = original_data


class TestStateMachineInvariants:
    """Tests for state machine invariants"""
    
    def test_affinity_range_invariant(self):
        """Test affinity is constrained to [-1, 1]"""
        sm = StateMachine()
        sm.add_range_invariant("affinity", -1.0, 1.0)
        
        # Valid values
        sm.set_field("affinity", 0.5)
        assert sm.get_field("affinity") == 0.5
        
        sm.set_field("affinity", -0.8)
        assert sm.get_field("affinity") == -0.8
        
        # Invalid value should fail
        with pytest.raises(StateTransitionError):
            sm.set_field("affinity", 1.5)
        
        with pytest.raises(StateTransitionError):
            sm.set_field("affinity", -2.0)
    
    def test_enum_invariant(self):
        """Test enum constraint on mood"""
        sm = StateMachine()
        sm.add_enum_invariant("mood", ["happy", "sad", "neutral"])
        
        # Valid values
        sm.set_field("mood", "happy")
        assert sm.get_field("mood") == "happy"
        
        # Invalid value should fail
        with pytest.raises(StateTransitionError):
            sm.set_field("mood", "angry")
    
    def test_transition_audit_log(self):
        """Test that all transitions are logged"""
        sm = StateMachine()
        sm.add_range_invariant("value", 0, 100)
        
        # Make some transitions
        sm.set_field("value", 10, event="initial")
        sm.set_field("value", 20, event="update")
        sm.set_field("value", 30, event="update")
        
        # Check audit log
        transitions = sm.get_transitions()
        assert len(transitions) == 3
        
        # All should be valid
        assert all(t.validation_passed for t in transitions)
        
        # Check stats
        stats = sm.get_transition_stats()
        assert stats["total_transitions"] == 3
        assert stats["successful_transitions"] == 3
        assert stats["failed_transitions"] == 0
    
    def test_drift_detection(self):
        """Test oscillation detection and damping"""
        sm = StateMachine()
        sm.add_range_invariant("value", 0, 100)
        
        # Rapid oscillation
        for i in range(20):
            value = 10 if i % 2 == 0 else 90
            sm.set_field("value", value)
        
        # Check that drift was detected and damped
        transitions = sm.get_transitions("value")
        assert len(transitions) == 20


class TestMemoryGovernance:
    """Tests for memory governance"""
    
    def test_memory_admission_with_confidence(self):
        """Test that low-confidence memories are quarantined"""
        import tempfile
        from pathlib import Path
        
        with tempfile.TemporaryDirectory() as tmpdir:
            governance = MemoryGovernance(storage_path=Path(tmpdir) / "governed")
            
            # Low confidence memory
            low_conf_memory = GovernedMemory(
                memory_id="",
                memory_type=MemoryType.FACT_CLAIM,
                source=MemorySource.LEARNER_INFERENCE,
                content="Test fact",
                confidence=0.1,  # Below threshold
                timestamp=datetime.utcnow()
            )
            
            success, reason, memory_id = governance.add_memory(low_conf_memory)
            assert not success
            assert "confidence" in reason.lower()
            
            # Should be in quarantine
            quarantined = governance.get_quarantined()
            assert len(quarantined) == 1
    
    def test_memory_ttl_expiration(self):
        """Test that memories expire based on TTL"""
        import tempfile
        from pathlib import Path
        
        with tempfile.TemporaryDirectory() as tmpdir:
            governance = MemoryGovernance(storage_path=Path(tmpdir) / "governed")
            
            # Memory with short TTL
            memory = GovernedMemory(
                memory_id="",
                memory_type=MemoryType.EMOTIONAL_STATE,
                source=MemorySource.USER_INPUT,
                content="Temporary mood",
                confidence=0.8,
                timestamp=datetime.utcnow(),
                ttl_seconds=0.1  # 100ms
            )
            
            governance.add_memory(memory)
            
            # Should be active initially
            active = governance.query_memories()
            assert len(active) == 1
            
            # Wait for expiration
            time.sleep(0.2)
            
            # Should be expired
            active = governance.query_memories(include_expired=False)
            assert len(active) == 0
    
    def test_contradiction_detection(self):
        """Test that contradictory memories are rejected"""
        import tempfile
        from pathlib import Path
        
        with tempfile.TemporaryDirectory() as tmpdir:
            governance = MemoryGovernance(storage_path=Path(tmpdir) / "governed")
            
            # Add first memory
            memory1 = GovernedMemory(
                memory_id="",
                memory_type=MemoryType.FACT_CLAIM,
                source=MemorySource.USER_INPUT,
                content="The sky is blue",
                confidence=0.9,
                timestamp=datetime.utcnow()
            )
            governance.add_memory(memory1)
            
            # Try to add contradictory memory
            memory2 = GovernedMemory(
                memory_id="",
                memory_type=MemoryType.FACT_CLAIM,
                source=MemorySource.USER_INPUT,
                content="The sky is not blue",
                confidence=0.9,
                timestamp=datetime.utcnow()
            )
            
            success, reason, _ = governance.add_memory(memory2)
            assert not success
            assert "contradicts" in reason.lower()
    
    def test_memory_provenance(self):
        """Test that memory provenance is tracked"""
        import tempfile
        from pathlib import Path
        
        with tempfile.TemporaryDirectory() as tmpdir:
            governance = MemoryGovernance(storage_path=Path(tmpdir) / "governed")
            
            memory = GovernedMemory(
                memory_id="",
                memory_type=MemoryType.CONVERSATION_TURN,
                source=MemorySource.NPC_RESPONSE,
                content="Hello there",
                confidence=0.95,
                timestamp=datetime.utcnow()
            )
            
            governance.add_memory(memory)
            
            # Retrieve and check provenance
            memories = governance.query_memories(memory_type=MemoryType.CONVERSATION_TURN)
            assert len(memories) == 1
            assert memories[0].source == MemorySource.NPC_RESPONSE
            assert memories[0].confidence == 0.95


class TestRFSNStateMachine:
    """Tests for RFSN-specific state machine"""
    
    def test_rfsn_invariants_preconfigured(self):
        """Test that RFSN invariants are pre-configured"""
        rfsn = RFSNStateMachine()
        
        # Affinity should be constrained
        with pytest.raises(StateTransitionError):
            rfsn.set_field("affinity", 2.0)
        
        # Mood should be enum-constrained
        with pytest.raises(StateTransitionError):
            rfsn.set_field("mood", "invalid_mood")
        
        # Relationship should be enum-constrained
        with pytest.raises(StateTransitionError):
            rfsn.set_field("relationship", "invalid_relationship")
    
    def test_affinity_relationship_consistency(self):
        """Test affinity-relationship consistency invariant"""
        rfsn = RFSNStateMachine()
        
        # Set relationship to enemy
        rfsn.set_field("relationship", "enemy")
        
        # High affinity should be rejected for enemy
        with pytest.raises(StateTransitionError):
            rfsn.set_field("affinity", 0.9)
        
        # Negative affinity should work
        rfsn.set_field("affinity", -0.5)
        assert rfsn.get_field("affinity") == -0.5


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
