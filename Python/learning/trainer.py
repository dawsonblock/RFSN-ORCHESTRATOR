"""
Trainer: Online learning with gradient updates and persistence
"""
import numpy as np
import json
from pathlib import Path
from typing import Optional
from .schemas import FeatureVector, ActionMode, TurnLog
import logging

logger = logging.getLogger(__name__)


class Trainer:
    """
    Online trainer for policy weights
    Uses simple gradient ascent on linear model
    """
    
    def __init__(self, learning_rate: float = 0.05, 
                 decay_rate: float = 0.9999,
                 log_path: Optional[Path] = None):
        """
        Initialize trainer
        
        Args:
            learning_rate: Initial learning rate
            decay_rate: LR decay per update
            log_path: Path to save turn logs
        """
        self.learning_rate = learning_rate
        self.initial_lr = learning_rate
        self.decay_rate = decay_rate
        self.update_count = 0
        
        # Logging
        self.log_path = log_path or Path("data/policy/turn_logs.jsonl")
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
    
    def update(self, weights: np.ndarray, features: FeatureVector, 
               action: ActionMode, reward: float) -> np.ndarray:
        """
        Update policy weights using gradient ascent
        
        Args:
            weights: Current weight matrix (n_actions, n_features)
            features: Feature vector for this turn
            action: Action that was taken
            reward: Observed reward
            
        Returns:
            Updated weights
        """
        x = np.array(features.to_array())
        a = action.value
        
        # Gradient for linear model: ∇w = r * x
        # Update only the weights for the action that was taken
        gradient = reward * x
        weights[a] += self.learning_rate * gradient
        
        # Decay learning rate
        self.learning_rate *= self.decay_rate
        self.update_count += 1
        
        if self.update_count % 100 == 0:
            logger.info(f"Update {self.update_count}: LR={self.learning_rate:.4f}")
        
        return weights
    
    def log_turn(self, turn_log: TurnLog):
        """
        Append turn log to JSONL file
        
        Args:
            turn_log: TurnLog to save
        """
        try:
            with open(self.log_path, 'a') as f:
                json.dump(turn_log.__dict__, f)
                f.write('\n')
        except Exception as e:
            logger.error(f"Could not write turn log: {e}")
    
    def reset_learning_rate(self):
        """Reset learning rate to initial value"""
        self.learning_rate = self.initial_lr
        logger.info(f"Reset learning rate to {self.initial_lr}")
    
    def get_stats(self) -> dict:
        """Get training statistics"""
        return {
            "update_count": self.update_count,
            "learning_rate": self.learning_rate,
            "initial_lr": self.initial_lr,
            "decay_rate": self.decay_rate
        }
