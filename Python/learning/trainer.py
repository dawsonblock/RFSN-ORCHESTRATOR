"""
Trainer: Online learning with gradient updates and persistence
"""
import os
import tempfile
import numpy as np
import json
from pathlib import Path
from typing import Optional
from .schemas import FeatureVector, ActionMode, TurnLog
import logging

logger = logging.getLogger(__name__)


def atomic_write_json(path: str, obj: dict) -> None:
    """Write JSON atomically to prevent corruption on crash"""
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp_policy_", dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        # Clean up temp file on failure
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass
        raise


class Trainer:
    """
    Online trainer for policy weights
    Uses simple gradient ascent on linear model
    
    Includes stability controls:
    - Feature clipping to [-5, 5]
    - Reward clipping to [-2, 2]
    - Weight decay (0.999 per update)
    - Weight magnitude capping to [-10, 10]
    """
    
    # Stability constants
    FEATURE_CLIP = 5.0
    REWARD_CLIP = 2.0
    WEIGHT_DECAY = 0.999
    WEIGHT_CAP = 10.0
    
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
        Update policy weights using gradient ascent with stability controls
        
        Args:
            weights: Current weight matrix (n_actions, n_features)
            features: Feature vector for this turn
            action: Action that was taken
            reward: Observed reward
            
        Returns:
            Updated weights
        """
        # Convert and clip features (Patch 4.1)
        x = np.array(features.to_array(), dtype=np.float32)
        x = np.clip(x, -self.FEATURE_CLIP, self.FEATURE_CLIP)
        
        # Clip reward at trainer boundary (Patch 4.2)
        reward = float(np.clip(reward, -self.REWARD_CLIP, self.REWARD_CLIP))
        
        a = action.value
        
        # Apply weight decay to the updated row (Patch 4.3)
        weights[a] *= self.WEIGHT_DECAY
        
        # Gradient for linear model: ∇w = r * x
        # Update only the weights for the action that was taken
        gradient = reward * x
        weights[a] += self.learning_rate * gradient
        
        # Cap weight magnitude (Patch 4.4) - prevents softmax saturation and mode lock
        weights = np.clip(weights, -self.WEIGHT_CAP, self.WEIGHT_CAP)
        
        # Decay learning rate
        self.learning_rate *= self.decay_rate
        self.update_count += 1
        
        if self.update_count % 100 == 0:
            logger.info(f"Update {self.update_count}: LR={self.learning_rate:.4f}, max_w={np.abs(weights).max():.2f}")
        
        return weights
    
    def save_weights(self, weights: np.ndarray, path: Path) -> None:
        """
        Save policy weights atomically (Patch 6)
        
        Args:
            weights: Weight matrix to save
            path: Path to save to
        """
        data = {
            "weights": weights.tolist(),
            "update_count": self.update_count,
            "learning_rate": self.learning_rate
        }
        atomic_write_json(str(path), data)
        logger.debug(f"Saved weights atomically to {path}")
    
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

