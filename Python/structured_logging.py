#!/usr/bin/env python3
"""
RFSN Structured Logging v8.2
JSON structured logs with request tracking and component-level configuration.
"""

import json
import logging
import sys
import threading
import time
import traceback
import uuid
from contextvars import ContextVar
from datetime import datetime
from functools import wraps
from typing import Any, Dict, Optional

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware


# Context variable for request ID tracking
request_id_var: ContextVar[str] = ContextVar('request_id', default='')
npc_name_var: ContextVar[str] = ContextVar('npc_name', default='')


class JSONFormatter(logging.Formatter):
    """
    JSON structured log formatter.
    
    Output format:
    {
        "timestamp": "2024-01-01T12:00:00.000Z",
        "level": "INFO",
        "logger": "rfsn.orchestrator",
        "message": "Request processed",
        "request_id": "abc123",
        "npc": "Lydia",
        "latency_ms": 150,
        ...extra fields
    }
    """
    
    RESERVED_ATTRS = {
        'name', 'msg', 'args', 'created', 'filename', 'funcName',
        'levelname', 'levelno', 'lineno', 'module', 'msecs',
        'pathname', 'process', 'processName', 'relativeCreated',
        'stack_info', 'exc_info', 'exc_text', 'thread', 'threadName',
        'message', 'asctime'
    }
    
    def __init__(self, include_stack: bool = False):
        super().__init__()
        self.include_stack = include_stack
    
    def format(self, record: logging.LogRecord) -> str:
        # Base log entry
        log_entry = {
            "timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        
        # Add context variables
        request_id = request_id_var.get()
        if request_id:
            log_entry["request_id"] = request_id
        
        npc_name = npc_name_var.get()
        if npc_name:
            log_entry["npc"] = npc_name
        
        # Add location info for errors
        if record.levelno >= logging.WARNING:
            log_entry["location"] = {
                "file": record.filename,
                "line": record.lineno,
                "function": record.funcName
            }
        
        # Add exception info
        if record.exc_info:
            log_entry["exception"] = {
                "type": record.exc_info[0].__name__ if record.exc_info[0] else None,
                "message": str(record.exc_info[1]) if record.exc_info[1] else None,
            }
            if self.include_stack:
                log_entry["exception"]["traceback"] = traceback.format_exception(*record.exc_info)
        
        # Add extra fields from record
        for key, value in record.__dict__.items():
            if key not in self.RESERVED_ATTRS and not key.startswith('_'):
                try:
                    json.dumps(value)  # Check if serializable
                    log_entry[key] = value
                except (TypeError, ValueError):
                    log_entry[key] = str(value)
        
        return json.dumps(log_entry, default=str)


class StructuredLogger(logging.Logger):
    """
    Logger with structured logging support.
    
    Usage:
        logger = get_logger("rfsn.orchestrator")
        logger.info("Request processed", latency_ms=150, tokens=42)
    """
    
    def _log(self, level, msg, args, exc_info=None, extra=None, stack_info=False, **kwargs):
        # Merge kwargs into extra
        if kwargs:
            extra = extra or {}
            extra.update(kwargs)
        
        super()._log(level, msg, args, exc_info, extra, stack_info)


# Register custom logger class
logging.setLoggerClass(StructuredLogger)


def get_logger(name: str, level: int = logging.INFO) -> StructuredLogger:
    """
    Get a structured logger.
    
    Args:
        name: Logger name (e.g., "rfsn.orchestrator")
        level: Logging level
    
    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)
    
    # Only add handler if not already configured
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JSONFormatter(include_stack=level <= logging.DEBUG))
        logger.addHandler(handler)
    
    return logger


def configure_logging(
    level: str = "INFO",
    json_format: bool = True,
    component_levels: Dict[str, str] = None
):
    """
    Configure logging for the entire application.
    
    Args:
        level: Default log level
        json_format: Use JSON formatting
        component_levels: Component-specific log levels
            e.g., {"rfsn.tts": "DEBUG", "rfsn.memory": "WARNING"}
    """
    # Set root level
    root_level = getattr(logging, level.upper())
    logging.root.setLevel(root_level)
    
    # Configure root handler
    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)
    
    handler = logging.StreamHandler(sys.stdout)
    if json_format:
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        ))
    logging.root.addHandler(handler)
    
    # Apply component-specific levels
    if component_levels:
        for component, comp_level in component_levels.items():
            logging.getLogger(component).setLevel(getattr(logging, comp_level.upper()))


# =============================================================================
# REQUEST TRACKING MIDDLEWARE
# =============================================================================

class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware for request logging with:
    - Unique request ID generation
    - Request/response timing
    - Structured logging
    """
    
    def __init__(self, app, logger_name: str = "rfsn.http"):
        super().__init__(app)
        self.logger = get_logger(logger_name)
    
    async def dispatch(self, request: Request, call_next):
        # Generate request ID
        request_id = str(uuid.uuid4())[:8]
        request_id_var.set(request_id)
        
        # Store in request state for access in handlers
        request.state.request_id = request_id
        
        # Log request
        start_time = time.time()
        self.logger.info(
            "Request started",
            method=request.method,
            path=request.url.path,
            client_ip=request.client.host if request.client else None
        )
        
        try:
            response = await call_next(request)
            
            # Calculate duration
            duration_ms = (time.time() - start_time) * 1000
            
            # Log response
            self.logger.info(
                "Request completed",
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                duration_ms=round(duration_ms, 2)
            )
            
            # Add request ID header
            response.headers["X-Request-ID"] = request_id
            
            return response
            
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            
            self.logger.error(
                "Request failed",
                method=request.method,
                path=request.url.path,
                error=str(e),
                duration_ms=round(duration_ms, 2),
                exc_info=True
            )
            raise


# =============================================================================
# PERFORMANCE LOGGING DECORATORS
# =============================================================================

def log_performance(logger_name: str = "rfsn.performance"):
    """
    Decorator to log function performance.
    
    Usage:
        @log_performance()
        def my_function():
            ...
    """
    logger = get_logger(logger_name)
    
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            start = time.time()
            try:
                result = func(*args, **kwargs)
                duration_ms = (time.time() - start) * 1000
                logger.info(
                    f"{func.__name__} completed",
                    function=func.__name__,
                    duration_ms=round(duration_ms, 2)
                )
                return result
            except Exception as e:
                duration_ms = (time.time() - start) * 1000
                logger.error(
                    f"{func.__name__} failed",
                    function=func.__name__,
                    duration_ms=round(duration_ms, 2),
                    error=str(e),
                    exc_info=True
                )
                raise
        
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            start = time.time()
            try:
                result = await func(*args, **kwargs)
                duration_ms = (time.time() - start) * 1000
                logger.info(
                    f"{func.__name__} completed",
                    function=func.__name__,
                    duration_ms=round(duration_ms, 2)
                )
                return result
            except Exception as e:
                duration_ms = (time.time() - start) * 1000
                logger.error(
                    f"{func.__name__} failed",
                    function=func.__name__,
                    duration_ms=round(duration_ms, 2),
                    error=str(e),
                    exc_info=True
                )
                raise
        
        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return wrapper
    
    return decorator


def set_npc_context(npc_name: str):
    """Set NPC name in logging context"""
    npc_name_var.set(npc_name)


def get_request_id() -> str:
    """Get current request ID"""
    return request_id_var.get()


# =============================================================================
# LOG AGGREGATION HELPERS
# =============================================================================

class MetricsCollector:
    """
    Collect and aggregate metrics for logging.
    """
    
    def __init__(self):
        self._metrics: Dict[str, list] = {}
        self._lock = threading.Lock()
    
    def record(self, name: str, value: float):
        """Record a metric value"""
        with self._lock:
            if name not in self._metrics:
                self._metrics[name] = []
            self._metrics[name].append(value)
    
    def get_stats(self, name: str) -> Dict[str, float]:
        """Get statistics for a metric"""
        with self._lock:
            values = self._metrics.get(name, [])
            if not values:
                return {}
            
            sorted_values = sorted(values)
            n = len(sorted_values)
            
            return {
                "count": n,
                "min": sorted_values[0],
                "max": sorted_values[-1],
                "avg": sum(values) / n,
                "p50": sorted_values[n // 2],
                "p95": sorted_values[int(n * 0.95)] if n >= 20 else sorted_values[-1],
                "p99": sorted_values[int(n * 0.99)] if n >= 100 else sorted_values[-1]
            }
    
    def reset(self, name: str = None):
        """Reset metrics (all or specific)"""
        with self._lock:
            if name:
                self._metrics.pop(name, None)
            else:
                self._metrics.clear()


# Global metrics collector
metrics = MetricsCollector()


if __name__ == "__main__":
    # Quick test
    configure_logging(level="DEBUG", json_format=True)
    
    logger = get_logger("rfsn.test")
    
    # Basic logging
    logger.info("Test message", custom_field="value", count=42)
    
    # With context
    request_id_var.set("abc123")
    npc_name_var.set("Lydia")
    logger.info("Contextualized message")
    
    # Error logging
    try:
        raise ValueError("Test error")
    except Exception:
        logger.error("An error occurred", exc_info=True)
    
    # Metrics
    for i in range(100):
        metrics.record("latency_ms", i * 10)
    
    print("\nMetrics stats:")
    print(json.dumps(metrics.get_stats("latency_ms"), indent=2))
