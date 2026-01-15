"""
NPC Action Bandit: Thompson Sampling learner for action selection.
Learns which NPCAction to choose per state context bucket.
"""
from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from world_model import NPCAction, PlayerSignal, StateSnapshot


@dataclass(frozen=True)
class BanditKey:
    """
    Coarse bucket so learning generalizes without exploding state space.
    """
    mood: str
    relationship: str
    affinity_band: str
    player_signal: str
    combat: bool
    quest: bool

    @staticmethod
    def _affinity_band(a: float) -> str:
        if a <= -0.6:
            return "very_neg"
        if a <= -0.2:
            return "neg"
        if a < 0.2:
            return "neutral"
        if a < 0.6:
            return "pos"
        return "very_pos"

    @classmethod
    def from_state(cls, s: StateSnapshot, sig: PlayerSignal) -> "BanditKey":
        return cls(
            mood=(s.mood or "neutral").lower(),
            relationship=(s.relationship or "stranger").lower(),
            affinity_band=cls._affinity_band(float(s.affinity)),
            player_signal=sig.value,
            combat=bool(s.combat_active),
            quest=bool(s.quest_active),
        )

    def to_str(self) -> str:
        return "|".join([
            self.mood,
            self.relationship,
            self.affinity_band,
            self.player_signal,
            "combat" if self.combat else "no_combat",
            "quest" if self.quest else "no_quest",
        ])


class NPCActionBandit:
    """
    Thompson sampling bandit with Beta priors per (key, action).
    Rewards must be in [0, 1].
    """

    def __init__(self, path: Optional[Path] = None, min_trials_before_exploit: int = 3):
        self.path = path or Path("data/learning/npc_action_bandit.json")
        self.min_trials_before_exploit = min_trials_before_exploit
        self._arms: Dict[str, Dict[str, Dict[str, float]]] = {}  # key -> action -> {alpha,beta}
        self.load()

    def _get_arm(self, key: str, action: NPCAction) -> Dict[str, float]:
        k = key
        a = action.value
        if k not in self._arms:
            self._arms[k] = {}
        if a not in self._arms[k]:
            # mild prior: alpha=1, beta=1 (uniform)
            self._arms[k][a] = {"alpha": 1.0, "beta": 1.0, "n": 0.0}
        return self._arms[k][a]

    @staticmethod
    def _clamp01(x: float) -> float:
        if x < 0.0:
            return 0.0
        if x > 1.0:
            return 1.0
        return x

    def select(
        self,
        key: str,
        candidates: List[NPCAction],
        priors: Optional[Dict[NPCAction, float]] = None,
        explore_bias: float = 0.10,
    ) -> NPCAction:
        """
        Select an action among candidates.
        - priors: optional scorer values (any real number). Used as weak tie-breaker.
        - explore_bias: chance to pick a random candidate early to avoid lock-in.
        """
        if not candidates:
            raise ValueError("No candidates provided to bandit.select()")

        # early exploration
        if random.random() < explore_bias:
            return random.choice(candidates)

        best_a: Optional[NPCAction] = None
        best_score: float = -1e9

        for a in candidates:
            arm = self._get_arm(key, a)
            alpha = arm["alpha"]
            beta = arm["beta"]
            n = arm["n"]

            # if we have almost no data, keep it a bit exploratory
            sample = random.betavariate(alpha, beta)

            # weak prior blending: normalize scorer prior into a small [-0.05, +0.05] bump
            bump = 0.0
            if priors and a in priors:
                p = priors[a]
                bump = max(-0.05, min(0.05, p / 20.0))

            # discourage exploitation if no trials yet
            cold_start_penalty = 0.0
            if n < self.min_trials_before_exploit:
                cold_start_penalty = -0.03 * (self.min_trials_before_exploit - n)

            score = sample + bump + cold_start_penalty
            if score > best_score:
                best_score = score
                best_a = a

        return best_a or candidates[0]

    def update(self, key: str, action: NPCAction, reward_01: float) -> None:
        r = self._clamp01(float(reward_01))
        arm = self._get_arm(key, action)

        # Beta update: treat reward as fractional success
        arm["alpha"] += r
        arm["beta"] += (1.0 - r)
        arm["n"] += 1.0

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"arms": self._arms}, f, indent=2, sort_keys=True)

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._arms = data.get("arms", {}) or {}
        except Exception:
            # if corrupted, start fresh (better than crashing prod)
            self._arms = {}
