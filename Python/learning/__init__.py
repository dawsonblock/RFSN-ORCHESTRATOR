"""
Learning Layer for RFSN Orchestrator
Enables adaptive NPC behavior through contextual bandits
"""

from .schemas import (
    ActionMode,
    FeatureVector,
    TurnLog,
    RewardSignals
)
from .policy_adapter import PolicyAdapter
from .reward_model import RewardModel
from .trainer import Trainer
from .learning_contract import (
    LearningContract,
    LearningConstraints,
    LearningUpdate,
    StateSnapshot,
    EvidenceType,
    WriteGateError
)
from .npc_action_bandit import NPCActionBandit, BanditKey

__all__ = [
    'ActionMode',
    'FeatureVector',
    'TurnLog',
    'RewardSignals',
    'PolicyAdapter',
    'RewardModel',
    'Trainer',
    'LearningContract',
    'LearningConstraints',
    'LearningUpdate',
    'StateSnapshot',
    'EvidenceType',
    'WriteGateError',
    'NPCActionBandit',
    'BanditKey'
]
