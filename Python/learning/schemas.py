"""
Type definitions for learning layer
"""
from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, Any, Optional
from datetime import datetime


class ActionMode(Enum):
    """Discrete behavior policies for NPC dialogue"""
    TERSE_DIRECT = 0      # Short, instructional, low emotion
    WARM_SUPPORTIVE = 1   # Empathy, reassurance, emotional support
    LORE_EXPLAINER = 2    # Longer responses, world-building focus
    CLARIFY_FIRST = 3     # Ask questions before answering
    EVIDENCE_CITE = 4     # Force memory citations, avoid invention
    DEESCALATE = 5        # Conflict reduction, calm tone
    
    @property
    def prompt_injection(self) -> str:
        """Get prompt control block for this action mode"""
        injections = {
            ActionMode.TERSE_DIRECT: """[ACTION MODE: TERSE_DIRECT]
- Keep responses to 3-4 sentences
- Be direct and clear
- Focus on facts and actions
- Answer the question fully""",
            
            ActionMode.WARM_SUPPORTIVE: """[ACTION MODE: WARM_SUPPORTIVE]
- Show empathy and understanding
- Offer reassurance when appropriate
- Use warmer, more personal tone
- Acknowledge feelings""",
            
            ActionMode.LORE_EXPLAINER: """[ACTION MODE: LORE_EXPLAINER]
- Provide detailed world-building context
- Share relevant lore and history
- Use descriptive, immersive language
- Connect to broader narrative""",
            
            ActionMode.CLARIFY_FIRST: """[ACTION MODE: CLARIFY_FIRST]
- Ask 1-2 clarifying questions if info is missing
- Don't make assumptions about intent
- Confirm understanding before answering
- Be brief in your questions""",
            
            ActionMode.EVIDENCE_CITE: """[ACTION MODE: EVIDENCE_CITE]
- Use retrieved memory snippets in your response
- If no relevant memories, say "I don't recall"
- Cite specific events when possible
- Avoid inventing facts""",
            
            ActionMode.DEESCALATE: """[ACTION MODE: DEESCALATE]
- Reduce tension and conflict
- Acknowledge concerns calmly
- Redirect to neutral topics
- Avoid accusations or blame"""
        }
        return injections[self]


@dataclass
class FeatureVector:
    """Features extracted from current state for policy decision"""
    npc_id_hash: int                    # Hash bucket of NPC name
    affinity: float                     # Relationship affinity score
    mood: int                           # Mood category (0-5)
    relationship: int                   # Relationship type (0-5)
    player_playstyle: int              # Playstyle category (0-3)
    recent_sentiment: float            # Sentiment of recent turns
    retrieval_topk_mean_sim: float     # Mean similarity of retrieved memories
    retrieval_contradiction_flag: int  # 1 if contradiction detected, 0 otherwise
    turn_index_in_convo: int           # Current turn number
    last_action_mode: int              # Previous action mode ID
    
    def to_array(self) -> list:
        """Convert to numerical array for linear model"""
        return [
            self.npc_id_hash,
            self.affinity,
            self.mood,
            self.relationship,
            self.player_playstyle,
            self.recent_sentiment,
            self.retrieval_topk_mean_sim,
            self.retrieval_contradiction_flag,
            self.turn_index_in_convo,
            self.last_action_mode
        ]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging"""
        return {
            "npc_id_hash": self.npc_id_hash,
            "affinity": self.affinity,
            "mood": self.mood,
            "relationship": self.relationship,
            "player_playstyle": self.player_playstyle,
            "recent_sentiment": self.recent_sentiment,
            "retrieval_topk_mean_sim": self.retrieval_topk_mean_sim,
            "retrieval_contradiction_flag": self.retrieval_contradiction_flag,
            "turn_index_in_convo": self.turn_index_in_convo,
            "last_action_mode": self.last_action_mode
        }


@dataclass
class RewardSignals:
    """Observable signals used to compute reward"""
    contradiction_detected: bool = False
    user_correction: bool = False
    tts_overrun: bool = False
    conversation_continued: bool = False
    follow_up_question: bool = False
    
    def to_dict(self) -> Dict[str, bool]:
        """Convert to dictionary for logging"""
        return {
            "contradiction": self.contradiction_detected,
            "user_correction": self.user_correction,
            "tts_overrun": self.tts_overrun,
            "continued": self.conversation_continued,
            "follow_up": self.follow_up_question
        }


@dataclass
class TurnLog:
    """Complete log entry for one dialogue turn"""
    timestamp: str
    npc_id: str
    features: Dict[str, Any]
    action_mode: str
    reward: float
    signals: Dict[str, bool]
    
    @classmethod
    def create(cls, npc_id: str, features: FeatureVector, 
               action_mode: ActionMode, reward: float, 
               signals: RewardSignals) -> 'TurnLog':
        """Create a turn log from components"""
        return cls(
            timestamp=datetime.utcnow().isoformat() + "Z",
            npc_id=npc_id,
            features=features.to_dict(),
            action_mode=action_mode.name,
            reward=reward,
            signals=signals.to_dict()
        )
