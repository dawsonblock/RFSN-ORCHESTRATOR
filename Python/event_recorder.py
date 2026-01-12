"""
Event Recorder and Replayer: Deterministic execution and bug reproduction
Records all inputs, tool results, and actions for deterministic replay.
"""
import json
import time
import threading
import hashlib
import random
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Dict, Any, Optional, List, Callable
from pathlib import Path
from enum import Enum
import logging

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False
    np = None

logger = logging.getLogger(__name__)


class EventType(Enum):
    """Types of events that can be recorded"""
    USER_INPUT = "user_input"
    STATE_UPDATE = "state_update"
    LLM_GENERATION = "llm_generation"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    ACTION_CHOSEN = "action_chosen"
    MEMORY_ADDED = "memory_added"
    LEARNING_UPDATE = "learning_update"
    ERROR = "error"


@dataclass
class RecordedEvent:
    """A recorded event in the execution trace"""
    event_id: str = ""
    event_type: EventType = None
    timestamp: float = None
    data: Dict[str, Any] = None
    wall_clock_time: Optional[float] = None
    checksum: Optional[str] = None
    
    def __post_init__(self):
        if not self.event_id:
            content = f"{self.event_type.value}:{self.timestamp}:{json.dumps(self.data, sort_keys=True)}"
            self.event_id = hashlib.sha256(content.encode()).hexdigest()[:16]
        
        if not self.checksum:
            self.checksum = self._compute_checksum()
    
    def _compute_checksum(self) -> str:
        """Compute checksum for data integrity"""
        content = json.dumps(self.data, sort_keys=True)
        return hashlib.sha256(content.encode()).hexdigest()[:16]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage"""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "timestamp": self.timestamp,
            "datetime": datetime.fromtimestamp(self.timestamp).isoformat(),
            "wall_clock_time": self.wall_clock_time,
            "checksum": self.checksum,
            "data": self.data
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'RecordedEvent':
        """Create from dictionary"""
        return cls(
            event_id=data["event_id"],
            event_type=EventType(data["event_type"]),
            timestamp=data["timestamp"],
            data=data["data"],
            wall_clock_time=data.get("wall_clock_time"),
            checksum=data.get("checksum")
        )


class EventRecorder:
    """
    Records all events during execution for deterministic replay.
    Append-only log with integrity checking.
    """
    
    def __init__(self, session_id: Optional[str] = None,
                 output_dir: Optional[Path] = None):
        """
        Initialize event recorder
        
        Args:
            session_id: Unique session identifier
            output_dir: Directory to store recordings
        """
        self.session_id = session_id or hashlib.sha256(
            str(time.time()).encode()
        ).hexdigest()[:16]
        
        self.output_dir = output_dir or Path("data/recordings")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self._events: List[RecordedEvent] = []
        self._lock = threading.Lock()
        
        self._recording_file = self.output_dir / f"recording_{self.session_id}.jsonl"
        
        logger.info(f"EventRecorder initialized for session {self.session_id}")
    
    def record(self, event_type: EventType, data: Dict[str, Any],
               wall_clock_time: Optional[float] = None) -> RecordedEvent:
        """
        Record an event
        
        Args:
            event_type: Type of event
            data: Event data
            wall_clock_time: Actual wall clock time (for timing analysis)
            
        Returns:
            RecordedEvent
        """
        with self._lock:
            event = RecordedEvent(
                event_type=event_type,
                timestamp=time.time(),
                data=data,
                wall_clock_time=wall_clock_time or time.time()
            )
            
            self._events.append(event)
            
            # Append to file (append-only)
            try:
                with open(self._recording_file, 'a') as f:
                    f.write(json.dumps(event.to_dict()) + '\n')
            except Exception as e:
                logger.error(f"Failed to write event to file: {e}")
            
            logger.debug(f"Recorded event: {event_type.value} ({event.event_id})")
            return event
    
    def get_events(self, event_type: Optional[EventType] = None) -> List[RecordedEvent]:
        """
        Get recorded events, optionally filtered by type
        
        Args:
            event_type: Filter by event type
            
        Returns:
            List of events
        """
        with self._lock:
            if event_type:
                return [e for e in self._events if e.event_type == event_type]
            return self._events.copy()
    
    def get_event_count(self) -> int:
        """Get total number of recorded events"""
        with self._lock:
            return len(self._events)
    
    def verify_integrity(self) -> bool:
        """
        Verify integrity of all recorded events
        
        Returns:
            True if all checksums match
        """
        with self._lock:
            for event in self._events:
                computed = event._compute_checksum()
                if computed != event.checksum:
                    logger.error(f"Checksum mismatch for event {event.event_id}")
                    return False
            return True
    
    def save_recording(self, output_path: Optional[Path] = None) -> Path:
        """
        Save complete recording to file
        
        Args:
            output_path: Custom output path
            
        Returns:
            Path to saved recording
        """
        output_path = output_path or self.output_dir / f"recording_{self.session_id}.json"
        
        recording = {
            "session_id": self.session_id,
            "start_time": self._events[0].timestamp if self._events else None,
            "end_time": self._events[-1].timestamp if self._events else None,
            "event_count": len(self._events),
            "events": [e.to_dict() for e in self._events]
        }
        
        with open(output_path, 'w') as f:
            json.dump(recording, f, indent=2)
        
        logger.info(f"Recording saved to {output_path}")
        return output_path


class EventReplayer:
    """
    Replays recorded events for deterministic execution.
    Can replay in real-time or accelerated mode.
    """
    
    def __init__(self, recording_path: Path,
                 accelerated: bool = False,
                 time_scale: float = 1.0):
        """
        Initialize event replayer
        
        Args:
            recording_path: Path to recording file
            accelerated: If True, replay as fast as possible
            time_scale: Time scaling factor (1.0 = real-time, 0.1 = 10x faster)
        """
        self.recording_path = recording_path
        self.accelerated = accelerated
        self.time_scale = time_scale
        
        self._events: List[RecordedEvent] = []
        self._current_index = 0
        self._start_time: Optional[float] = None
        self._lock = threading.Lock()
        
        # Load recording
        self._load_recording()
        
        logger.info(f"EventReplayer initialized with {len(self._events)} events")
    
    def _load_recording(self):
        """Load recording from file"""
        if self.recording_path.suffix == '.jsonl':
            # JSONL format
            with open(self.recording_path, 'r') as f:
                for line in f:
                    if line.strip():
                        data = json.loads(line)
                        self._events.append(RecordedEvent.from_dict(data))
        else:
            # JSON format
            with open(self.recording_path, 'r') as f:
                recording = json.load(f)
                self._events = [
                    RecordedEvent.from_dict(e)
                    for e in recording.get("events", [])
                ]
        
        # Verify integrity
        for event in self._events:
            computed = event._compute_checksum()
            if computed != event.checksum:
                logger.warning(f"Checksum mismatch for event {event.event_id}")
    
    def reset(self):
        """Reset replayer to beginning"""
        with self._lock:
            self._current_index = 0
            self._start_time = None
    
    def next_event(self, wait: bool = True) -> Optional[RecordedEvent]:
        """
        Get next event, respecting timing
        
        Args:
            wait: If True, wait until event time
            
        Returns:
            Next event or None if finished
        """
        with self._lock:
            if self._current_index >= len(self._events):
                return None
            
            event = self._events[self._current_index]
            
            if not self._start_time:
                self._start_time = time.time()
            
            if wait and not self.accelerated:
                # Calculate time to wait
                elapsed = time.time() - self._start_time
                event_time = event.timestamp - self._events[0].timestamp
                scaled_time = event_time * self.time_scale
                
                if elapsed < scaled_time:
                    sleep_time = scaled_time - elapsed
                    time.sleep(sleep_time)
            
            self._current_index += 1
            return event
    
    def get_all_events(self) -> List[RecordedEvent]:
        """Get all events"""
        with self._lock:
            return self._events.copy()
    
    def get_progress(self) -> Dict[str, Any]:
        """Get replay progress"""
        with self._lock:
            total = len(self._events)
            if total == 0:
                return {
                    "current_index": self._current_index,
                    "total_events": 0,
                    "progress_percent": 0.0,
                    "completed": True
                }
            return {
                "current_index": self._current_index,
                "total_events": total,
                "progress_percent": (self._current_index / total * 100),
                "completed": self._current_index >= total
            }


class DeterministicOrchestrator:
    """
    Orchestrator wrapper that records all events for deterministic replay.
    Intercepts all inputs and outputs to ensure reproducibility.
    """
    
    def __init__(self, recorder: Optional[EventRecorder] = None):
        """
        Initialize deterministic orchestrator
        
        Args:
            recorder: Event recorder (creates one if None)
        """
        self.recorder = recorder or EventRecorder()
        self._seed: Optional[int] = None
        self._random_state: Optional[Dict[str, Any]] = None
        
        # Hook registry for intercepting calls
        self._hooks: Dict[str, List[Callable]] = {}
    
    def set_seed(self, seed: int):
        """
        Set random seed for deterministic execution
        
        Args:
            seed: Random seed
        """
        self._seed = seed
        random.seed(seed)
        if HAS_NUMPY:
            np.random.seed(seed)

        self.recorder.record(
            EventType.STATE_UPDATE,
            {"action": "set_seed", "seed": seed}
        )

        logger.info(f"Set deterministic seed: {seed}")
    
    def record_input(self, input_data: Dict[str, Any]) -> RecordedEvent:
        """Record user input"""
        return self.recorder.record(
            EventType.USER_INPUT,
            input_data
        )
    
    def record_state_update(self, field: str, old_value: Any, new_value: Any):
        """Record state update"""
        return self.recorder.record(
            EventType.STATE_UPDATE,
            {
                "field": field,
                "old_value": old_value,
                "new_value": new_value
            }
        )
    
    def record_llm_generation(self, prompt: str, response: str,
                             metadata: Optional[Dict[str, Any]] = None):
        """Record LLM generation"""
        return self.recorder.record(
            EventType.LLM_GENERATION,
            {
                "prompt": prompt,
                "response": response,
                "metadata": metadata or {}
            }
        )
    
    def record_tool_call(self, tool_name: str, arguments: Dict[str, Any]):
        """Record tool call"""
        return self.recorder.record(
            EventType.TOOL_CALL,
            {
                "tool": tool_name,
                "arguments": arguments
            }
        )
    
    def record_tool_result(self, tool_name: str, result: Any,
                          error: Optional[str] = None):
        """Record tool result"""
        return self.recorder.record(
            EventType.TOOL_RESULT,
            {
                "tool": tool_name,
                "result": result,
                "error": error
            }
        )
    
    def record_action(self, action_type: str, action_data: Dict[str, Any]):
        """Record action chosen"""
        return self.recorder.record(
            EventType.ACTION_CHOSEN,
            {
                "action_type": action_type,
                "action_data": action_data
            }
        )
    
    def record_memory(self, memory_type: str, content: str,
                     metadata: Optional[Dict[str, Any]] = None):
        """Record memory addition"""
        return self.recorder.record(
            EventType.MEMORY_ADDED,
            {
                "memory_type": memory_type,
                "content": content,
                "metadata": metadata or {}
            }
        )
    
    def record_learning(self, field: str, old_value: Any, new_value: Any,
                       evidence: List[str]):
        """Record learning update"""
        return self.recorder.record(
            EventType.LEARNING_UPDATE,
            {
                "field": field,
                "old_value": old_value,
                "new_value": new_value,
                "evidence": evidence
            }
        )
    
    def record_error(self, error_type: str, error_message: str,
                    context: Optional[Dict[str, Any]] = None):
        """Record error"""
        return self.recorder.record(
            EventType.ERROR,
            {
                "error_type": error_type,
                "error_message": error_message,
                "context": context or {}
            }
        )
    
    def register_hook(self, event_type: EventType, callback: Callable):
        """
        Register a hook for specific event types
        
        Args:
            event_type: Event type to hook
            callback: Callback function
        """
        if event_type.value not in self._hooks:
            self._hooks[event_type.value] = []
        self._hooks[event_type.value].append(callback)
    
    def trigger_hooks(self, event: RecordedEvent):
        """Trigger all hooks for an event"""
        hooks = self._hooks.get(event.event_type.value, [])
        for hook in hooks:
            try:
                hook(event)
            except Exception as e:
                logger.error(f"Hook error: {e}")
    
    def save_recording(self, output_path: Optional[Path] = None) -> Path:
        """Save recording to file"""
        return self.recorder.save_recording(output_path)
    
    def get_recorder(self) -> EventRecorder:
        """Get the event recorder"""
        return self.recorder


def create_replay_session(recording_path: Path,
                         accelerated: bool = False) -> EventReplayer:
    """
    Create a replay session from a recording
    
    Args:
        recording_path: Path to recording file
        accelerated: If True, replay as fast as possible
        
    Returns:
        EventReplayer instance
    """
    return EventReplayer(recording_path, accelerated=accelerated)


def verify_recording_integrity(recording_path: Path) -> bool:
    """
    Verify integrity of a recording file

    Args:
        recording_path: Path to recording

    Returns:
        True if integrity verified
    """
    recorder = EventRecorder()
    # Load events directly without modifying internal state
    events = []

    if recording_path.suffix == '.jsonl':
        with open(recording_path, 'r') as f:
            for line in f:
                if line.strip():
                    data = json.loads(line)
                    event = RecordedEvent.from_dict(data)
                    events.append(event)
    else:
        with open(recording_path, 'r') as f:
            recording_data = json.load(f)
            events = [
                RecordedEvent.from_dict(e)
                for e in recording_data.get("events", [])
            ]

    # Verify integrity
    for event in events:
        computed = event._compute_checksum()
        if computed != event.checksum:
            logger.error(f"Checksum mismatch for event {event.event_id}")
            return False

    return True
