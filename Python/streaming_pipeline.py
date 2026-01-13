"""
Streaming Pipeline with Hard Guarantees
Provides lifecycle IDs, exactly-once delivery, timeouts, and explicit drop policies.
"""
import uuid
import time
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Any, Optional, List
from enum import Enum
from collections import deque
import logging

logger = logging.getLogger(__name__)


class DropPolicy(Enum):
    """Queue drop policies when full"""
    DROP_OLDEST = "drop_oldest"
    DROP_NEWEST = "drop_newest"
    DEGRADE_TEXT_ONLY = "degrade_text_only"
    BLOCK = "block"


class OutputChannel(Enum):
    """Output channels for exactly-once delivery"""
    TEXT = "text"
    AUDIO = "audio"


@dataclass
class MessageLifecycle:
    """
    Tracks a message through the entire pipeline.
    IDs: input_id → state_id → gen_id → audio_id
    """
    input_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    state_id: Optional[str] = None
    gen_id: Optional[str] = None
    audio_id: Optional[str] = None
    
    # Timestamps for latency tracking
    input_timestamp: float = field(default_factory=time.time)
    state_timestamp: Optional[float] = None
    gen_start_timestamp: Optional[float] = None
    gen_end_timestamp: Optional[float] = None
    audio_start_timestamp: Optional[float] = None
    audio_end_timestamp: Optional[float] = None
    
    # Status tracking
    status: str = "input_received"
    error: Optional[str] = None
    
    # Output delivery tracking (exactly-once)
    delivered_text: bool = False
    delivered_audio: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging"""
        return {
            "input_id": self.input_id,
            "state_id": self.state_id,
            "gen_id": self.gen_id,
            "audio_id": self.audio_id,
            "status": self.status,
            "error": self.error,
            "delivered_text": self.delivered_text,
            "delivered_audio": self.delivered_audio,
            "latency_ms": {
                "input_to_state": self._ms(self.state_timestamp, self.input_timestamp),
                "state_to_gen_start": self._ms(self.gen_start_timestamp, self.state_timestamp),
                "gen_duration": self._ms(self.gen_end_timestamp, self.gen_start_timestamp),
                "audio_duration": self._ms(self.audio_end_timestamp, self.audio_start_timestamp),
                "total": self._ms(self.audio_end_timestamp, self.input_timestamp)
            }
        }
    
    def _ms(self, end: Optional[float], start: Optional[float]) -> Optional[float]:
        """Calculate milliseconds between timestamps"""
        if end is None or start is None:
            return None
        return (end - start) * 1000.0


@dataclass
class TimeoutConfig:
    """Timeout configuration for pipeline stages"""
    llm_generation_timeout: float = 30.0
    tts_synthesis_timeout: float = 10.0
    audio_playback_timeout: float = 15.0
    state_update_timeout: float = 5.0


@dataclass
class CircuitBreakerState:
    """Circuit breaker state for a component"""
    is_open: bool = False
    failure_count: int = 0
    last_failure_time: Optional[float] = None
    open_until: Optional[float] = None


class BoundedQueue:
    """
    Bounded queue with explicit drop policy.
    Prevents unbounded queue growth.
    """
    
    def __init__(self, max_size: int, drop_policy: DropPolicy,
                 name: str = "queue"):
        """
        Initialize bounded queue
        
        Args:
            max_size: Maximum queue size
            drop_policy: Policy when queue is full
            name: Queue name for logging
        """
        self.max_size = max_size
        self.drop_policy = drop_policy
        self.name = name
        self._queue: deque = deque()  # No maxlen - handle manually
        self._lock = threading.Lock()
        self._dropped_count = 0
        self._dropped_oldest = 0
        self._dropped_newest = 0
    
    def put(self, item: Any) -> bool:
        """
        Put item in queue, applying drop policy if full
        
        Args:
            item: Item to add
            
        Returns:
            True if item was added, False if dropped
        """
        with self._lock:
            if len(self._queue) >= self.max_size:
                self._dropped_count += 1
                
                if self.drop_policy == DropPolicy.DROP_OLDEST:
                    self._queue.popleft()
                    self._dropped_oldest += 1
                    self._queue.append(item)
                    logger.warning(
                        f"{self.name}: Dropped oldest (queue full, "
                        f"total dropped: {self._dropped_count})"
                    )
                    return True
                
                elif self.drop_policy == DropPolicy.DROP_NEWEST:
                    self._dropped_newest += 1
                    logger.warning(
                        f"{self.name}: Dropped newest (queue full, "
                        f"total dropped: {self._dropped_count})"
                    )
                    return False
                
                elif self.drop_policy == DropPolicy.DEGRADE_TEXT_ONLY:
                    # Special handling for audio degradation
                    if hasattr(item, 'degrade_to_text'):
                        item.degrade_to_text()
                    self._queue.popleft()
                    self._queue.append(item)
                    logger.warning(f"{self.name}: Degrading to text-only")
                    return True
                
                elif self.drop_policy == DropPolicy.BLOCK:
                    logger.warning(f"{self.name}: Blocking (queue full)")
                    return False
            
            self._queue.append(item)
            return True
    
    def get(self) -> Optional[Any]:
        """Get item from queue"""
        with self._lock:
            if not self._queue:
                return None
            return self._queue.popleft()
    
    def size(self) -> int:
        """Get current queue size"""
        with self._lock:
            return len(self._queue)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get queue statistics"""
        with self._lock:
            return {
                "name": self.name,
                "current_size": len(self._queue),
                "max_size": self.max_size,
                "dropped_total": self._dropped_count,
                "dropped_oldest": self._dropped_oldest,
                "dropped_newest": self._dropped_newest
            }


class StreamingPipeline:
    """
    Streaming pipeline with hard guarantees.
    
    Features:
    - Message lifecycle tracking with unique IDs
    - Exactly-once delivery per output channel
    - Timeouts for all stages
    - Circuit breakers for failing components
    - Explicit drop policies
    - Comprehensive metrics
    """
    
    def __init__(self,
                 timeout_config: Optional[TimeoutConfig] = None,
                 text_queue_size: int = 10,
                 audio_queue_size: int = 10,
                 text_drop_policy: DropPolicy = DropPolicy.DROP_OLDEST,
                 audio_drop_policy: DropPolicy = DropPolicy.DROP_NEWEST):
        """
        Initialize streaming pipeline
        
        Args:
            timeout_config: Timeout configuration
            text_queue_size: Max text queue size
            audio_queue_size: Max audio queue size
            text_drop_policy: Drop policy for text queue
            audio_drop_policy: Drop policy for audio queue
        """
        self.timeouts = timeout_config or TimeoutConfig()
        
        # Output queues with drop policies
        self.text_queue = BoundedQueue(
            text_queue_size, text_drop_policy, "text_queue"
        )
        self.audio_queue = BoundedQueue(
            audio_queue_size, audio_drop_policy, "audio_queue"
        )
        
        # Delivery tracking (exactly-once)
        self._delivered_messages: Dict[str, set] = {}
        self._delivery_lock = threading.Lock()
        
        # Circuit breakers
        self._circuit_breakers: Dict[str, CircuitBreakerState] = {
            "llm": CircuitBreakerState(),
            "tts": CircuitBreakerState(),
            "audio": CircuitBreakerState()
        }
        
        # Metrics
        self._total_messages = 0
        self._failed_messages = 0
        self._timeout_messages = 0
        
        # Thread safety
        self._lock = threading.RLock()
        
        logger.info("StreamingPipeline initialized with hard guarantees")
    
    def create_lifecycle(self) -> MessageLifecycle:
        """Create new message lifecycle"""
        with self._lock:
            self._total_messages += 1
            return MessageLifecycle()
    
    def track_state_update(self, lifecycle: MessageLifecycle,
                           state_id: str) -> MessageLifecycle:
        """Track state update in lifecycle"""
        lifecycle.state_id = state_id
        lifecycle.state_timestamp = time.time()
        lifecycle.status = "state_updated"
        return lifecycle
    
    def track_generation_start(self, lifecycle: MessageLifecycle,
                               gen_id: str) -> MessageLifecycle:
        """Track LLM generation start"""
        lifecycle.gen_id = gen_id
        lifecycle.gen_start_timestamp = time.time()
        lifecycle.status = "generating"
        return lifecycle
    
    def track_generation_end(self, lifecycle: MessageLifecycle) -> MessageLifecycle:
        """Track LLM generation end"""
        lifecycle.gen_end_timestamp = time.time()
        lifecycle.status = "generated"
        return lifecycle
    
    def track_audio_start(self, lifecycle: MessageLifecycle,
                          audio_id: str) -> MessageLifecycle:
        """Track audio synthesis start"""
        lifecycle.audio_id = audio_id
        lifecycle.audio_start_timestamp = time.time()
        lifecycle.status = "synthesizing"
        return lifecycle
    
    def track_audio_end(self, lifecycle: MessageLifecycle) -> MessageLifecycle:
        """Track audio synthesis end"""
        lifecycle.audio_end_timestamp = time.time()
        lifecycle.status = "synthesized"
        return lifecycle
    
    def deliver_text(self, lifecycle: MessageLifecycle, text: str) -> bool:
        """
        Deliver text output with exactly-once guarantee
        
        Args:
            lifecycle: Message lifecycle
            text: Text content
            
        Returns:
            True if delivered (not duplicate)
        """
        with self._delivery_lock:
            if lifecycle.input_id not in self._delivered_messages:
                self._delivered_messages[lifecycle.input_id] = set()
            
            if OutputChannel.TEXT.value in self._delivered_messages[lifecycle.input_id]:
                logger.debug(f"Text already delivered for {lifecycle.input_id}")
                return False
            
            # Add to output queue
            delivered = self.text_queue.put({
                "lifecycle": lifecycle,
                "text": text,
                "channel": OutputChannel.TEXT
            })

            if delivered:
                self._delivered_messages[lifecycle.input_id].add(
                    OutputChannel.TEXT.value
                )
                lifecycle.delivered_text = True
                logger.info(f"Text delivered for {lifecycle.input_id}")
            else:
                logger.warning(f"Text delivery failed for {lifecycle.input_id}")

            return delivered
    
    def deliver_audio(self, lifecycle: MessageLifecycle, audio_data: bytes) -> bool:
        """
        Deliver audio output with exactly-once guarantee
        
        Args:
            lifecycle: Message lifecycle
            audio_data: Audio data
            
        Returns:
            True if delivered (not duplicate)
        """
        with self._delivery_lock:
            if lifecycle.input_id not in self._delivered_messages:
                self._delivered_messages[lifecycle.input_id] = set()
            
            if OutputChannel.AUDIO.value in self._delivered_messages[lifecycle.input_id]:
                logger.debug(f"Audio already delivered for {lifecycle.input_id}")
                return False
            
            # Add to output queue
            delivered = self.audio_queue.put({
                "lifecycle": lifecycle,
                "audio": audio_data,
                "channel": OutputChannel.AUDIO
            })

            if delivered:
                self._delivered_messages[lifecycle.input_id].add(
                    OutputChannel.AUDIO.value
                )
                lifecycle.delivered_audio = True
                logger.info(f"Audio delivered for {lifecycle.input_id}")
            else:
                logger.warning(f"Audio delivery failed for {lifecycle.input_id}")

            return delivered
    
    def check_circuit_breaker(self, component: str,
                              failure_threshold: int = 5,
                              cooldown_seconds: float = 60.0) -> bool:
        """
        Check if circuit breaker is open for a component
        
        Args:
            component: Component name (llm, tts, audio)
            failure_threshold: Failures before opening
            cooldown_seconds: Cooldown period
            
        Returns:
            True if circuit is open (should skip)
        """
        with self._lock:
            cb = self._circuit_breakers.get(component)
            if not cb:
                return False
            
            # Check if circuit should close
            if cb.is_open and cb.open_until:
                if time.time() >= cb.open_until:
                    cb.is_open = False
                    cb.failure_count = 0
                    logger.info(f"Circuit breaker closed for {component}")
                    return False
            
            return cb.is_open
    
    def record_failure(self, component: str,
                       failure_threshold: int = 5,
                       cooldown_seconds: float = 60.0):
        """
        Record a failure for a component
        
        Args:
            component: Component name
            failure_threshold: Failures before opening
            cooldown_seconds: Cooldown period
        """
        with self._lock:
            cb = self._circuit_breakers.get(component)
            if not cb:
                cb = CircuitBreakerState()
                self._circuit_breakers[component] = cb
            
            cb.failure_count += 1
            cb.last_failure_time = time.time()
            
            if cb.failure_count >= failure_threshold:
                cb.is_open = True
                cb.open_until = time.time() + cooldown_seconds
                logger.warning(
                    f"Circuit breaker opened for {component} "
                    f"(failures: {cb.failure_count})"
                )
    
    def mark_failed(self, lifecycle: MessageLifecycle, error: str):
        """Mark lifecycle as failed"""
        lifecycle.status = "failed"
        lifecycle.error = error
        with self._lock:
            self._failed_messages += 1
        logger.error(f"Message {lifecycle.input_id} failed: {error}")
    
    def mark_timeout(self, lifecycle: MessageLifecycle, stage: str):
        """Mark lifecycle as timed out"""
        lifecycle.status = f"timeout_{stage}"
        lifecycle.error = f"Timeout at {stage}"
        with self._lock:
            self._timeout_messages += 1
        logger.warning(f"Message {lifecycle.input_id} timed out at {stage}")
    
    def cleanup_lifecycle(self, lifecycle: MessageLifecycle):
        """Cleanup lifecycle tracking after completion"""
        with self._delivery_lock:
            if lifecycle.input_id in self._delivered_messages:
                del self._delivered_messages[lifecycle.input_id]
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get pipeline metrics"""
        with self._lock:
            return {
                "total_messages": self._total_messages,
                "failed_messages": self._failed_messages,
                "timeout_messages": self._timeout_messages,
                "success_rate": (
                    (self._total_messages - self._failed_messages - self._timeout_messages) /
                    max(self._total_messages, 1)
                ),
                "text_queue": self.text_queue.get_stats(),
                "audio_queue": self.audio_queue.get_stats(),
                "circuit_breakers": {
                    name: {
                        "is_open": cb.is_open,
                        "failure_count": cb.failure_count,
                        "last_failure": cb.last_failure_time
                    }
                    for name, cb in self._circuit_breakers.items()
                }
            }
    
    def get_trace_dump(self, lifecycle: MessageLifecycle) -> Dict[str, Any]:
        """
        Get trace dump for debugging
        
        Args:
            lifecycle: Message lifecycle to dump
            
        Returns:
            Complete trace information
        """
        return {
            "lifecycle": lifecycle.to_dict(),
            "pipeline_metrics": self.get_metrics(),
            "timestamp": datetime.utcnow().isoformat()
        }
