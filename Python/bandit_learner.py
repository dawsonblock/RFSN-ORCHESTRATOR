# bandit_learner.py
"""
Per-state bounded bandit learner for RFSN action selection.

This module provides Thompson sampling and UCB1 algorithms for selecting
actions in a multi-armed bandit setting, with per-state isolation and
JSON persistence. Designed for RFSN to learn optimal action selection
while maintaining safety constraints.
"""
from __future__ import annotations

import json
import math
import os
import random
import time
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional


@dataclass
class ArmStats:
    """Statistics for a single bandit arm (action).
    
    Attributes:
        n: Number of times this arm has been pulled
        value_sum: Sum of all rewards (for computing mean)
        a: Thompson sampling alpha parameter (successes + 1)
        b: Thompson sampling beta parameter (failures + 1)
        last_update_ts: Timestamp of last update
    """
    n: int = 0
    value_sum: float = 0.0      # for UCB / mean
    a: float = 1.0              # Thompson alpha (success + 1)
    b: float = 1.0              # Thompson beta  (failure + 1)
    last_update_ts: float = 0.0

    def mean(self) -> float:
        """Compute the mean reward for this arm."""
        return self.value_sum / self.n if self.n > 0 else 0.0


@dataclass
class BanditConfig:
    """Configuration for the bandit learner.
    
    Attributes:
        mode: Selection algorithm ("thompson" or "ucb")
        epsilon: Probability of random exploration
        min_trials_before_exploit: Minimum trials before exploiting
        reward_min: Minimum expected reward value
        reward_max: Maximum expected reward value
        thompson_binary: If True, reward>0 is success, else failure
        ucb_c: UCB exploration constant (higher = more exploration)
        banned_actions: List of actions that should never be selected
    """
    mode: str = "thompson"      # "thompson" or "ucb"
    epsilon: float = 0.02       # exploration fallback
    min_trials_before_exploit: int = 3
    reward_min: float = -1.0
    reward_max: float = 1.0
    thompson_binary: bool = False  # if True, reward>0 counts as success else failure
    ucb_c: float = 2.0          # exploration strength
    banned_actions: Optional[List[str]] = None


class StateActionBandit:
    """
    Per-state action selection with bounded learning.
    Designed for RFSN: key is a discrete state_id string.

    Reward expectations:
      - If thompson_binary=False: reward is continuous but still used to update mean;
        Thompson updates use a heuristic mapping unless you set binary=True.
      - If thompson_binary=True: reward>0 => success, else failure (recommended).
      
    Example usage:
        >>> config = BanditConfig(mode="thompson", thompson_binary=True)
        >>> bandit = StateActionBandit("data/bandit_state.json", config)
        >>> 
        >>> # Select an action
        >>> action = bandit.select_action("FRIENDLY", ["GREET", "HELP", "EXPLAIN"])
        >>> 
        >>> # Execute action and get reward
        >>> reward = 0.8  # player engaged positively
        >>> bandit.update("FRIENDLY", action, reward)
    """

    def __init__(self, storage_path: str, config: Optional[BanditConfig] = None):
        """Initialize the bandit learner.
        
        Args:
            storage_path: Path to JSON file for persistence
            config: Configuration object (uses defaults if None)
        """
        self.storage_path = storage_path
        self.cfg = config or BanditConfig()
        mode = self.cfg.mode.lower()
        if mode not in ("thompson", "ucb"):
            raise ValueError(f"Unsupported mode: {self.cfg.mode}")
        self.cfg.mode = mode
        self._db: Dict[str, Dict[str, ArmStats]] = {}
        self._load()

    # ---------- public API ----------

    def select_action(
        self,
        state_id: str,
        candidate_actions: List[str],
        rng_seed: Optional[int] = None,
    ) -> str:
        """Select an action for the given state.
        
        Uses the configured selection strategy (Thompson sampling or UCB1)
        with epsilon-greedy exploration.
        
        Args:
            state_id: Current state identifier (e.g., "FRIENDLY", "ALERT")
            candidate_actions: List of valid actions for this state
            rng_seed: Optional random seed for reproducibility
            
        Returns:
            Selected action ID
            
        Raises:
            ValueError: If candidate_actions is empty
        """
        if not candidate_actions:
            raise ValueError("candidate_actions cannot be empty")
            
        if rng_seed is not None:
            random.seed(rng_seed)

        banned = set(self.cfg.banned_actions or [])
        actions = [a for a in candidate_actions if a not in banned]
        if not actions:
            # If all candidate actions are banned, there are no valid choices.
            raise ValueError("All candidate actions are banned.")

        # Ensure stats exist
        st = self._db.setdefault(state_id, {})
        for a in actions:
            st.setdefault(a, ArmStats())

        # Epsilon exploration
        if random.random() < self.cfg.epsilon:
            return random.choice(actions)

        # If not enough trials overall, explore more uniformly
        if self._total_trials(state_id, actions) < self.cfg.min_trials_before_exploit * len(actions):
            # pick the least-tried action to seed coverage
            return min(actions, key=lambda a: st[a].n)

        if self.cfg.mode.lower() == "ucb":
            return self._select_ucb(state_id, actions)
        return self._select_thompson(state_id, actions)

    def update(
        self,
        state_id: str,
        action_id: str,
        reward: float,
        ts: Optional[float] = None,
    ) -> None:
        """Update statistics for a state-action pair.
        
        Args:
            state_id: State identifier
            action_id: Action that was taken
            reward: Observed reward (will be clamped to [reward_min, reward_max])
            ts: Optional timestamp (uses current time if None)
        """
        ts = ts if ts is not None else time.time()
        reward = self._clamp(reward, self.cfg.reward_min, self.cfg.reward_max)

        st = self._db.setdefault(state_id, {})
        arm = st.setdefault(action_id, ArmStats())

        arm.n += 1
        arm.value_sum += reward
        arm.last_update_ts = ts

        # Thompson update
        if self.cfg.mode.lower() == "thompson":
            if self.cfg.thompson_binary:
                if reward > 0:
                    arm.a += 1.0
                else:
                    arm.b += 1.0
            else:
                # Map bounded reward [-1,1] -> pseudo success probability [0,1]
                p = (reward - self.cfg.reward_min) / (self.cfg.reward_max - self.cfg.reward_min)
                # Soft update: add fractional evidence
                arm.a += p
                arm.b += (1.0 - p)

    def reset_state(self, state_id: str) -> None:
        """Reset all statistics for a given state.
    
        Args:
            state_id: State to reset
        """
        if state_id in self._db:
            del self._db[state_id]

    def snapshot(self) -> Dict[str, Dict[str, dict]]:
        """Get a snapshot of all current statistics.
        
        Returns:
            Nested dictionary of {state_id: {action_id: stats_dict}}
        """
        return {
            s: {a: asdict(stats) for a, stats in acts.items()}
            for s, acts in self._db.items()
        }

    # ---------- selection strategies ----------

    def _select_thompson(self, state_id: str, actions: List[str]) -> str:
        """Thompson sampling: sample from Beta distributions and choose max.
        
        Args:
            state_id: Current state
            actions: Valid actions to choose from
            
        Returns:
            Selected action
        """
        st = self._db[state_id]
        # sample from Beta(a,b), choose max
        best_a = actions[0]
        best_sample = -1.0
        for a in actions:
            arm = st[a]
            sample = random.betavariate(max(arm.a, 1e-6), max(arm.b, 1e-6))
            # tie-break with mean
            if sample > best_sample or (sample == best_sample and arm.mean() > st[best_a].mean()):
                best_sample = sample
                best_a = a
        return best_a

    def _select_ucb(self, state_id: str, actions: List[str]) -> str:
        """UCB1: compute upper confidence bounds and choose max.
        
        Args:
            state_id: Current state
            actions: Valid actions to choose from
            
        Returns:
            Selected action
        """
        st = self._db[state_id]
        total = self._total_trials(state_id, actions)
        if total <= 0:
            return random.choice(actions)

        best_a = actions[0]
        best_score = -1e9
        for a in actions:
            arm = st[a]
            if arm.n == 0:
                return a  # force explore
            bonus = self.cfg.ucb_c * math.sqrt(math.log(total) / arm.n)
            score = arm.mean() + bonus
            if score > best_score:
                best_score = score
                best_a = a
        return best_a

    # ---------- persistence ----------

    def _load(self) -> None:
        """Load statistics from JSON file."""
        if not os.path.exists(self.storage_path):
            self._db = {}
            return
        try:
            with open(self.storage_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            self._db = {}
            for state_id, acts in raw.items():
                self._db[state_id] = {}
                for action_id, stats_dict in acts.items():
                    self._db[state_id][action_id] = ArmStats(**stats_dict)
        except Exception:
            # If corrupted, don't brick runtime; start fresh
            self._db = {}

    def _save(self) -> None:
        """Save statistics to JSON file with atomic write."""
        os.makedirs(os.path.dirname(self.storage_path) or ".", exist_ok=True)
        tmp_path = self.storage_path + ".tmp"
        payload = self.snapshot()
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, sort_keys=True)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self.storage_path)
        except OSError:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except OSError:
                pass

    def _total_trials(self, state_id: str, actions: List[str]) -> int:
        """Compute total number of trials across all actions in a state.
    
        Args:
            state_id: State to count trials for
            actions: Actions to include in count
        
        Returns:
            Total trial count
        """
        st = self._db.get(state_id, {})
        return sum(st.get(a, ArmStats()).n for a in actions)

    @staticmethod
    def _clamp(x: float, lo: float, hi: float) -> float:
        """Clamp a value to a range.
    
        Args:
            x: Value to clamp
            lo: Minimum value
            hi: Maximum value
        
        Returns:
            Clamped value
        """
        return lo if x < lo else hi if x > hi else x
