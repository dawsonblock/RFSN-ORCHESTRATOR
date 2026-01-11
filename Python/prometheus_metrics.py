#!/usr/bin/env python3
"""
RFSN Prometheus Metrics v8.2
Exposes /metrics endpoint for observability.
"""

import time
import threading
from collections import defaultdict
from typing import Dict, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime

from fastapi import APIRouter, Response


# =============================================================================
# METRIC TYPES
# =============================================================================

@dataclass
class Counter:
    """Monotonically increasing counter"""
    name: str
    help: str
    value: float = 0.0
    labels: Dict[str, str] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    
    def inc(self, value: float = 1.0):
        with self._lock:
            self.value += value
    
    def to_prometheus(self) -> str:
        label_str = self._format_labels()
        return f"{self.name}{label_str} {self.value}"
    
    def _format_labels(self) -> str:
        if not self.labels:
            return ""
        pairs = [f'{k}="{v}"' for k, v in self.labels.items()]
        return "{" + ",".join(pairs) + "}"


@dataclass
class Gauge:
    """Value that can go up or down"""
    name: str
    help: str
    value: float = 0.0
    labels: Dict[str, str] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    
    def set(self, value: float):
        with self._lock:
            self.value = value
    
    def inc(self, value: float = 1.0):
        with self._lock:
            self.value += value
    
    def dec(self, value: float = 1.0):
        with self._lock:
            self.value -= value
    
    def to_prometheus(self) -> str:
        label_str = self._format_labels()
        return f"{self.name}{label_str} {self.value}"
    
    def _format_labels(self) -> str:
        if not self.labels:
            return ""
        pairs = [f'{k}="{v}"' for k, v in self.labels.items()]
        return "{" + ",".join(pairs) + "}"


@dataclass
class Histogram:
    """Distribution of values with buckets"""
    name: str
    help: str
    buckets: tuple = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10)
    _values: list = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    labels: Dict[str, str] = field(default_factory=dict)
    
    def observe(self, value: float):
        with self._lock:
            self._values.append(value)
            # Keep only last 10000 to prevent memory issues
            if len(self._values) > 10000:
                self._values = self._values[-10000:]
    
    def to_prometheus(self) -> str:
        with self._lock:
            values = self._values.copy()
        
        if not values:
            return ""
        
        lines = []
        label_str = self._format_labels()
        
        # Bucket counts
        for bucket in self.buckets:
            count = sum(1 for v in values if v <= bucket)
            lines.append(f'{self.name}_bucket{{le="{bucket}"{label_str}}} {count}')
        
        # +Inf bucket
        lines.append(f'{self.name}_bucket{{le="+Inf"{label_str}}} {len(values)}')
        
        # Sum and count
        lines.append(f'{self.name}_sum{label_str} {sum(values)}')
        lines.append(f'{self.name}_count{label_str} {len(values)}')
        
        return "\n".join(lines)
    
    def _format_labels(self) -> str:
        if not self.labels:
            return ""
        pairs = [f',{k}="{v}"' for k, v in self.labels.items()]
        return "".join(pairs)


@dataclass  
class Summary:
    """Quantile observations"""
    name: str
    help: str
    quantiles: tuple = (0.5, 0.9, 0.95, 0.99)
    _values: list = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    labels: Dict[str, str] = field(default_factory=dict)
    
    def observe(self, value: float):
        with self._lock:
            self._values.append(value)
            if len(self._values) > 10000:
                self._values = self._values[-10000:]
    
    def to_prometheus(self) -> str:
        with self._lock:
            values = sorted(self._values.copy())
        
        if not values:
            return ""
        
        lines = []
        label_str = self._format_labels()
        
        # Quantiles
        n = len(values)
        for q in self.quantiles:
            idx = int(q * n)
            lines.append(f'{self.name}{{quantile="{q}"{label_str}}} {values[min(idx, n-1)]}')
        
        # Sum and count
        lines.append(f'{self.name}_sum{label_str} {sum(values)}')
        lines.append(f'{self.name}_count{label_str} {n}')
        
        return "\n".join(lines)
    
    def _format_labels(self) -> str:
        if not self.labels:
            return ""
        pairs = [f',{k}="{v}"' for k, v in self.labels.items()]
        return "".join(pairs)


# =============================================================================
# METRICS REGISTRY
# =============================================================================

class MetricsRegistry:
    """
    Central registry for all metrics.
    """
    
    def __init__(self):
        self._metrics: Dict[str, Any] = {}
        self._lock = threading.Lock()
        
        # Register default metrics
        self._register_default_metrics()
    
    def _register_default_metrics(self):
        """Register standard RFSN metrics"""
        
        # Request metrics
        self.register(Counter(
            "rfsn_requests_total",
            "Total number of requests"
        ))
        
        self.register(Histogram(
            "rfsn_request_duration_seconds",
            "Request duration in seconds",
            buckets=(0.1, 0.25, 0.5, 1, 2.5, 5, 10)
        ))
        
        # LLM metrics
        self.register(Histogram(
            "rfsn_llm_first_token_seconds",
            "Time to first token in seconds",
            buckets=(0.1, 0.25, 0.5, 1, 1.5, 2, 3, 5)
        ))
        
        self.register(Histogram(
            "rfsn_llm_total_generation_seconds",
            "Total generation time in seconds",
            buckets=(0.5, 1, 2, 3, 5, 10, 20)
        ))
        
        self.register(Counter(
            "rfsn_llm_tokens_generated_total",
            "Total tokens generated"
        ))
        
        # TTS metrics
        self.register(Histogram(
            "rfsn_tts_synthesis_seconds",
            "TTS synthesis time in seconds",
            buckets=(0.05, 0.1, 0.2, 0.5, 1)
        ))
        
        self.register(Counter(
            "rfsn_tts_sentences_total",
            "Total sentences synthesized"
        ))
        
        self.register(Counter(
            "rfsn_tts_dropped_total",
            "Sentences dropped due to backpressure"
        ))
        
        # Queue metrics
        self.register(Gauge(
            "rfsn_tts_queue_size",
            "Current TTS queue size"
        ))
        
        # Memory metrics
        self.register(Counter(
            "rfsn_memory_turns_total",
            "Total conversation turns saved"
        ))
        
        self.register(Gauge(
            "rfsn_active_sessions",
            "Number of active NPC sessions"
        ))
        
        # Error metrics
        self.register(Counter(
            "rfsn_errors_total",
            "Total errors"
        ))
    
    def register(self, metric):
        """Register a metric"""
        with self._lock:
            self._metrics[metric.name] = metric
    
    def get(self, name: str):
        """Get a metric by name"""
        return self._metrics.get(name)
    
    def counter(self, name: str) -> Optional[Counter]:
        """Get a counter metric"""
        m = self.get(name)
        return m if isinstance(m, Counter) else None
    
    def gauge(self, name: str) -> Optional[Gauge]:
        """Get a gauge metric"""
        m = self.get(name)
        return m if isinstance(m, Gauge) else None
    
    def histogram(self, name: str) -> Optional[Histogram]:
        """Get a histogram metric"""
        m = self.get(name)
        return m if isinstance(m, Histogram) else None
    
    def summary(self, name: str) -> Optional[Summary]:
        """Get a summary metric"""
        m = self.get(name)
        return m if isinstance(m, Summary) else None
    
    def to_prometheus(self) -> str:
        """
        Generate Prometheus-format metrics output.
        """
        lines = []
        
        with self._lock:
            for name, metric in sorted(self._metrics.items()):
                # Add HELP and TYPE
                lines.append(f"# HELP {name} {metric.help}")
                
                if isinstance(metric, Counter):
                    lines.append(f"# TYPE {name} counter")
                elif isinstance(metric, Gauge):
                    lines.append(f"# TYPE {name} gauge")
                elif isinstance(metric, Histogram):
                    lines.append(f"# TYPE {name} histogram")
                elif isinstance(metric, Summary):
                    lines.append(f"# TYPE {name} summary")
                
                # Add metric value(s)
                prometheus_str = metric.to_prometheus()
                if prometheus_str:
                    lines.append(prometheus_str)
                
                lines.append("")  # Empty line between metrics
        
        return "\n".join(lines)


# Global registry
registry = MetricsRegistry()


# =============================================================================
# FASTAPI ROUTER
# =============================================================================

router = APIRouter()


@router.get("/metrics")
async def get_metrics():
    """
    Prometheus metrics endpoint.
    
    Returns metrics in Prometheus exposition format.
    """
    content = registry.to_prometheus()
    return Response(content=content, media_type="text/plain; charset=utf-8")


@router.get("/metrics/json")
async def get_metrics_json():
    """
    Get metrics in JSON format for debugging.
    """
    result = {}
    
    for name, metric in registry._metrics.items():
        if isinstance(metric, (Counter, Gauge)):
            result[name] = {"type": type(metric).__name__, "value": metric.value}
        elif isinstance(metric, Histogram):
            with metric._lock:
                values = metric._values.copy()
            if values:
                result[name] = {
                    "type": "Histogram",
                    "count": len(values),
                    "sum": sum(values),
                    "avg": sum(values) / len(values) if values else 0
                }
        elif isinstance(metric, Summary):
            with metric._lock:
                values = sorted(metric._values.copy())
            if values:
                n = len(values)
                result[name] = {
                    "type": "Summary",
                    "count": n,
                    "p50": values[n // 2],
                    "p99": values[int(n * 0.99)] if n >= 100 else values[-1]
                }
    
    return result


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def inc_requests():
    """Increment request counter"""
    registry.counter("rfsn_requests_total").inc()


def observe_request_duration(seconds: float):
    """Record request duration"""
    registry.histogram("rfsn_request_duration_seconds").observe(seconds)


def observe_first_token(seconds: float):
    """Record time to first token"""
    registry.histogram("rfsn_llm_first_token_seconds").observe(seconds)


def observe_generation_time(seconds: float):
    """Record total generation time"""
    registry.histogram("rfsn_llm_total_generation_seconds").observe(seconds)


def inc_tokens(count: int = 1):
    """Increment token counter"""
    registry.counter("rfsn_llm_tokens_generated_total").inc(count)


def observe_tts_synthesis(seconds: float):
    """Record TTS synthesis time"""
    registry.histogram("rfsn_tts_synthesis_seconds").observe(seconds)


def inc_tts_sentences():
    """Increment TTS sentence counter"""
    registry.counter("rfsn_tts_sentences_total").inc()


def inc_tts_dropped():
    """Increment dropped sentence counter"""
    registry.counter("rfsn_tts_dropped_total").inc()


def set_queue_size(size: int):
    """Set current TTS queue size"""
    registry.gauge("rfsn_tts_queue_size").set(size)


def inc_memory_turns():
    """Increment memory turn counter"""
    registry.counter("rfsn_memory_turns_total").inc()


def set_active_sessions(count: int):
    """Set active session count"""
    registry.gauge("rfsn_active_sessions").set(count)


def inc_errors():
    """Increment error counter"""
    registry.counter("rfsn_errors_total").inc()


if __name__ == "__main__":
    # Quick test
    print("Testing Prometheus Metrics...")
    
    # Record some metrics
    inc_requests()
    inc_requests()
    observe_request_duration(0.5)
    observe_request_duration(1.2)
    observe_first_token(0.8)
    set_queue_size(2)
    inc_tts_sentences()
    
    # Print output
    print("\nPrometheus Output:")
    print("-" * 40)
    print(registry.to_prometheus())
