"""
World Model for RFSN: Predicts state transitions from actions.
Implements retrieval-based prediction and hand-authored transition rules.
"""
import json
import math
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List, Tuple
from pathlib import Path
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class NPCAction(Enum):
    """Discrete set of NPC actions for world model learning"""
    GREET = "greet"
    FAREWELL = "farewell"
    AGREE = "agree"
    DISAGREE = "disagree"
    APOLOGIZE = "apologize"
    INSULT = "insult"
    COMPLIMENT = "compliment"
    THREATEN = "threaten"
    REQUEST = "request"
    OFFER = "offer"
    REFUSE = "refuse"
    ACCEPT = "accept"
    ATTACK = "attack"
    DEFEND = "defend"
    FLEE = "flee"
    HELP = "help"
    BETRAY = "betray"
    IGNORE = "ignore"
    INQUIRE = "inquire"
    EXPLAIN = "explain"


class PlayerSignal(Enum):
    """Discrete player signals for world model learning"""
    GREET = "greet"
    FAREWELL = "farewell"
    AGREE = "agree"
    DISAGREE = "disagree"
    APOLOGIZE = "apologize"
    INSULT = "insult"
    COMPLIMENT = "compliment"
    THREATEN = "threaten"
    REQUEST = "request"
    OFFER = "offer"
    REFUSE = "refuse"
    ACCEPT = "accept"
    ATTACK = "attack"
    HELP = "help"
    BETRAY = "betray"
    IGNORE = "ignore"
    QUESTION = "question"
    COMMAND = "command"
    FLEE = "flee"


@dataclass
class StateSnapshot:
    """Snapshot of NPC state for world model training"""
    mood: str
    affinity: float
    relationship: str
    recent_sentiment: float
    combat_active: bool = False
    quest_active: bool = False
    trust_level: float = 0.5
    fear_level: float = 0.0
    additional_fields: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "mood": self.mood,
            "affinity": self.affinity,
            "relationship": self.relationship,
            "recent_sentiment": self.recent_sentiment,
            "combat_active": self.combat_active,
            "quest_active": self.quest_active,
            "trust_level": self.trust_level,
            "fear_level": self.fear_level,
            **self.additional_fields
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'StateSnapshot':
        """Create from dictionary"""
        return cls(
            mood=data.get("mood", "neutral"),
            affinity=data.get("affinity", 0.0),
            relationship=data.get("relationship", "stranger"),
            recent_sentiment=data.get("recent_sentiment", 0.0),
            combat_active=data.get("combat_active", False),
            quest_active=data.get("quest_active", False),
            trust_level=data.get("trust_level", 0.5),
            fear_level=data.get("fear_level", 0.0),
            additional_fields={k: v for k, v in data.items() 
                             if k not in ["mood", "affinity", "relationship", 
                                         "recent_sentiment", "combat_active", 
                                         "quest_active", "trust_level", "fear_level"]}
        )
    
    def distance_to(self, other: 'StateSnapshot') -> float:
        """Calculate Euclidean distance to another state"""
        # Numeric fields
        numeric_diff = (
            (self.affinity - other.affinity) ** 2 +
            (self.recent_sentiment - other.recent_sentiment) ** 2 +
            (self.trust_level - other.trust_level) ** 2 +
            (self.fear_level - other.fear_level) ** 2
        )
        
        # Categorical fields (0 if same, 1 if different)
        cat_diff = 0
        if self.mood != other.mood:
            cat_diff += 1
        if self.relationship != other.relationship:
            cat_diff += 1
        if self.combat_active != other.combat_active:
            cat_diff += 1
        if self.quest_active != other.quest_active:
            cat_diff += 1
        
        return math.sqrt(numeric_diff + cat_diff)


@dataclass
class Transition:
    """A state transition for world model training"""
    state_before: StateSnapshot
    npc_action: NPCAction
    player_signal: PlayerSignal
    state_after: StateSnapshot
    reward: float = 0.0
    timestamp: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "state_before": self.state_before.to_dict(),
            "npc_action": self.npc_action.value,
            "player_signal": self.player_signal.value,
            "state_after": self.state_after.to_dict(),
            "reward": self.reward,
            "timestamp": self.timestamp
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Transition':
        """Create from dictionary"""
        return cls(
            state_before=StateSnapshot.from_dict(data["state_before"]),
            npc_action=NPCAction(data["npc_action"]),
            player_signal=PlayerSignal(data["player_signal"]),
            state_after=StateSnapshot.from_dict(data["state_after"]),
            reward=data.get("reward", 0.0),
            timestamp=data.get("timestamp", 0.0)
        )


class HandAuthoredRules:
    """
    Hand-authored transition rules for hard physics and invariants.
    Provides predictable behavior for critical game mechanics.
    """
    
    def __init__(self):
        """Initialize hand-authored rules"""
        self._rules = self._setup_rules()
    
    def _setup_rules(self) -> Dict[Tuple[NPCAction, PlayerSignal], callable]:
        """Setup hand-authored transition rules"""
        return {
            # Insult rules
            (NPCAction.INSULT, PlayerSignal.INSULT): self._mutual_insult,
            (NPCAction.INSULT, PlayerSignal.APOLOGIZE): self._insult_apology,
            (NPCAction.INSULT, PlayerSignal.THREATEN): self._escalate_to_combat,
            
            # Threat rules
            (NPCAction.THREATEN, PlayerSignal.THREATEN): self._escalate_to_combat,
            (NPCAction.THREATEN, PlayerSignal.APOLOGIZE): self._threat_apology,
            (NPCAction.THREATEN, PlayerSignal.ATTACK): self._combat_imminent,
            
            # Apology rules
            (NPCAction.APOLOGIZE, PlayerSignal.ACCEPT): self._apology_accepted,
            (NPCAction.APOLOGIZE, PlayerSignal.REFUSE): self._apology_refused,
            
            # Compliment rules
            (NPCAction.COMPLIMENT, PlayerSignal.COMPLIMENT): self._mutual_compliment,
            (NPCAction.COMPLIMENT, PlayerSignal.INSULT): self._compliment_insult,
            
            # Betrayal rules
            (NPCAction.BETRAY, PlayerSignal.ATTACK): self._betrayal_combat,
            (NPCAction.BETRAY, PlayerSignal.FLEE): self._betrayal_flee,
            
            # Help rules
            (NPCAction.HELP, PlayerSignal.COMPLIMENT): self._help_rewarded,
            (NPCAction.HELP, PlayerSignal.BETRAY): self._help_betrayed,
        }
    
    def predict(self, state: StateSnapshot, action: NPCAction, 
                player_signal: PlayerSignal) -> Optional[StateSnapshot]:
        """
        Predict next state using hand-authored rules
        
        Args:
            state: Current state
            action: NPC action
            player_signal: Player signal
            
        Returns:
            Predicted next state or None if no rule applies
        """
        rule_key = (action, player_signal)
        if rule_key in self._rules:
            return self._rules[rule_key](state)
        return None
    
    def _mutual_insult(self, state: StateSnapshot) -> StateSnapshot:
        """Both parties insult each other"""
        return StateSnapshot(
            mood="angry",
            affinity=max(-1.0, state.affinity - 0.3),
            relationship="enemy" if state.affinity < -0.5 else state.relationship,
            recent_sentiment=-0.8,
            combat_active=state.combat_active,
            quest_active=state.quest_active,
            trust_level=max(0.0, state.trust_level - 0.2),
            fear_level=state.fear_level
        )
    
    def _insult_apology(self, state: StateSnapshot) -> StateSnapshot:
        """NPC insults, player apologizes"""
        return StateSnapshot(
            mood="neutral",
            affinity=max(-0.5, state.affinity - 0.1),
            relationship=state.relationship,
            recent_sentiment=-0.3,
            combat_active=False,
            quest_active=state.quest_active,
            trust_level=state.trust_level,
            fear_level=state.fear_level
        )
    
    def _escalate_to_combat(self, state: StateSnapshot) -> StateSnapshot:
        """Mutual threats escalate to combat"""
        return StateSnapshot(
            mood="angry",
            affinity=-1.0,
            relationship="enemy",
            recent_sentiment=-1.0,
            combat_active=True,
            quest_active=state.quest_active,
            trust_level=0.0,
            fear_level=min(1.0, state.fear_level + 0.3)
        )
    
    def _threat_apology(self, state: StateSnapshot) -> StateSnapshot:
        """NPC threatens, player apologizes"""
        return StateSnapshot(
            mood="fearful",
            affinity=max(-0.3, state.affinity - 0.1),
            relationship=state.relationship,
            recent_sentiment=-0.5,
            combat_active=False,
            quest_active=state.quest_active,
            trust_level=max(0.0, state.trust_level - 0.1),
            fear_level=min(1.0, state.fear_level + 0.2)
        )
    
    def _combat_imminent(self, state: StateSnapshot) -> StateSnapshot:
        """NPC threatens, player attacks"""
        return StateSnapshot(
            mood="angry",
            affinity=-1.0,
            relationship="enemy",
            recent_sentiment=-1.0,
            combat_active=True,
            quest_active=state.quest_active,
            trust_level=0.0,
            fear_level=min(1.0, state.fear_level + 0.4)
        )
    
    def _apology_accepted(self, state: StateSnapshot) -> StateSnapshot:
        """NPC apologizes, player accepts"""
        return StateSnapshot(
            mood="neutral",
            affinity=min(1.0, state.affinity + 0.1),
            relationship=state.relationship,
            recent_sentiment=0.3,
            combat_active=False,
            quest_active=state.quest_active,
            trust_level=min(1.0, state.trust_level + 0.1),
            fear_level=max(0.0, state.fear_level - 0.1)
        )
    
    def _apology_refused(self, state: StateSnapshot) -> StateSnapshot:
        """NPC apologizes, player refuses"""
        return StateSnapshot(
            mood="sad",
            affinity=max(-1.0, state.affinity - 0.2),
            relationship=state.relationship,
            recent_sentiment=-0.4,
            combat_active=state.combat_active,
            quest_active=state.quest_active,
            trust_level=max(0.0, state.trust_level - 0.1),
            fear_level=state.fear_level
        )
    
    def _mutual_compliment(self, state: StateSnapshot) -> StateSnapshot:
        """Both parties compliment each other"""
        return StateSnapshot(
            mood="happy",
            affinity=min(1.0, state.affinity + 0.2),
            relationship="friend" if state.affinity > 0.5 else state.relationship,
            recent_sentiment=0.8,
            combat_active=False,
            quest_active=state.quest_active,
            trust_level=min(1.0, state.trust_level + 0.1),
            fear_level=max(0.0, state.fear_level - 0.1)
        )
    
    def _compliment_insult(self, state: StateSnapshot) -> StateSnapshot:
        """NPC compliments, player insults"""
        return StateSnapshot(
            mood="sad",
            affinity=max(-1.0, state.affinity - 0.3),
            relationship=state.relationship,
            recent_sentiment=-0.2,
            combat_active=state.combat_active,
            quest_active=state.quest_active,
            trust_level=max(0.0, state.trust_level - 0.2),
            fear_level=min(1.0, state.fear_level + 0.1)
        )
    
    def _betrayal_combat(self, state: StateSnapshot) -> StateSnapshot:
        """NPC betrays, player attacks"""
        return StateSnapshot(
            mood="angry",
            affinity=-1.0,
            relationship="enemy",
            recent_sentiment=-1.0,
            combat_active=True,
            quest_active=False,
            trust_level=0.0,
            fear_level=min(1.0, state.fear_level + 0.5)
        )
    
    def _betrayal_flee(self, state: StateSnapshot) -> StateSnapshot:
        """NPC betrays, player flees"""
        return StateSnapshot(
            mood="angry",
            affinity=-1.0,
            relationship="enemy",
            recent_sentiment=-0.8,
            combat_active=False,
            quest_active=state.quest_active,
            trust_level=0.0,
            fear_level=state.fear_level
        )
    
    def _help_rewarded(self, state: StateSnapshot) -> StateSnapshot:
        """NPC helps, player compliments"""
        return StateSnapshot(
            mood="happy",
            affinity=min(1.0, state.affinity + 0.3),
            relationship="ally" if state.affinity > 0.7 else state.relationship,
            recent_sentiment=0.9,
            combat_active=False,
            quest_active=state.quest_active,
            trust_level=min(1.0, state.trust_level + 0.2),
            fear_level=max(0.0, state.fear_level - 0.2)
        )
    
    def _help_betrayed(self, state: StateSnapshot) -> StateSnapshot:
        """NPC helps, player betrays"""
        return StateSnapshot(
            mood="angry",
            affinity=-1.0,
            relationship="enemy",
            recent_sentiment=-1.0,
            combat_active=True,
            quest_active=False,
            trust_level=0.0,
            fear_level=min(1.0, state.fear_level + 0.3)
        )


class RetrievalWorldModel:
    """
    Retrieval-based world model using historical transitions.
    Finds K-nearest past states and predicts outcomes by majority/average.
    """
    
    def __init__(self, k_neighbors: int = 5):
        """
        Initialize retrieval world model
        
        Args:
            k_neighbors: Number of neighbors to retrieve
        """
        self.k_neighbors = k_neighbors
        self._transitions: List[Transition] = []
    
    def add_transition(self, transition: Transition):
        """
        Add a transition to the history
        
        Args:
            transition: Transition to add
        """
        self._transitions.append(transition)
        logger.debug(f"Added transition: {transition.npc_action.value}")
    
    def load_from_file(self, path: Path):
        """
        Load transitions from file
        
        Args:
            path: Path to transition file
        """
        if not path.exists():
            logger.warning(f"Transition file not found: {path}")
            return
        
        with open(path, 'r') as f:
            data = json.load(f)
            self._transitions = [
                Transition.from_dict(t) for t in data.get("transitions", [])
            ]
        
        logger.info(f"Loaded {len(self._transitions)} transitions from {path}")
    
    def save_to_file(self, path: Path):
        """
        Save transitions to file
        
        Args:
            path: Path to save transitions
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        
        data = {
            "transition_count": len(self._transitions),
            "transitions": [t.to_dict() for t in self._transitions]
        }
        
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)
        
        logger.info(f"Saved {len(self._transitions)} transitions to {path}")
    
    def get_transition_count(self) -> int:
        """Get number of recorded transitions"""
        return len(self._transitions)
    
    def predict(self, state: StateSnapshot, action: NPCAction,
                player_signal: PlayerSignal) -> Optional[StateSnapshot]:
        """
        Predict next state using retrieval
        
        Args:
            state: Current state
            action: NPC action
            player_signal: Player signal
            
        Returns:
            Predicted next state or None if no similar transitions found
        """
        if len(self._transitions) == 0:
            return None
        
        # Find similar transitions
        similar = self._find_similar_transitions(state, action, player_signal)
        
        if len(similar) == 0:
            return None
        
        # Aggregate predictions
        return self._aggregate_predictions(similar)
    
    def _find_similar_transitions(self, state: StateSnapshot, 
                                   action: NPCAction,
                                   player_signal: PlayerSignal) -> List[Transition]:
        """Find K-nearest similar transitions"""
        scored = []
        
        for transition in self._transitions:
            # Only consider transitions with same action and player signal
            if transition.npc_action != action or transition.player_signal != player_signal:
                continue
            
            # Calculate distance
            distance = state.distance_to(transition.state_before)
            scored.append((distance, transition))
        
        # Sort by distance and take K nearest
        scored.sort(key=lambda x: x[0])
        return [t for _, t in scored[:self.k_neighbors]]
    
    def _aggregate_predictions(self, transitions: List[Transition]) -> StateSnapshot:
        """Aggregate predictions from similar transitions"""
        if len(transitions) == 0:
            raise ValueError("Cannot aggregate empty transitions")
        
        # Average numeric fields
        avg_affinity = sum(t.state_after.affinity for t in transitions) / len(transitions)
        avg_sentiment = sum(t.state_after.recent_sentiment for t in transitions) / len(transitions)
        avg_trust = sum(t.state_after.trust_level for t in transitions) / len(transitions)
        avg_fear = sum(t.state_after.fear_level for t in transitions) / len(transitions)
        
        # Majority vote for categorical fields
        from collections import Counter
        mood_counter = Counter(t.state_after.mood for t in transitions)
        rel_counter = Counter(t.state_after.relationship for t in transitions)
        
        combat_active = any(t.state_after.combat_active for t in transitions)
        quest_active = any(t.state_after.quest_active for t in transitions)
        
        return StateSnapshot(
            mood=mood_counter.most_common(1)[0][0],
            affinity=avg_affinity,
            relationship=rel_counter.most_common(1)[0][0],
            recent_sentiment=avg_sentiment,
            combat_active=combat_active,
            quest_active=quest_active,
            trust_level=avg_trust,
            fear_level=avg_fear
        )


class WorldModel:
    """
    Main world model combining hand-authored rules and retrieval-based prediction.
    Predicts state transitions from actions: S + A + player_signal → S'
    """
    
    def __init__(self, retrieval_k: int = 5, 
                 transitions_path: Optional[Path] = None):
        """
        Initialize world model
        
        Args:
            retrieval_k: Number of neighbors for retrieval
            transitions_path: Path to load transitions from
        """
        self.hand_authored = HandAuthoredRules()
        self.retrieval = RetrievalWorldModel(k_neighbors=retrieval_k)
        
        if transitions_path:
            self.retrieval.load_from_file(transitions_path)
        
        logger.info("WorldModel initialized")
    
    def predict(self, state: StateSnapshot, action: NPCAction,
                player_signal: PlayerSignal) -> StateSnapshot:
        """
        Predict next state
        
        Args:
            state: Current state
            action: NPC action
            player_signal: Player signal
            
        Returns:
            Predicted next state
        """
        # Try hand-authored rules first (for hard physics)
        predicted = self.hand_authored.predict(state, action, player_signal)
        
        if predicted is not None:
            logger.debug(f"Used hand-authored rule for {action.value}")
            return predicted
        
        # Fall back to retrieval-based prediction
        predicted = self.retrieval.predict(state, action, player_signal)
        
        if predicted is not None:
            logger.debug(f"Used retrieval prediction for {action.value}")
            return predicted
        
        # No prediction available - return state unchanged
        logger.warning(f"No prediction available for {action.value}")
        return state
    
    def record_transition(self, state_before: StateSnapshot, action: NPCAction,
                         player_signal: PlayerSignal, state_after: StateSnapshot,
                         reward: float = 0.0):
        """
        Record a transition for learning
        
        Args:
            state_before: State before action
            action: NPC action taken
            player_signal: Player signal received
            state_after: State after action
            reward: Reward received
        """
        import time
        transition = Transition(
            state_before=state_before,
            npc_action=action,
            player_signal=player_signal,
            state_after=state_after,
            reward=reward,
            timestamp=time.time()
        )
        
        self.retrieval.add_transition(transition)
        logger.debug(f"Recorded transition: {action.value}")
    
    def save_transitions(self, path: Path):
        """Save learned transitions"""
        self.retrieval.save_to_file(path)
    
    def get_transition_count(self) -> int:
        """Get number of recorded transitions"""
        return len(self.retrieval._transitions)
