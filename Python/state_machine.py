"""
State Machine with Invariants and Transition Audit
Enforces invariants on state transitions and logs all changes.
"""
import json
import time
import threading
import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Any, Optional, List, Callable, Tuple
from pathlib import Path
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class StateTransitionError(Exception):
    """Raised when a state transition violates invariants"""
    pass


@dataclass
class StateTransition:
    """A recorded state transition"""
    transition_id: str
    timestamp: float
    field_name: str
    old_value: Any
    new_value: Any
    event: str
    validation_passed: bool
    violation_message: Optional[str] = None
    context: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "transition_id": self.transition_id,
            "timestamp": self.timestamp,
            "datetime": datetime.fromtimestamp(self.timestamp).isoformat(),
            "field_name": self.field_name,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "event": self.event,
            "validation_passed": self.validation_passed,
            "violation_message": self.violation_message,
            "context": self.context
        }


class InvariantType(Enum):
    """Types of invariants"""
    RANGE = "range"
    RELATIONSHIP = "relationship"
    ENUM = "enum"
    CUSTOM = "custom"


@dataclass
class Invariant:
    """An invariant constraint on a state field"""
    field_name: str
    invariant_type: InvariantType
    params: Dict[str, Any] = field(default_factory=dict)
    validator: Optional[Callable[[Any, Any], bool]] = None
    error_message: Optional[str] = None
    
    def validate(self, old_value: Any, new_value: Any,
                full_state: Optional[Dict[str, Any]] = None) -> Tuple[bool, Optional[str]]:
        """
        Validate a state transition against this invariant
        
        Args:
            old_value: Previous value
            new_value: New value
            full_state: Full state for relationship invariants
            
        Returns:
            (is_valid, error_message)
        """
        if self.validator:
            try:
                is_valid = self.validator(old_value, new_value, full_state)
                return is_valid, self.error_message if not is_valid else None
            except Exception as e:
                return False, f"Validator error: {e}"
        
        # Built-in invariant types
        if self.invariant_type == InvariantType.RANGE:
            min_val = self.params.get("min", float("-inf"))
            max_val = self.params.get("max", float("inf"))
            
            try:
                val = float(new_value)
                if val < min_val or val > max_val:
                    return False, f"Value {val} outside range [{min_val}, {max_val}]"
            except (ValueError, TypeError):
                return False, f"Cannot convert {new_value} to float for range check"
        
        elif self.invariant_type == InvariantType.ENUM:
            allowed = self.params.get("allowed", [])
            if new_value not in allowed:
                return False, f"Value {new_value} not in allowed values {allowed}"
        
        elif self.invariant_type == InvariantType.RELATIONSHIP:
            if full_state is None:
                return False, "Relationship invariant requires full state"
            
            other_field = self.params.get("other_field")
            relationship = self.params.get("relationship")  # "lt", "gt", "eq", "neq"
            
            if other_field not in full_state:
                return False, f"Other field {other_field} not in state"
            
            other_value = full_state[other_field]
            
            try:
                new_val = float(new_value)
                other_val = float(other_value)
                
                if relationship == "lt" and not (new_val < other_val):
                    return False, f"{self.field_name} ({new_val}) must be < {other_field} ({other_val})"
                elif relationship == "gt" and not (new_val > other_val):
                    return False, f"{self.field_name} ({new_val}) must be > {other_field} ({other_val})"
                elif relationship == "eq" and not (new_val == other_val):
                    return False, f"{self.field_name} ({new_val}) must equal {other_field} ({other_val})"
                elif relationship == "neq" and not (new_val != other_val):
                    return False, f"{self.field_name} ({new_val}) must not equal {other_field} ({other_val})"
            except (ValueError, TypeError):
                return False, f"Cannot compare {new_value} and {other_value}"
        
        return True, None


class DriftDetector:
    """
    Detects oscillation or drift in state values.
    Damps rapid changes that indicate instability.
    """
    
    def __init__(self, window_size: int = 10,
                 oscillation_threshold: int = 5,
                 damping_factor: float = 0.5):
        """
        Initialize drift detector
        
        Args:
            window_size: Size of history window
            oscillation_threshold: Changes in window to trigger oscillation
            damping_factor: Factor to damp oscillating values
        """
        self.window_size = window_size
        self.oscillation_threshold = oscillation_threshold
        self.damping_factor = damping_factor
        
        self._history: Dict[str, List[Tuple[float, Any]]] = {}
        self._lock = threading.Lock()
    
    def check_drift(self, field_name: str, old_value: Any,
                   new_value: Any) -> Tuple[bool, Optional[Any]]:
        """
        Check for drift and return damped value if needed
        
        Args:
            field_name: Field to check
            old_value: Previous value
            new_value: Proposed new value
            
        Returns:
            (has_drift, damped_value)
        """
        with self._lock:
            if field_name not in self._history:
                self._history[field_name] = []
            
            history = self._history[field_name]
            
            # Add new value to history
            history.append((time.time(), new_value))
            
            # Keep only recent history
            if len(history) > self.window_size:
                history.pop(0)
            
            # Check for oscillation
            if len(history) >= self.oscillation_threshold:
                # Count direction changes
                changes = 0
                for i in range(1, len(history)):
                    try:
                        prev_val = float(history[i-1][1])
                        curr_val = float(history[i][1])
                        if curr_val != prev_val:
                            changes += 1
                    except (ValueError, TypeError):
                        continue
                
                if changes >= self.oscillation_threshold:
                    # Oscillation detected - apply damping
                    try:
                        old_num = float(old_value)
                        new_num = float(new_value)
                        damped = old_num + (new_num - old_num) * self.damping_factor
                        logger.warning(
                            f"Oscillation detected for {field_name}, "
                            f"damping from {new_value} to {damped}"
                        )
                        return True, damped
                    except (ValueError, TypeError):
                        pass
            
            return False, None


class StateMachine:
    """
    State machine with invariants, transition auditing, and drift detection.
    All state changes go through validation and are logged.
    """
    
    def __init__(self, initial_state: Optional[Dict[str, Any]] = None,
                 audit_log_path: Optional[Path] = None):
        """
        Initialize state machine
        
        Args:
            initial_state: Initial state values
            audit_log_path: Path to audit log file
        """
        self._state: Dict[str, Any] = initial_state or {}
        self._invariants: List[Invariant] = []
        self._transitions: List[StateTransition] = []
        
        self._drift_detector = DriftDetector()
        self._lock = threading.RLock()
        
        self.audit_log_path = audit_log_path or Path("data/audit/state_audit.jsonl")
        self.audit_log_path.parent.mkdir(parents=True, exist_ok=True)
        
        logger.info("StateMachine initialized")
    
    def add_invariant(self, invariant: Invariant):
        """
        Add an invariant constraint
        
        Args:
            invariant: Invariant to add
        """
        with self._lock:
            self._invariants.append(invariant)
            logger.debug(f"Added invariant for {invariant.field_name}")
    
    def add_range_invariant(self, field_name: str, min_val: float, max_val: float,
                           error_message: Optional[str] = None):
        """Add a range invariant"""
        self.add_invariant(Invariant(
            field_name=field_name,
            invariant_type=InvariantType.RANGE,
            params={"min": min_val, "max": max_val},
            error_message=error_message
        ))
    
    def add_enum_invariant(self, field_name: str, allowed_values: List[Any],
                          error_message: Optional[str] = None):
        """Add an enum invariant"""
        self.add_invariant(Invariant(
            field_name=field_name,
            invariant_type=InvariantType.ENUM,
            params={"allowed": allowed_values},
            error_message=error_message
        ))
    
    def add_relationship_invariant(self, field_name: str, other_field: str,
                                  relationship: str,
                                  error_message: Optional[str] = None):
        """Add a relationship invariant"""
        self.add_invariant(Invariant(
            field_name=field_name,
            invariant_type=InvariantType.RELATIONSHIP,
            params={
                "other_field": other_field,
                "relationship": relationship
            },
            error_message=error_message
        ))
    
    def add_custom_invariant(self, field_name: str,
                            validator: Callable[[Any, Any, Optional[Dict[str, Any]]], bool],
                            error_message: Optional[str] = None):
        """Add a custom invariant"""
        self.add_invariant(Invariant(
            field_name=field_name,
            invariant_type=InvariantType.CUSTOM,
            validator=validator,
            error_message=error_message
        ))
    
    def get_state(self) -> Dict[str, Any]:
        """Get current state (read-only copy)"""
        with self._lock:
            return self._state.copy()
    
    def get_field(self, field_name: str, default: Any = None) -> Any:
        """Get a specific field value"""
        with self._lock:
            return self._state.get(field_name, default)
    
    def set_field(self, field_name: str, value: Any, event: str = "update",
                  context: Optional[Dict[str, Any]] = None) -> bool:
        """
        Set a field value with invariant validation
        
        Args:
            field_name: Field to set
            value: New value
            event: Event name for audit
            context: Additional context
            
        Returns:
            True if transition succeeded
            
        Raises:
            StateTransitionError: If invariants are violated
        """
        with self._lock:
            old_value = self._state.get(field_name)
            
            # Check for drift
            has_drift, damped_value = self._drift_detector.check_drift(
                field_name, old_value, value
            )
            if has_drift and damped_value is not None:
                value = damped_value
            
            # Validate against invariants
            violations = []
            for invariant in self._invariants:
                if invariant.field_name == field_name:
                    is_valid, error_msg = invariant.validate(
                        old_value, value, self._state
                    )
                    if not is_valid:
                        violations.append(error_msg or "Invariant violation")
            
            if violations:
                transition = StateTransition(
                    transition_id=self._generate_transition_id(),
                    timestamp=time.time(),
                    field_name=field_name,
                    old_value=old_value,
                    new_value=value,
                    event=event,
                    validation_passed=False,
                    violation_message="; ".join(violations),
                    context=context
                )
                self._transitions.append(transition)
                self._audit_transition(transition)
                
                error_msg = f"State transition failed for {field_name}: {violations[0]}"
                logger.error(error_msg)
                raise StateTransitionError(error_msg)
            
            # Apply transition
            self._state[field_name] = value
            
            # Record successful transition
            transition = StateTransition(
                transition_id=self._generate_transition_id(),
                timestamp=time.time(),
                field_name=field_name,
                old_value=old_value,
                new_value=value,
                event=event,
                validation_passed=True,
                context=context
            )
            self._transitions.append(transition)
            self._audit_transition(transition)
            
            logger.debug(f"State transition: {field_name} = {value}")
            return True
    
    def _generate_transition_id(self) -> str:
        """Generate unique transition ID"""
        content = f"{time.time()}:{len(self._transitions)}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]
    
    def _audit_transition(self, transition: StateTransition):
        """Write transition to audit log"""
        try:
            with open(self.audit_log_path, 'a') as f:
                f.write(json.dumps(transition.to_dict()) + '\n')
        except Exception as e:
            logger.error(f"Failed to write audit log: {e}")
    
    def get_transitions(self, field_name: Optional[str] = None,
                       limit: Optional[int] = None) -> List[StateTransition]:
        """
        Get transition history
        
        Args:
            field_name: Filter by field name
            limit: Maximum number of transitions
            
        Returns:
            List of transitions
        """
        with self._lock:
            transitions = self._transitions.copy()
            
            if field_name:
                transitions = [t for t in transitions if t.field_name == field_name]
            
            if limit:
                transitions = transitions[-limit:]
            
            return transitions
    
    def get_transition_stats(self) -> Dict[str, Any]:
        """Get transition statistics"""
        with self._lock:
            total = len(self._transitions)
            failed = sum(1 for t in self._transitions if not t.validation_passed)
            
            # Field-level stats
            field_counts = {}
            for t in self._transitions:
                field_counts[t.field_name] = field_counts.get(t.field_name, 0) + 1
            
            return {
                "total_transitions": total,
                "successful_transitions": total - failed,
                "failed_transitions": failed,
                "success_rate": (total - failed) / max(total, 1),
                "transitions_per_field": field_counts
            }
    
    def validate_state(self) -> Tuple[bool, List[str]]:
        """
        Validate current state against all invariants
        
        Returns:
            (is_valid, violation_messages)
        """
        with self._lock:
            violations = []
            
            for invariant in self._invariants:
                current_value = self._state.get(invariant.field_name)
                is_valid, error_msg = invariant.validate(
                    current_value, current_value, self._state
                )
                if not is_valid:
                    violations.append(
                        f"{invariant.field_name}: {error_msg}"
                    )
            
            return len(violations) == 0, violations
    
    def load_from_audit(self, audit_path: Optional[Path] = None):
        """
        Load state from audit log (reconstruct from transitions)
        
        Args:
            audit_path: Path to audit log
        """
        audit_path = audit_path or self.audit_log_path
        
        if not audit_path.exists():
            logger.warning(f"Audit log not found: {audit_path}")
            return
        
        with self._lock:
            self._state.clear()
            self._transitions.clear()
            
            with open(audit_path, 'r') as f:
                for line in f:
                    if line.strip():
                        data = json.loads(line)
                        transition = StateTransition(
                            transition_id=data["transition_id"],
                            timestamp=data["timestamp"],
                            field_name=data["field_name"],
                            old_value=data["old_value"],
                            new_value=data["new_value"],
                            event=data["event"],
                            validation_passed=data["validation_passed"],
                            violation_message=data.get("violation_message"),
                            context=data.get("context")
                        )
                        
                        if transition.validation_passed:
                            self._state[transition.field_name] = transition.new_value
                        
                        self._transitions.append(transition)
            
            # Validate loaded state
            is_valid, violations = self.validate_state()
            if not is_valid:
                logger.warning(f"Loaded state has violations: {violations}")
            
            logger.info(f"Loaded state from audit: {len(self._transitions)} transitions")


class RFSNStateMachine(StateMachine):
    """
    Specialized state machine for RFSN with pre-configured invariants.
    """
    
    def __init__(self, initial_state: Optional[Dict[str, Any]] = None,
                 audit_log_path: Optional[Path] = None):
        super().__init__(initial_state, audit_log_path)
        
        # Add RFSN-specific invariants
        self._setup_rfsn_invariants()
    
    def _setup_rfsn_invariants(self):
        """Configure RFSN-specific invariants"""
        # Affinity: must be in [-1, 1]
        self.add_range_invariant("affinity", -1.0, 1.0,
                                "Affinity must be between -1 and 1")
        
        # Mood: must be valid mood
        self.add_enum_invariant("mood",
                                ["happy", "neutral", "sad", "angry",
                                 "fearful", "surprised"],
                                "Invalid mood value")
        
        # Relationship: must be valid relationship
        self.add_enum_invariant("relationship",
                                ["stranger", "acquaintance", "friend",
                                 "ally", "enemy", "rival"],
                                "Invalid relationship value")
        
        # Playstyle: must be valid playstyle
        self.add_enum_invariant("playstyle",
                                ["aggressive", "diplomatic", "stealthy",
                                 "balanced"],
                                "Invalid playstyle value")
        
        # Recent sentiment: must be in [-1, 1]
        self.add_range_invariant("recent_sentiment", -1.0, 1.0,
                                "Recent sentiment must be between -1 and 1")
        
        # Custom: affinity and relationship consistency
        def affinity_relationship_consistency(old_aff, new_aff, state):
            """Affinity should align with relationship"""
            relationship = state.get("relationship", "stranger")
            
            if relationship == "enemy" and new_aff > 0:
                return False
            if relationship == "ally" and new_aff < 0:
                return False
            return True
        
        self.add_custom_invariant(
            "affinity",
            affinity_relationship_consistency,
            "Affinity inconsistent with relationship"
        )
        
        logger.info("RFSN invariants configured")

    def apply_transition(self, state_before: Dict[str, Any],
                        player_signal: str,
                        npc_action: str) -> Dict[str, Any]:
        """
        Authoritative state transition function.

        This is the single source of truth for state transitions.
        It applies effects based on the chosen NPC action and player signal.

        Args:
            state_before: State dictionary before the transition
            player_signal: PlayerSignal value (e.g., "greet", "insult")
            npc_action: NPCAction value (e.g., "GREET", "APOLOGIZE")

        Returns:
            state_after: State dictionary after the transition
        """
        state_after = state_before.copy()

        # Base affinity adjustment based on player signal
        affinity_delta = 0.0
        if player_signal == "greet":
            affinity_delta = 0.1
        elif player_signal == "insult":
            affinity_delta = -0.2
        elif player_signal == "apologize":
            affinity_delta = 0.15
        elif player_signal == "help":
            affinity_delta = 0.2
        elif player_signal == "threaten":
            affinity_delta = -0.3
        elif player_signal == "compliment":
            affinity_delta = 0.15

        # Apply NPC action effects
        if npc_action == "APOLOGIZE":
            affinity_delta += 0.1
            state_after["mood"] = "sad" if state_before.get("mood") != "sad" else state_before["mood"]
        elif npc_action == "INSULT":
            affinity_delta -= 0.25
            state_after["mood"] = "angry"
        elif npc_action == "COMPLIMENT":
            affinity_delta += 0.1
            state_after["mood"] = "happy"
        elif npc_action == "THREATEN":
            affinity_delta -= 0.3
            state_after["mood"] = "angry"
        elif npc_action == "HELP":
            affinity_delta += 0.15
            state_after["mood"] = "happy"
        elif npc_action == "AGREE":
            affinity_delta += 0.05
        elif npc_action == "DISAGREE":
            affinity_delta -= 0.05

        # Apply affinity change with bounds
        current_affinity = state_before.get("affinity", 0.0)
        new_affinity = max(-1.0, min(1.0, current_affinity + affinity_delta))
        state_after["affinity"] = new_affinity

        # Update relationship based on affinity
        if new_affinity < -0.5:
            state_after["relationship"] = "enemy"
        elif new_affinity < 0.0:
            state_after["relationship"] = "rival"
        elif new_affinity < 0.5:
            state_after["relationship"] = "friend"
        else:
            state_after["relationship"] = "ally"

        # Log the transition
        logger.info(
            f"State transition: {player_signal} -> {npc_action}, "
            f"affinity {current_affinity:.2f} -> {new_affinity:.2f}"
        )

        # Validate the new state
        is_valid, violations = self.validate_state(state_after)
        if not is_valid:
            logger.warning(f"Transition produced invalid state: {violations}")

        return state_after
