"""
Observability: Structured JSON logging with trace correlation
Provides metrics, trace dumps, and correlated logs across the pipeline.
"""
import json
import time
import threading
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Dict, Any, Optional, List
from pathlib import Path
from collections import deque
import uuid

logger = logging.getLogger(__name__)


@dataclass
class TraceContext:
    """Correlation context for a request trace"""
    trace_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    parent_span_id: Optional[str] = None
    span_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    tags: Dict[str, str] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class LogEvent:
    """Structured log event with correlation"""
    timestamp: float
    level: str
    message: str
    trace_context: Optional[TraceContext] = None
    metrics: Dict[str, float] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        result = {
            "timestamp": self.timestamp,
            "datetime": datetime.fromtimestamp(self.timestamp).isoformat(),
            "level": self.level,
            "message": self.message,
            "metrics": self.metrics,
            "metadata": self.metadata
        }
        if self.trace_context:
            result["trace"] = self.trace_context.to_dict()
        return result


class MetricsCollector:
    """Collects and aggregates metrics"""
    
    def __init__(self, max_history: int = 1000):
        """
        Initialize metrics collector
        
        Args:
            max_history: Maximum number of data points to keep per metric
        """
        self._counters: Dict[str, int] = {}
        self._gauges: Dict[str, List[float]] = {}
        self._histograms: Dict[str, List[float]] = {}
        self._max_history = max_history
        self._lock = threading.Lock()
    
    def increment(self, name: str, value: int = 1, tags: Optional[Dict[str, str]] = None):
        """Increment a counter"""
        with self._lock:
            key = self._make_key(name, tags)
            self._counters[key] = self._counters.get(key, 0) + value
    
    def set_gauge(self, name: str, value: float, tags: Optional[Dict[str, str]] = None):
        """Set a gauge value"""
        with self._lock:
            key = self._make_key(name, tags)
            if key not in self._gauges:
                self._gauges[key] = deque(maxlen=self._max_history)
            self._gauges[key].append(value)
    
    def record_histogram(self, name: str, value: float,
                        tags: Optional[Dict[str, str]] = None):
        """Record a histogram value"""
        with self._lock:
            key = self._make_key(name, tags)
            if key not in self._histograms:
                self._histograms[key] = deque(maxlen=self._max_history)
            self._histograms[key].append(value)
    
    def _make_key(self, name: str, tags: Optional[Dict[str, str]]) -> str:
        """Create a metric key from name and tags"""
        if not tags:
            return name
        tag_str = ",".join(f"{k}={v}" for k, v in sorted(tags.items()))
        return f"{name}{{{tag_str}}}"
    
    def get_counter(self, name: str, tags: Optional[Dict[str, str]] = None) -> int:
        """Get counter value"""
        with self._lock:
            key = self._make_key(name, tags)
            return self._counters.get(key, 0)
    
    def get_gauge_stats(self, name: str,
                       tags: Optional[Dict[str, str]] = None) -> Dict[str, float]:
        """Get gauge statistics (min, max, avg, current)"""
        with self._lock:
            key = self._make_key(name, tags)
            values = list(self._gauges.get(key, []))
            if not values:
                return {}
            
            return {
                "count": len(values),
                "min": min(values),
                "max": max(values),
                "avg": sum(values) / len(values),
                "current": values[-1]
            }
    
    def get_histogram_stats(self, name: str,
                           tags: Optional[Dict[str, str]] = None) -> Dict[str, float]:
        """Get histogram statistics (percentiles)"""
        with self._lock:
            key = self._make_key(name, tags)
            values = sorted(self._histograms.get(key, []))
            if not values:
                return {}
            
            n = len(values)
            if n < 2:
                return {
                    "count": n,
                    "min": values[0] if n > 0 else None,
                    "max": values[-1] if n > 0 else None,
                    "avg": sum(values) / n if n > 0 else None,
                    "p50": values[0] if n > 0 else None,
                    "p95": values[0] if n > 0 else None,
                    "p99": values[0] if n > 0 else None
                }
            return {
                "count": n,
                "min": values[0],
                "max": values[-1],
                "avg": sum(values) / n,
                "p50": values[int(n * 0.5)],
                "p95": values[min(int(n * 0.95), n - 1)],
                "p99": values[min(int(n * 0.99), n - 1)]
            }
    
    def get_all_metrics(self) -> Dict[str, Any]:
        """Get all metrics"""
        with self._lock:
            return {
                "counters": dict(self._counters),
                "gauges": {
                    key: self.get_gauge_stats(key)
                    for key in self._gauges.keys()
                },
                "histograms": {
                    key: self.get_histogram_stats(key)
                    for key in self._histograms.keys()
                }
            }


class TraceDumper:
    """
    Captures and dumps trace information for debugging.
    Stores last N events per trace for failure analysis.
    """
    
    def __init__(self, max_traces: int = 100, max_events_per_trace: int = 50):
        """
        Initialize trace dumper
        
        Args:
            max_traces: Maximum number of traces to keep
            max_events_per_trace: Maximum events per trace
        """
        self.max_traces = max_traces
        self.max_events_per_trace = max_events_per_trace
        
        self._traces: Dict[str, List[Dict[str, Any]]] = {}
        self._trace_metadata: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        
        self._trace_order: deque = deque(maxlen=max_traces)
    
    def start_trace(self, trace_id: str, metadata: Optional[Dict[str, Any]] = None):
        """Start a new trace"""
        with self._lock:
            self._traces[trace_id] = []
            self._trace_metadata[trace_id] = metadata or {}
            self._trace_order.append(trace_id)
            
            # Evict oldest if needed
            while len(self._traces) > self.max_traces:
                oldest = self._trace_order.popleft()
                if oldest in self._traces:
                    del self._traces[oldest]
                if oldest in self._trace_metadata:
                    del self._trace_metadata[oldest]
    
    def add_event(self, trace_id: str, event: Dict[str, Any]):
        """Add an event to a trace"""
        with self._lock:
            if trace_id not in self._traces:
                self.start_trace(trace_id)
            
            events = self._traces[trace_id]
            events.append({
                "timestamp": time.time(),
                **event
            })
            
            # Limit events per trace
            if len(events) > self.max_events_per_trace:
                events.pop(0)
    
    def get_trace(self, trace_id: str) -> Optional[Dict[str, Any]]:
        """Get a complete trace"""
        with self._lock:
            if trace_id not in self._traces:
                return None
            
            return {
                "trace_id": trace_id,
                "metadata": self._trace_metadata.get(trace_id, {}),
                "events": self._traces[trace_id],
                "event_count": len(self._traces[trace_id])
            }
    
    def get_recent_traces(self, count: int = 10) -> List[Dict[str, Any]]:
        """Get recent traces"""
        with self._lock:
            recent_ids = list(self._trace_order)[-count:]
            return [self.get_trace(tid) for tid in recent_ids if tid in self._traces]
    
    def dump_trace_to_file(self, trace_id: str, output_dir: Path):
        """Dump trace to file for offline analysis"""
        trace = self.get_trace(trace_id)
        if not trace:
            return
        
        output_dir.mkdir(parents=True, exist_ok=True)
        output_file = output_dir / f"trace_{trace_id}.json"
        
        with open(output_file, 'w') as f:
            json.dump(trace, f, indent=2, default=str)
        
        return output_file


class StructuredLogger:
    """
    Structured JSON logger with trace correlation.
    All logs are JSON-formatted with correlation IDs.
    """
    
    def __init__(self, name: str,
                 log_level: str = "INFO",
                 log_file: Optional[Path] = None):
        """
        Initialize structured logger
        
        Args:
            name: Logger name
            log_level: Log level
            log_file: Optional log file path
        """
        self.logger = logging.getLogger(name)
        self.logger.setLevel(getattr(logging, log_level.upper()))
        
        # Clear existing handlers
        self.logger.handlers.clear()
        
        # Console handler with JSON formatter
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(JSONFormatter())
        self.logger.addHandler(console_handler)
        
        # File handler if specified
        if log_file:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(log_file)
            file_handler.setFormatter(JSONFormatter())
            self.logger.addHandler(file_handler)
        
        # Metrics and trace dumper
        self.metrics = MetricsCollector()
        self.trace_dumper = TraceDumper()
    
    def log(self, level: str, message: str,
            trace_context: Optional[TraceContext] = None,
            metrics: Optional[Dict[str, float]] = None,
            **kwargs):
        """
        Log a structured event
        
        Args:
            level: Log level
            message: Log message
            trace_context: Trace correlation context
            metrics: Metrics to record
            **kwargs: Additional metadata
        """
        # Create log event
        event = LogEvent(
            timestamp=time.time(),
            level=level,
            message=message,
            trace_context=trace_context,
            metrics=metrics or {},
            metadata=kwargs
        )
        
        # Log via standard logging
        level_lower = level.lower()
        if not hasattr(self.logger, level_lower):
            level_lower = "info"
        log_fn = getattr(self.logger, level_lower, self.logger.info)
        log_fn(json.dumps(event.to_dict()))
        
        # Record metrics
        if metrics:
            for name, value in metrics.items():
                if isinstance(value, (int, float)):
                    self.metrics.record_histogram(name, value)
        
        # Add to trace if context provided
        if trace_context:
            self.trace_dumper.add_event(
                trace_context.trace_id,
                {
                    "level": level,
                    "message": message,
                    "metrics": metrics,
                    **kwargs
                }
            )
    
    def debug(self, message: str, trace_context: Optional[TraceContext] = None,
              **kwargs):
        self.log("DEBUG", message, trace_context, **kwargs)
    
    def info(self, message: str, trace_context: Optional[TraceContext] = None,
             **kwargs):
        self.log("INFO", message, trace_context, **kwargs)
    
    def warning(self, message: str, trace_context: Optional[TraceContext] = None,
                **kwargs):
        self.log("WARNING", message, trace_context, **kwargs)
    
    def error(self, message: str, trace_context: Optional[TraceContext] = None,
              **kwargs):
        self.log("ERROR", message, trace_context, **kwargs)
    
    def critical(self, message: str, trace_context: Optional[TraceContext] = None,
                 **kwargs):
        self.log("CRITICAL", message, trace_context, **kwargs)
    
    def increment_counter(self, name: str, value: int = 1,
                         tags: Optional[Dict[str, str]] = None):
        """Increment a counter metric"""
        self.metrics.increment(name, value, tags)
    
    def set_gauge(self, name: str, value: float,
                 tags: Optional[Dict[str, str]] = None):
        """Set a gauge metric"""
        self.metrics.set_gauge(name, value, tags)
    
    def record_latency(self, name: str, value_ms: float,
                      tags: Optional[Dict[str, str]] = None):
        """Record a latency metric"""
        self.metrics.record_histogram(name, value_ms, tags)
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get all metrics"""
        return self.metrics.get_all_metrics()
    
    def get_trace_dump(self, trace_id: str) -> Optional[Dict[str, Any]]:
        """Get trace dump for debugging"""
        return self.trace_dumper.get_trace(trace_id)
    
    def dump_failure_trace(self, trace_id: str, output_dir: Path):
        """Dump trace on failure"""
        return self.trace_dumper.dump_trace_to_file(trace_id, output_dir)


class JSONFormatter(logging.Formatter):
    """JSON formatter for structured logging"""
    
    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON"""
        log_dict = {
            "timestamp": record.created,
            "datetime": datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno
        }
        
        # Add exception info if present
        if record.exc_info:
            log_dict["exception"] = self.formatException(record.exc_info)
        
        # Add extra fields
        for key, value in record.__dict__.items():
            if key not in {
                'name', 'msg', 'args', 'created', 'filename', 'funcName',
                'levelname', 'levelno', 'pathname', 'lineno', 'module',
                'exc_info', 'exc_text', 'stack_info', 'message', 'asctime'
            }:
                log_dict[key] = value
        
        return json.dumps(log_dict, default=str)


# Global observability instance
_observability: Optional[StructuredLogger] = None


def get_observability() -> StructuredLogger:
    """Get global observability instance"""
    global _observability
    if _observability is None:
        _observability = StructuredLogger("rfsn")
    return _observability


def init_observability(name: str = "rfsn",
                       log_level: str = "INFO",
                       log_file: Optional[Path] = None) -> StructuredLogger:
    """
    Initialize global observability
    
    Args:
        name: Logger name
        log_level: Log level
        log_file: Optional log file path
        
    Returns:
        StructuredLogger instance
    """
    global _observability
    _observability = StructuredLogger(name, log_level, log_file)
    return _observability
