#!/usr/bin/env python3
"""
RFSN Load Tests v8.2
Stress testing for concurrent request handling.
"""

import asyncio
import json
import sys
import os
import time
import threading
import statistics
from dataclasses import dataclass, field
from typing import List, Dict, Any
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest


@dataclass
class LoadTestResult:
    """Result of a load test run"""
    total_requests: int
    successful: int
    failed: int
    duration_seconds: float
    latencies_ms: List[float] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    
    @property
    def success_rate(self) -> float:
        return self.successful / max(self.total_requests, 1)
    
    @property
    def requests_per_second(self) -> float:
        return self.total_requests / max(self.duration_seconds, 0.001)
    
    @property
    def avg_latency_ms(self) -> float:
        return statistics.mean(self.latencies_ms) if self.latencies_ms else 0
    
    @property
    def p50_latency_ms(self) -> float:
        if not self.latencies_ms:
            return 0
        sorted_lat = sorted(self.latencies_ms)
        return sorted_lat[len(sorted_lat) // 2]
    
    @property
    def p95_latency_ms(self) -> float:
        if not self.latencies_ms:
            return 0
        sorted_lat = sorted(self.latencies_ms)
        return sorted_lat[int(len(sorted_lat) * 0.95)]
    
    @property
    def p99_latency_ms(self) -> float:
        if not self.latencies_ms:
            return 0
        sorted_lat = sorted(self.latencies_ms)
        return sorted_lat[int(len(sorted_lat) * 0.99)]
    
    def summary(self) -> str:
        return (
            f"Requests: {self.successful}/{self.total_requests} "
            f"({self.success_rate:.1%} success)\n"
            f"Duration: {self.duration_seconds:.2f}s "
            f"({self.requests_per_second:.1f} req/s)\n"
            f"Latency: avg={self.avg_latency_ms:.0f}ms, "
            f"p50={self.p50_latency_ms:.0f}ms, "
            f"p95={self.p95_latency_ms:.0f}ms, "
            f"p99={self.p99_latency_ms:.0f}ms"
        )


class ComponentLoadTester:
    """Load tester for individual components (no server required)"""
    
    def run_streaming_engine_load(
        self,
        num_requests: int = 100,
        concurrency: int = 10
    ) -> LoadTestResult:
        """Load test the streaming engine"""
        from streaming_engine import StreamingMantellaEngine
        
        latencies = []
        errors = []
        successful = 0
        
        def single_request(_):
            nonlocal successful
            engine = StreamingMantellaEngine(model_path=None)
            
            try:
                start = time.time()
                chunks = list(engine.generate_streaming("Hello, how are you?"))
                elapsed = (time.time() - start) * 1000
                
                if chunks:
                    latencies.append(elapsed)
                    successful += 1
                
            except Exception as e:
                errors.append(str(e))
            finally:
                engine.shutdown()
        
        start_time = time.time()
        
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = [executor.submit(single_request, i) for i in range(num_requests)]
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    errors.append(str(e))
        
        duration = time.time() - start_time
        
        return LoadTestResult(
            total_requests=num_requests,
            successful=successful,
            failed=len(errors),
            duration_seconds=duration,
            latencies_ms=latencies,
            errors=errors[:10]  # Keep first 10 errors
        )
    
    def run_memory_manager_load(
        self,
        num_operations: int = 1000,
        concurrency: int = 20
    ) -> LoadTestResult:
        """Load test the memory manager"""
        from memory_manager import ConversationManager
        import tempfile
        
        with tempfile.TemporaryDirectory() as tmp_dir:
            latencies = []
            errors = []
            successful = 0
            lock = threading.Lock()
            
            def single_operation(i):
                nonlocal successful
                
                npc_name = f"NPC_{i % 10}"
                manager = ConversationManager(npc_name, tmp_dir)
                
                try:
                    start = time.time()
                    
                    # Write operation
                    manager.add_turn(f"Question {i}", f"Answer {i}")
                    
                    # Read operation
                    manager.get_context_window(limit=5)
                    
                    elapsed = (time.time() - start) * 1000
                    
                    with lock:
                        latencies.append(elapsed)
                        successful += 1
                    
                except Exception as e:
                    with lock:
                        errors.append(str(e))
            
            start_time = time.time()
            
            with ThreadPoolExecutor(max_workers=concurrency) as executor:
                futures = [executor.submit(single_operation, i) for i in range(num_operations)]
                for future in as_completed(futures):
                    try:
                        future.result()
                    except Exception as e:
                        with lock:
                            errors.append(str(e))
            
            duration = time.time() - start_time
            
            return LoadTestResult(
                total_requests=num_operations,
                successful=successful,
                failed=len(errors),
                duration_seconds=duration,
                latencies_ms=latencies,
                errors=errors[:10]
            )
    
    def run_voice_system_load(
        self,
        num_calls: int = 100,
        concurrency: int = 5
    ) -> LoadTestResult:
        """Load test the voice system queueing"""
        from streaming_engine import StreamingVoiceSystem
        
        voice = StreamingVoiceSystem(max_queue_size=10)
        latencies = []
        errors = []
        successful = 0
        lock = threading.Lock()
        
        def single_call(i):
            nonlocal successful
            
            try:
                start = time.time()
                voice.speak(f"This is test message number {i}")
                elapsed = (time.time() - start) * 1000
                
                with lock:
                    latencies.append(elapsed)
                    successful += 1
                
            except Exception as e:
                with lock:
                    errors.append(str(e))
        
        start_time = time.time()
        
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = [executor.submit(single_call, i) for i in range(num_calls)]
            for future in as_completed(futures):
                pass  # Collect results
        
        duration = time.time() - start_time
        
        voice.shutdown()
        
        return LoadTestResult(
            total_requests=num_calls,
            successful=successful,
            failed=len(errors),
            duration_seconds=duration,
            latencies_ms=latencies,
            errors=errors[:10]
        )


class TestLoadTests:
    """Pytest wrapper for load tests"""
    
    @pytest.fixture
    def tester(self):
        return ComponentLoadTester()
    
    def test_streaming_engine_load(self, tester):
        """Streaming engine handles concurrent requests"""
        result = tester.run_streaming_engine_load(num_requests=20, concurrency=4)
        
        print(f"\n{result.summary()}")
        
        assert result.success_rate >= 0.9  # 90% success rate
        assert result.p95_latency_ms < 5000  # Under 5s p95
    
    def test_memory_manager_load(self, tester):
        """Memory manager handles concurrent operations"""
        result = tester.run_memory_manager_load(num_operations=100, concurrency=10)
        
        print(f"\n{result.summary()}")
        
        assert result.success_rate >= 0.95  # 95% success rate
        assert result.avg_latency_ms < 100  # Under 100ms average
    
    def test_voice_system_load(self, tester):
        """Voice system handles concurrent speak calls"""
        result = tester.run_voice_system_load(num_calls=50, concurrency=5)
        
        print(f"\n{result.summary()}")
        
        assert result.success_rate >= 0.9
        assert result.avg_latency_ms < 50  # Queuing should be fast


if __name__ == "__main__":
    print("=" * 60)
    print("RFSN Load Tests")
    print("=" * 60)
    
    tester = ComponentLoadTester()
    
    print("\n1. Streaming Engine Load Test")
    print("-" * 40)
    result = tester.run_streaming_engine_load(num_requests=50, concurrency=5)
    print(result.summary())
    
    print("\n2. Memory Manager Load Test")
    print("-" * 40)
    result = tester.run_memory_manager_load(num_operations=200, concurrency=20)
    print(result.summary())
    
    print("\n3. Voice System Load Test")
    print("-" * 40)
    result = tester.run_voice_system_load(num_calls=100, concurrency=10)
    print(result.summary())
    
    print("\n" + "=" * 60)
    print("Load tests complete!")
