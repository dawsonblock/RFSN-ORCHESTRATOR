"""
Policy Adapter: Feature extraction and action selection
Uses epsilon-greedy contextual bandit with softmax linear model
"""
import hashlib
import numpy as np
import json
from pathlib import Path
from typing import Dict, Any, Optional
from .schemas import ActionMode, FeatureVector
import logging

logger = logging.getLogger(__name__)


def stable_bucket_id(text: str, buckets: int = 256) -> int:
    """Compute a stable bucket ID using SHA1 (consistent across processes/restarts)"""
    h = hashlib.sha1(text.encode("utf-8")).digest()
    return int.from_bytes(h[:2], "big") % buckets


class PolicyAdapter:
    """
    Chooses action modes based on current state features
    Uses epsilon-greedy exploration with softmax action probabilities
    """
    
    def __init__(self, epsilon: float = 0.08, weights_path: Optional[Path] = None):
        """
        Initialize policy adapter
        
        Args:
            epsilon: Exploration rate (default 8%)
            weights_path: Path to load/save weights
        """
        self.epsilon = epsilon
        self.n_actions = len(ActionMode)
        self.n_features = 10
        
        # Initialize weights: shape (n_actions, n_features)
        self.weights = np.zeros((self.n_actions, self.n_features))
        
        # Track last action for feature extraction
        self.last_action_mode = ActionMode.TERSE_DIRECT
        
        # Load weights if path provided
        self.weights_path = weights_path or Path("data/policy/policy_weights.json")
        if self.weights_path.exists():
            self.load_weights()
    
    def build_features(self, rfsn_state: Dict[str, Any], 
                      retrieval_stats: Dict[str, Any],
                      convo_stats: Dict[str, Any]) -> FeatureVector:
        """
        Extract feature vector from current state
        
        Args:
            rfsn_state: RFSN state dict with affinity, mood, relationship, etc.
            retrieval_stats: Memory retrieval statistics
            convo_stats: Conversation statistics
            
        Returns:
            FeatureVector with 10 features
        """
        # Stable bucket for NPC identity (SHA1-based, consistent across restarts)
        npc_name = rfsn_state.get("npc_name", "unknown")
        npc_bucket = stable_bucket_id(npc_name or "unknown", buckets=256)
        # Normalize bucket to 0-1 range
        npc_id_normalized = npc_bucket / 256.0
        
        # Extract RFSN state features
        # Patch 3: affinity is actually [-1, 1], map to [0, 1] for policy
        raw_affinity = float(rfsn_state.get("affinity", 0.0))
        # Clamp to [-1, 1] then map to [0, 1]
        clamped = max(-1.0, min(1.0, raw_affinity))
        affinity = (clamped + 1.0) / 2.0  # Now 0-1
        
        # Normalize categorical features to 0-1 range
        mood_int = self._mood_to_int(rfsn_state.get("mood", "neutral"))
        mood_normalized = mood_int / 5.0  # 6 moods (0-5)
        
        relationship_int = self._relationship_to_int(rfsn_state.get("relationship", "stranger"))
        relationship_normalized = relationship_int / 5.0  # 6 relationships (0-5)
        
        playstyle_int = self._playstyle_to_int(rfsn_state.get("playstyle", "balanced"))
        playstyle_normalized = playstyle_int / 3.0  # 4 playstyles (0-3)
        
        # Recent sentiment (already -1 to 1, keep as-is)
        recent_sentiment = float(rfsn_state.get("recent_sentiment", 0.0))
        
        # Retrieval statistics (already 0-1)
        retrieval_scores = retrieval_stats.get("top_k_scores", [])
        retrieval_topk_mean_sim = float(np.mean(retrieval_scores)) if retrieval_scores else 0.0
        retrieval_contradiction_flag = int(retrieval_stats.get("contradiction_detected", False))
        
        # Conversation statistics - cap at 50, normalize to 0-1
        raw_turn_count = int(convo_stats.get("turn_count", 0))
        turn_index_normalized = min(raw_turn_count, 50) / 50.0
        
        # Last action mode - normalize to 0-1
        last_action_normalized = self.last_action_mode.value / max(1, self.n_actions - 1)
        
        return FeatureVector(
            npc_id_hash=npc_id_normalized,
            affinity=affinity,
            mood=mood_normalized,
            relationship=relationship_normalized,
            player_playstyle=playstyle_normalized,
            recent_sentiment=recent_sentiment,
            retrieval_topk_mean_sim=retrieval_topk_mean_sim,
            retrieval_contradiction_flag=retrieval_contradiction_flag,
            turn_index_in_convo=turn_index_normalized,
            last_action_mode=last_action_normalized
        )
    
    def choose_action_mode(self, features: FeatureVector) -> ActionMode:
        """
        Select action mode using epsilon-greedy policy
        
        Args:
            features: Current feature vector
            
        Returns:
            Selected ActionMode
        """
        # Epsilon-greedy exploration
        if np.random.random() < self.epsilon:
            # Explore: random action
            action_id = np.random.randint(0, self.n_actions)
        else:
            # Exploit: choose best action based on current weights
            action_id = self._select_best_action(features)
        
        action_mode = ActionMode(action_id)
        self.last_action_mode = action_mode
        
        logger.info(f"Selected action mode: {action_mode.name}")
        return action_mode
    
    def _select_best_action(self, features: FeatureVector) -> int:
        """
        Select action with highest score using softmax
        
        Args:
            features: Feature vector
            
        Returns:
            Action ID
        """
        x = np.array(features.to_array())
        
        # Compute scores for each action: score = w_a · x
        scores = self.weights @ x
        
        # Softmax to get probabilities
        exp_scores = np.exp(scores - np.max(scores))  # Numerical stability
        probs = exp_scores / np.sum(exp_scores)
        
        # Sample from distribution (or take argmax for greedy)
        action_id = np.argmax(probs)
        
        return int(action_id)
    
    def get_action_probabilities(self, features: FeatureVector) -> np.ndarray:
        """Get probability distribution over actions for given features"""
        x = np.array(features.to_array())
        scores = self.weights @ x
        exp_scores = np.exp(scores - np.max(scores))
        probs = exp_scores / np.sum(exp_scores)
        return probs
    
    def load_weights(self):
        """Load weights from JSON file"""
        try:
            with open(self.weights_path, 'r') as f:
                data = json.load(f)
                self.weights = np.array(data['weights'])
                logger.info(f"Loaded policy weights from {self.weights_path}")
        except Exception as e:
            logger.warning(f"Could not load weights: {e}. Using zero initialization.")
    
    def save_weights(self):
        """Save weights to JSON file"""
        try:
            self.weights_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.weights_path, 'w') as f:
                json.dump({
                    'weights': self.weights.tolist(),
                    'epsilon': self.epsilon,
                    'n_actions': self.n_actions,
                    'n_features': self.n_features
                }, f, indent=2)
            logger.info(f"Saved policy weights to {self.weights_path}")
        except Exception as e:
            logger.error(f"Could not save weights: {e}")
    
    # Helper functions for categorical encoding
    @staticmethod
    def _mood_to_int(mood: str) -> int:
        """Convert mood string to integer category"""
        mood_map = {
            "happy": 0, "neutral": 1, "sad": 2,
            "angry": 3, "fearful": 4, "surprised": 5
        }
        return mood_map.get(mood.lower(), 1)  # Default to neutral
    
    @staticmethod
    def _relationship_to_int(relationship: str) -> int:
        """Convert relationship string to integer category"""
        rel_map = {
            "stranger": 0, "acquaintance": 1, "friend": 2,
            "ally": 3, "enemy": 4, "rival": 5
        }
        return rel_map.get(relationship.lower(), 0)  # Default to stranger
    
    @staticmethod
    def _playstyle_to_int(playstyle: str) -> int:
        """Convert playstyle string to integer category"""
        style_map = {
            "aggressive": 0, "diplomatic": 1,
            "stealthy": 2, "balanced": 3
        }
        return style_map.get(playstyle.lower(), 3)  # Default to balanced
