"""
Drop-in Bandit Core Module for RFSN Orchestrator.

Provides a unified interface for multiple bandit strategies:
- Thompson Beta (Thompson Sampling with Beta priors)
- Softmax (Boltzmann exploration)
- UCB1 (Upper Confidence Bound)

Supports:
- Per-(key, action) arms
- Persistence to JSON
- Deterministic seeding for reproducibility
- Prior blending from action scorer
"""
from __future__ import annotations

import json
import math
import random
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Any


@dataclass
class ArmStats:
    """Statistics for a single bandit arm."""
    alpha: float = 1.0  # Beta distribution alpha (successes + 1)
    beta: float = 1.0   # Beta distribution beta (failures + 1)
    n: int = 0          # Number of trials
    total_reward: float = 0.0  # Sum of rewards
    
    def mean(self) -> float:
        """Empirical mean reward."""
        if self.n == 0:
            return 0.5
        return self.total_reward / self.n


class BanditStrategy(ABC):
    """Abstract base class for bandit selection strategies."""
    
    @abstractmethod
    def select(
        self,
        candidates: List[str],
        arms: Dict[str, ArmStats],
        priors: Optional[Dict[str, float]] = None,
        explore_bias: float = 0.0
    ) -> str:
        """Select an action from candidates given arm statistics."""
        pass
    
    @abstractmethod
    def update(self, arm: ArmStats, reward: float) -> None:
        """Update arm statistics with new reward."""
        pass


class ThompsonBetaStrategy(BanditStrategy):
    """Thompson Sampling with Beta distributions."""
    
    def __init__(self, min_trials_before_exploit: int = 3):
        self.min_trials_before_exploit = min_trials_before_exploit
    
    def select(
        self,
        candidates: List[str],
        arms: Dict[str, ArmStats],
        priors: Optional[Dict[str, float]] = None,
        explore_bias: float = 0.0
    ) -> str:
        """Select using Thompson Sampling."""
        if not candidates:
            raise ValueError("No candidates provided")
        
        # Early exploration
        if random.random() < explore_bias:
            return random.choice(candidates)
        
        best_action = None
        best_score = -1e9
        
        for action in candidates:
            arm = arms.get(action, ArmStats())
            
            # Thompson sample from Beta distribution
            sample = random.betavariate(arm.alpha, arm.beta)
            
            # Weak prior blending (normalized to small bump)
            bump = 0.0
            if priors and action in priors:
                # Scale prior into range [-0.05, 0.05]
                bump = max(-0.05, min(0.05, priors[action] / 20.0))
            
            # Cold start penalty to encourage exploration
            cold_start_penalty = 0.0
            if arm.n < self.min_trials_before_exploit:
                cold_start_penalty = -0.03 * (self.min_trials_before_exploit - arm.n)
            
            score = sample + bump + cold_start_penalty
            
            if score > best_score:
                best_score = score
                best_action = action
        
        return best_action or candidates[0]
    
    def update(self, arm: ArmStats, reward: float) -> None:
        """Update Beta parameters."""
        r = max(0.0, min(1.0, reward))  # Clamp to [0, 1]
        arm.alpha += r
        arm.beta += (1.0 - r)
        arm.n += 1
        arm.total_reward += r


class SoftmaxStrategy(BanditStrategy):
    """Softmax (Boltzmann) exploration strategy."""
    
    def __init__(self, temperature: float = 0.1):
        self.temperature = temperature
    
    def select(
        self,
        candidates: List[str],
        arms: Dict[str, ArmStats],
        priors: Optional[Dict[str, float]] = None,
        explore_bias: float = 0.0
    ) -> str:
        """Select using softmax probabilities."""
        if not candidates:
            raise ValueError("No candidates provided")
        
        # Early exploration
        if random.random() < explore_bias:
            return random.choice(candidates)
        
        # Compute softmax probabilities
        scores = []
        for action in candidates:
            arm = arms.get(action, ArmStats())
            
            # Base score is empirical mean
            score = arm.mean()
            
            # Add prior if available
            if priors and action in priors:
                score += max(-0.05, min(0.05, priors[action] / 20.0))
            
            scores.append(score)
        
        # Apply softmax
        if self.temperature > 0:
            exp_scores = [math.exp(s / self.temperature) for s in scores]
        else:
            # Greedy selection if temperature is 0
            max_idx = scores.index(max(scores))
            return candidates[max_idx]
        
        total = sum(exp_scores)
        probs = [e / total for e in exp_scores]
        
        # Sample from distribution
        r = random.random()
        cumsum = 0.0
        for i, prob in enumerate(probs):
            cumsum += prob
            if r <= cumsum:
                return candidates[i]
        
        return candidates[-1]  # Fallback
    
    def update(self, arm: ArmStats, reward: float) -> None:
        """Update empirical mean."""
        r = max(0.0, min(1.0, reward))
        arm.n += 1
        arm.total_reward += r


class UCB1Strategy(BanditStrategy):
    """Upper Confidence Bound (UCB1) strategy."""
    
    def __init__(self, c: float = 2.0):
        self.c = c  # Exploration constant
    
    def select(
        self,
        candidates: List[str],
        arms: Dict[str, ArmStats],
        priors: Optional[Dict[str, float]] = None,
        explore_bias: float = 0.0
    ) -> str:
        """Select using UCB1."""
        if not candidates:
            raise ValueError("No candidates provided")
        
        # Early exploration
        if random.random() < explore_bias:
            return random.choice(candidates)
        
        # Total trials across all arms
        total_trials = sum(arms.get(a, ArmStats()).n for a in candidates)
        
        # Force exploration of unplayed arms
        for action in candidates:
            arm = arms.get(action, ArmStats())
            if arm.n == 0:
                return action
        
        best_action = None
        best_ucb = -1e9
        
        for action in candidates:
            arm = arms.get(action, ArmStats())
            
            # UCB1 formula: mean + c * sqrt(ln(total) / n)
            mean_reward = arm.mean()
            if total_trials > 0 and arm.n > 0:
                exploration_bonus = self.c * math.sqrt(math.log(total_trials) / arm.n)
            else:
                exploration_bonus = 0.0
            
            # Add prior if available
            prior_bonus = 0.0
            if priors and action in priors:
                prior_bonus = max(-0.05, min(0.05, priors[action] / 20.0))
            
            ucb = mean_reward + exploration_bonus + prior_bonus
            
            if ucb > best_ucb:
                best_ucb = ucb
                best_action = action
        
        return best_action or candidates[0]
    
    def update(self, arm: ArmStats, reward: float) -> None:
        """Update empirical mean."""
        r = max(0.0, min(1.0, reward))
        arm.n += 1
        arm.total_reward += r


class BanditCore:
    """
    Drop-in bandit learner with swappable strategies.
    
    Supports:
    - Multiple strategies (thompson_beta, softmax, ucb1)
    - Per-(key, action) arms
    - Persistence to JSON
    - Deterministic seeding
    """
    
    def __init__(
        self,
        strategy: str = "thompson_beta",
        path: Optional[Path] = None,
        seed: Optional[int] = None,
        strategy_params: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize BanditCore.
        
        Args:
            strategy: One of "thompson_beta", "softmax", "ucb1"
            path: Path to persistence file
            seed: Random seed for deterministic behavior
            strategy_params: Optional parameters for the strategy
        """
        self.strategy_name = strategy
        self.path = path or Path("data/learning/bandit_core.json")
        self.seed = seed
        
        if seed is not None:
            random.seed(seed)
        
        # Initialize strategy
        strategy_params = strategy_params or {}
        if strategy == "thompson_beta":
            self.strategy = ThompsonBetaStrategy(**strategy_params)
        elif strategy == "softmax":
            self.strategy = SoftmaxStrategy(**strategy_params)
        elif strategy == "ucb1":
            self.strategy = UCB1Strategy(**strategy_params)
        else:
            raise ValueError(f"Unknown strategy: {strategy}")
        
        # Storage: key -> action -> ArmStats
        self._arms: Dict[str, Dict[str, ArmStats]] = {}
        
        self.load()
    
    def select(
        self,
        key: str,
        candidates: List[str],
        priors: Optional[Dict[str, float]] = None,
        explore_bias: Optional[float] = None
    ) -> str:
        """
        Select an action from candidates for the given context key.
        
        Args:
            key: Context key (e.g., bandit state bucket)
            candidates: List of candidate actions
            priors: Optional prior scores from action scorer
            explore_bias: Optional exploration probability (overrides default)
            
        Returns:
            Selected action (one of the candidates)
        """
        if not candidates:
            raise ValueError("No candidates provided")
        
        if key not in self._arms:
            self._arms[key] = {}
        
        # Get arm stats for candidates
        arms = {}
        for action in candidates:
            if action not in self._arms[key]:
                self._arms[key][action] = ArmStats()
            arms[action] = self._arms[key][action]
        
        # Use default explore_bias if not provided
        if explore_bias is None:
            explore_bias = 0.1 if self.strategy_name == "thompson_beta" else 0.0
        
        return self.strategy.select(candidates, arms, priors, explore_bias)
    
    def update(self, key: str, action: str, reward_01: float) -> None:
        """
        Update arm statistics with observed reward.
        
        Args:
            key: Context key
            action: Action taken
            reward_01: Reward in [0, 1]
        """
        if key not in self._arms:
            self._arms[key] = {}
        if action not in self._arms[key]:
            self._arms[key][action] = ArmStats()
        
        arm = self._arms[key][action]
        self.strategy.update(arm, reward_01)
    
    def save(self) -> None:
        """Persist bandit state to JSON (atomic write)."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        
        # Convert to serializable format
        data = {
            "strategy": self.strategy_name,
            "seed": self.seed,
            "arms": {}
        }
        
        for key, actions in self._arms.items():
            data["arms"][key] = {}
            for action, stats in actions.items():
                data["arms"][key][action] = {
                    "alpha": stats.alpha,
                    "beta": stats.beta,
                    "n": stats.n,
                    "total_reward": stats.total_reward
                }
        
        # Atomic write
        tmp_path = self.path.with_suffix(".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
        tmp_path.replace(self.path)
    
    def load(self) -> None:
        """Load bandit state from JSON."""
        if not self.path.exists():
            return
        
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            # Restore arms
            arms_data = data.get("arms", {})
            for key, actions in arms_data.items():
                self._arms[key] = {}
                for action, stats_dict in actions.items():
                    self._arms[key][action] = ArmStats(
                        alpha=stats_dict.get("alpha", 1.0),
                        beta=stats_dict.get("beta", 1.0),
                        n=stats_dict.get("n", 0),
                        total_reward=stats_dict.get("total_reward", 0.0)
                    )
        except Exception as e:
            print(f"Warning: Failed to load bandit data from {self.path}: {e}")
            self._arms = {}
    
    def reset(self, key: Optional[str] = None) -> None:
        """
        Reset bandit state.
        
        Args:
            key: If provided, reset only this key. Otherwise reset all.
        """
        if key is None:
            self._arms = {}
        elif key in self._arms:
            del self._arms[key]
    
    def get_stats(self, key: str, action: str) -> Optional[ArmStats]:
        """Get statistics for a specific (key, action) pair."""
        if key in self._arms and action in self._arms[key]:
            return self._arms[key][action]
        return None
