#!/usr/bin/env python3
"""
RFSN Memory Leak Tests v8.2
Long-running stability and resource cleanup verification.
"""

import gc
import os
import sys
import time
import threading
import tracemalloc
from dataclasses import dataclass
from typing import List, Dict, Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest


@dataclass
class MemorySnapshot:
    """Memory usage snapshot"""
    timestamp: float
    current_mb: float
    peak_mb: float
    allocated_blocks: int
    
    @staticmethod
    def capture() -> "MemorySnapshot":
        current, peak = tracemalloc.get_traced_memory()
        stats = tracemalloc.get_tracemalloc_memory()
        return MemorySnapshot(
            timestamp=time.time(),
            current_mb=current / 1024 / 1024,
            peak_mb=peak / 1024 / 1024,
            allocated_blocks=stats
        )


class MemoryLeakTester:
    """Tests for memory leaks in various components"""
    
    def __init__(self):
        tracemalloc.start()
        self.snapshots: List[MemorySnapshot] = []
    
    def snapshot(self):
        """Take a memory snapshot"""
        gc.collect()
        self.snapshots.append(MemorySnapshot.capture())
    
    def get_growth_mb(self) -> float:
        """Get memory growth from first to last snapshot"""
        if len(self.snapshots) < 2:
            return 0
        return self.snapshots[-1].current_mb - self.snapshots[0].current_mb
    
    def test_streaming_engine_memory(self, iterations: int = 100) -> Dict[str, Any]:
        """Test streaming engine doesn't leak memory"""
        from streaming_engine import StreamingMantellaEngine
        
        self.snapshots.clear()
        self.snapshot()
        
        for i in range(iterations):
            engine = StreamingMantellaEngine(model_path=None)
            
            # Generate some content
            chunks = list(engine.generate_streaming(f"Test message {i}"))
            
            # Cleanup
            engine.shutdown()
            del engine
            
            if i % 20 == 0:
                gc.collect()
                self.snapshot()
        
        gc.collect()
        self.snapshot()
        
        growth = self.get_growth_mb()
        
        return {
            "component": "StreamingEngine",
            "iterations": iterations,
            "initial_mb": self.snapshots[0].current_mb,
            "final_mb": self.snapshots[-1].current_mb,
            "growth_mb": growth,
            "peak_mb": max(s.peak_mb for s in self.snapshots),
            "leak_detected": growth > 50  # Alert if >50MB growth
        }
    
    def test_memory_manager_memory(self, iterations: int = 100) -> Dict[str, Any]:
        """Test memory manager doesn't leak memory"""
        from memory_manager import ConversationManager
        import tempfile
        
        self.snapshots.clear()
        self.snapshot()
        
        with tempfile.TemporaryDirectory() as tmp_dir:
            for i in range(iterations):
                manager = ConversationManager(f"NPC_{i}", tmp_dir)
                
                # Add and retrieve turns
                for j in range(10):
                    manager.add_turn(f"Q{j}", f"A{j}")
                
                context = manager.get_context_window()
                
                # Clear
                manager.clear()
                del manager
                
                if i % 20 == 0:
                    gc.collect()
                    self.snapshot()
        
        gc.collect()
        self.snapshot()
        
        growth = self.get_growth_mb()
        
        return {
            "component": "MemoryManager",
            "iterations": iterations,
            "initial_mb": self.snapshots[0].current_mb,
            "final_mb": self.snapshots[-1].current_mb,
            "growth_mb": growth,
            "peak_mb": max(s.peak_mb for s in self.snapshots),
            "leak_detected": growth > 20  # Alert if >20MB growth
        }
    
    def test_voice_system_memory(self, iterations: int = 100) -> Dict[str, Any]:
        """Test voice system doesn't leak memory"""
        from streaming_engine import StreamingVoiceSystem
        
        self.snapshots.clear()
        self.snapshot()
        
        for i in range(iterations):
            voice = StreamingVoiceSystem(max_queue_size=5)
            
            # Queue some messages
            for j in range(20):
                voice.speak(f"Test message {j}")
            
            # Flush and cleanup
            voice.reset()
            voice.shutdown()
            del voice
            
            if i % 20 == 0:
                gc.collect()
                self.snapshot()
        
        gc.collect()
        self.snapshot()
        
        growth = self.get_growth_mb()
        
        return {
            "component": "VoiceSystem",
            "iterations": iterations,
            "initial_mb": self.snapshots[0].current_mb,
            "final_mb": self.snapshots[-1].current_mb,
            "growth_mb": growth,
            "peak_mb": max(s.peak_mb for s in self.snapshots),
            "leak_detected": growth > 30  # Alert if >30MB growth
        }
    
    def test_thread_cleanup(self, iterations: int = 20) -> Dict[str, Any]:
        """Test that threads are properly cleaned up"""
        from streaming_engine import StreamingMantellaEngine
        
        initial_threads = threading.active_count()
        
        for i in range(iterations):
            engine = StreamingMantellaEngine(model_path=None)
            list(engine.generate_streaming("Test"))
            engine.shutdown()
            del engine
            
            gc.collect()
            time.sleep(0.1)  # Give threads time to clean up
        
        gc.collect()
        time.sleep(0.5)
        
        final_threads = threading.active_count()
        thread_growth = final_threads - initial_threads
        
        return {
            "component": "ThreadCleanup",
            "iterations": iterations,
            "initial_threads": initial_threads,
            "final_threads": final_threads,
            "thread_growth": thread_growth,
            "leak_detected": thread_growth > 2  # Allow small margin
        }
    
    def run_full_suite(self) -> List[Dict[str, Any]]:
        """Run all memory leak tests"""
        results = []
        
        # Run each test
        results.append(self.test_streaming_engine_memory())
        results.append(self.test_memory_manager_memory())
        results.append(self.test_voice_system_memory())
        results.append(self.test_thread_cleanup())
        
        return results
    
    def cleanup(self):
        """Cleanup tracemalloc"""
        tracemalloc.stop()


class TestMemoryLeaks:
    """Pytest wrapper for memory leak tests"""
    
    @pytest.fixture
    def tester(self):
        t = MemoryLeakTester()
        yield t
        t.cleanup()
    
    def test_streaming_engine_no_leak(self, tester):
        """Streaming engine should not leak memory"""
        result = tester.test_streaming_engine_memory(iterations=30)
        
        print(f"\n{result['component']}: {result['growth_mb']:.2f} MB growth")
        
        # Allow some growth but not excessive
        assert not result["leak_detected"], f"Memory leak detected: {result['growth_mb']:.2f} MB"
    
    def test_memory_manager_no_leak(self, tester):
        """Memory manager should not leak memory"""
        result = tester.test_memory_manager_memory(iterations=30)
        
        print(f"\n{result['component']}: {result['growth_mb']:.2f} MB growth")
        
        assert not result["leak_detected"], f"Memory leak detected: {result['growth_mb']:.2f} MB"
    
    def test_voice_system_no_leak(self, tester):
        """Voice system should not leak memory"""
        result = tester.test_voice_system_memory(iterations=30)
        
        print(f"\n{result['component']}: {result['growth_mb']:.2f} MB growth")
        
        assert not result["leak_detected"], f"Memory leak detected: {result['growth_mb']:.2f} MB"
    
    def test_threads_cleanup(self, tester):
        """Threads should be properly cleaned up"""
        result = tester.test_thread_cleanup(iterations=10)
        
        print(f"\nThreads: {result['initial_threads']} -> {result['final_threads']}")
        
        assert not result["leak_detected"], f"Thread leak detected: +{result['thread_growth']} threads"


if __name__ == "__main__":
    print("=" * 60)
    print("RFSN Memory Leak Tests")
    print("=" * 60)
    
    tester = MemoryLeakTester()
    
    try:
        results = tester.run_full_suite()
        
        print("\nResults:")
        print("-" * 40)
        
        any_leaks = False
        for result in results:
            status = "⚠️ LEAK" if result.get("leak_detected") else "✅ OK"
            print(f"{status} {result['component']}")
            
            if "growth_mb" in result:
                print(f"   Memory: {result['initial_mb']:.1f} -> {result['final_mb']:.1f} MB")
                print(f"   Growth: {result['growth_mb']:.2f} MB")
            
            if "thread_growth" in result:
                print(f"   Threads: {result['initial_threads']} -> {result['final_threads']}")
            
            if result.get("leak_detected"):
                any_leaks = True
            
            print()
        
        if any_leaks:
            print("⚠️  Memory leaks detected!")
        else:
            print("✅ No memory leaks detected")
            
    finally:
        tester.cleanup()
