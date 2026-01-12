"""
LearningContract: Formal learning boundary with write gate and rollback
Enforces constraints on what can be learned, how fast, and provides rollback capability.
"""
import threading
import hashlib
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, Optional, List, Set, Tuple
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class EvidenceType(Enum):
    """Types of evidence that can support a learning update"""
    USER_CORRECTION = "user_correction"
    CONTINUED_CONVERSATION = "continued_conversation"
    CONTRADICTION_DETECTED = "contradiction_detected"
    FOLLOW_UP_QUESTION = "follow_up_question"
    TTS_OVERRUN = "tts_overrun"


@dataclass
class LearningConstraints:
    """Constraints on learning updates"""
    # Fields that can be learned (allowlist)
    learnable_fields: Set[str] = field(default_factory=lambda: {
        "affinity",
        "mood",
        "relationship",
        "playstyle",
        "recent_sentiment"
    })
    
    # Maximum step size per update (prevents wild swings)
    max_step_size: Dict[str, float] = field(default_factory=lambda: {
        "affinity": 0.1,      # Max 10% change per update
        "mood": 1.0,          # Max 1 mood category change
        "relationship": 1.0,  # Max 1 relationship level change
        "playstyle": 1.0,     # Max 1 playstyle change
        "recent_sentiment": 0.2
    })
    
    # Cooldown periods between updates (seconds)
    cooldowns: Dict[str, float] = field(default_factory=lambda: {
        "affinity": 5.0,      # 5 seconds between affinity updates
        "mood": 10.0,         # 10 seconds between mood updates
        "relationship": 30.0, # 30 seconds between relationship updates
        "playstyle": 60.0,    # 60 seconds between playstyle updates
        "recent_sentiment": 2.0
    })
    
    # Minimum confidence required for update
    min_confidence: float = 0.3
    
    # Required evidence types for specific fields
    required_evidence: Dict[str, Set[EvidenceType]] = field(default_factory=lambda: {
        "affinity": {EvidenceType.USER_CORRECTION, EvidenceType.CONTINUED_CONVERSATION},
        "relationship": {EvidenceType.USER_CORRECTION},
        "playstyle": {EvidenceType.CONTINUED_CONVERSATION, EvidenceType.FOLLOW_UP_QUESTION}
    })


@dataclass
class LearningUpdate:
    """A proposed learning update with metadata"""
    field_name: str
    old_value: Any
    new_value: Any
    evidence_types: List[EvidenceType]
    confidence: float
    timestamp: datetime = field(default_factory=datetime.utcnow)
    source: str = "learner"  # Must be "learner" to pass write gate
    update_id: str = field(default="")
    
    def __post_init__(self):
        if not self.update_id:
            # Generate deterministic ID from content
            content = f"{self.field_name}:{self.old_value}:{self.new_value}:{self.timestamp.isoformat()}"
            self.update_id = hashlib.sha256(content.encode()).hexdigest()[:16]


@dataclass
class StateSnapshot:
    """Snapshot of learnable state for rollback"""
    snapshot_id: str
    timestamp: datetime
    state: Dict[str, Any]
    update_applied: Optional[LearningUpdate] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "timestamp": self.timestamp.isoformat(),
            "state": self.state,
            "update_applied": asdict(self.update_applied) if self.update_applied else None
        }


class WriteGateError(Exception):
    """Raised when write gate rejects an update"""
    pass


class LearningContract:
    """
    Enforces learning boundary with write gate and rollback.
    
    Only updates from the learner module are accepted.
    All updates must satisfy constraints and evidence requirements.
    Every update creates a reversible snapshot.
    """
    
    def __init__(self, constraints: Optional[LearningConstraints] = None,
                 snapshot_dir: Optional[Path] = None):
        """
        Initialize learning contract
        
        Args:
            constraints: Learning constraints (uses defaults if None)
            snapshot_dir: Directory to store snapshots for rollback
        """
        self.constraints = constraints or LearningConstraints()
        self.snapshot_dir = snapshot_dir or Path("data/learning/snapshots")
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        
        # Current learnable state
        self._state: Dict[str, Any] = {}
        
        # Track last update time per field for cooldowns
        self._last_update_time: Dict[str, datetime] = {}
        
        # Snapshots for rollback (keep last 100)
        self._snapshots: List[StateSnapshot] = []
        self._max_snapshots = 100
        
        # Thread safety
        self._lock = threading.RLock()
        
        logger.info("LearningContract initialized with write gate enabled")
    
    def validate_update(self, update: LearningUpdate) -> Tuple[bool, str]:
        """
        Validate a learning update against constraints
        
        Args:
            update: Proposed update
            
        Returns:
            (is_valid, reason)
        """
        # Write gate: only accept from learner
        if update.source != "learner":
            return False, f"Write gate rejected: source must be 'learner', got '{update.source}'"
        
        # Check field is learnable
        if update.field_name not in self.constraints.learnable_fields:
            return False, f"Field '{update.field_name}' not in learnable fields"
        
        # Check confidence threshold
        if update.confidence < self.constraints.min_confidence:
            return False, f"Confidence {update.confidence} below threshold {self.constraints.min_confidence}"
        
        # Check evidence requirements
        required = self.constraints.required_evidence.get(update.field_name, set())
        if required:
            evidence_set = set(update.evidence_types)
            if not required.issubset(evidence_set):
                missing = required - evidence_set
                return False, f"Missing required evidence for '{update.field_name}': {missing}"
        
        # Check cooldown
        last_update = self._last_update_time.get(update.field_name)
        if last_update:
            cooldown = self.constraints.cooldowns.get(update.field_name, 0)
            elapsed = (datetime.utcnow() - last_update).total_seconds()
            if elapsed < cooldown:
                return False, f"Cooldown active for '{update.field_name}': {cooldown - elapsed:.1f}s remaining"

        # Verify old_value matches current state (prevent inconsistencies)
        current_value = self._state.get(update.field_name)
        if current_value is not None and update.old_value != current_value:
            return False, f"Old value mismatch for '{update.field_name}': expected {current_value}, got {update.old_value}"
        
        # Check step size
        max_step = self.constraints.max_step_size.get(update.field_name, float('inf'))
        try:
            old_val = float(update.old_value)
            new_val = float(update.new_value)
            step = abs(new_val - old_val)
            if step > max_step:
                return False, f"Step size {step} exceeds max {max_step} for '{update.field_name}'"
        except (ValueError, TypeError):
            # Non-numeric fields: just check they're different
            if update.old_value == update.new_value:
                return False, f"No change detected for '{update.field_name}'"
        
        return True, "Valid"
    
    def create_snapshot(self, update: Optional[LearningUpdate] = None) -> StateSnapshot:
        """
        Create snapshot of current state before applying update
        
        Args:
            update: Update about to be applied (for reference)
            
        Returns:
            StateSnapshot
        """
        snapshot_id = hashlib.sha256(
            f"{datetime.utcnow().isoformat()}:{json.dumps(self._state, sort_keys=True)}".encode()
        ).hexdigest()[:16]
        
        snapshot = StateSnapshot(
            snapshot_id=snapshot_id,
            timestamp=datetime.utcnow(),
            state=self._state.copy(),
            update_applied=update
        )
        
        # Keep in memory
        self._snapshots.append(snapshot)
        if len(self._snapshots) > self._max_snapshots:
            self._snapshots.pop(0)
        
        # Persist to disk
        snapshot_file = self.snapshot_dir / f"{snapshot_id}.json"
        try:
            with open(snapshot_file, 'w') as f:
                json.dump(snapshot.to_dict(), f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to persist snapshot {snapshot_id}: {e}")
        
        logger.debug(f"Created snapshot {snapshot_id} for field {update.field_name if update else 'none'}")
        return snapshot
    
    def apply_update(self, update: LearningUpdate) -> StateSnapshot:
        """
        Apply a validated learning update with snapshot
        
        Args:
            update: Validated update to apply
            
        Returns:
            Snapshot of state before update
            
        Raises:
            WriteGateError: If update fails validation
        """
        with self._lock:
            # Validate
            is_valid, reason = self.validate_update(update)
            if not is_valid:
                raise WriteGateError(f"Update rejected: {reason}")
            
            # Create snapshot before applying
            snapshot = self.create_snapshot(update)
            
            # Apply update
            self._state[update.field_name] = update.new_value
            self._last_update_time[update.field_name] = update.timestamp
            
            logger.info(f"Applied learning update {update.update_id}: {update.field_name} = {update.new_value}")
            return snapshot
    
    def rollback(self, snapshot_id: str) -> bool:
        """
        Rollback state to a previous snapshot
        
        Args:
            snapshot_id: ID of snapshot to rollback to
            
        Returns:
            True if rollback succeeded
        """
        with self._lock:
            # Find snapshot
            snapshot = None
            for s in reversed(self._snapshots):
                if s.snapshot_id == snapshot_id:
                    snapshot = s
                    break
            
            if not snapshot:
                # Try loading from disk
                snapshot_file = self.snapshot_dir / f"{snapshot_id}.json"
                if snapshot_file.exists():
                    try:
                        with open(snapshot_file, 'r') as f:
                            data = json.load(f)
                            # Reconstruct LearningUpdate if available
                            update_applied = None
                            if data.get("update_applied"):
                                ua = data["update_applied"]
                                try:
                                    update_applied = LearningUpdate(
                                        field_name=ua["field_name"],
                                        old_value=ua["old_value"],
                                        new_value=ua["new_value"],
                                        evidence_types=[EvidenceType(e) for e in ua["evidence_types"]],
                                        confidence=ua["confidence"],
                                        timestamp=datetime.fromisoformat(ua["timestamp"]),
                                        source=ua.get("source", "learner"),
                                        update_id=ua.get("update_id", "")
                                    )
                                except Exception as e:
                                    logger.warning(f"Failed to reconstruct update_applied: {e}")

                            snapshot = StateSnapshot(
                                snapshot_id=data["snapshot_id"],
                                timestamp=datetime.fromisoformat(data["timestamp"]),
                                state=data["state"],
                                update_applied=update_applied
                            )
                    except Exception as e:
                        logger.error(f"Failed to load snapshot {snapshot_id}: {e}")
                        return False
                else:
                    logger.error(f"Snapshot {snapshot_id} not found")
                    return False
            
            # Restore state
            self._state = snapshot.state.copy()

            # Restore last update times from snapshot timestamp
            # (simplified: clear cooldowns for fields in snapshot state)
            for field in snapshot.state.keys():
                if field in self._last_update_time:
                    del self._last_update_time[field]
            
            logger.info(f"Rolled back to snapshot {snapshot_id} from {snapshot.timestamp}")
            return True
    
    def get_state(self) -> Dict[str, Any]:
        """Get current learnable state (read-only copy)"""
        with self._lock:
            return self._state.copy()
    
    def get_field(self, field_name: str, default: Any = None) -> Any:
        """Get a specific field value"""
        with self._lock:
            return self._state.get(field_name, default)
    
    def set_field(self, field_name: str, value: Any, source: str = "system"):
        """
        Set a field directly (bypasses learning, used for initialization)
        
        Args:
            field_name: Field to set
            value: Value to set
            source: Source identifier
        """
        with self._lock:
            if field_name not in self.constraints.learnable_fields:
                logger.warning(f"Setting non-learnable field '{field_name}' from {source}")
            
            self._state[field_name] = value
            logger.debug(f"Set '{field_name}' = {value} from {source}")
    
    def get_recent_snapshots(self, count: int = 10) -> List[Dict[str, Any]]:
        """Get recent snapshots for inspection"""
        with self._lock:
            return [s.to_dict() for s in self._snapshots[-count:]]
    
    def clear_old_snapshots(self, older_than_days: int = 7):
        """Clear snapshot files older than specified days"""
        cutoff = datetime.utcnow() - timedelta(days=older_than_days)
        cleared = 0
        cleared_ids = set()

        for snapshot_file in self.snapshot_dir.glob("*.json"):
            try:
                # Load snapshot to check its actual timestamp
                with open(snapshot_file, 'r') as f:
                    data = json.load(f)
                    snapshot_time = datetime.fromisoformat(data["timestamp"])
                    snapshot_id = data["snapshot_id"]

                if snapshot_time < cutoff:
                    snapshot_file.unlink()
                    cleared_ids.add(snapshot_id)
                    cleared += 1
            except Exception as e:
                logger.warning(f"Failed to delete old snapshot {snapshot_file}: {e}")

        # Also clear from memory
        with self._lock:
            self._snapshots = [s for s in self._snapshots if s.snapshot_id not in cleared_ids]

        logger.info(f"Cleared {cleared} old snapshots")
