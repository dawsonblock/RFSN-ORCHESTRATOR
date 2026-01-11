"""
Tests for learning layer
"""
import pytest
import numpy as np
from pathlib import Path
import tempfile
import json

from learning.schemas import ActionMode, FeatureVector, RewardSignals, TurnLog
from learning.policy_adapter import PolicyAdapter
from learning.reward_model import RewardModel
from learning.trainer import Trainer


class TestActionModes:
    """Test action mode definitions and prompt injections"""
    
    def test_all_modes_have_injections(self):
        """Each action mode should have a prompt injection"""
        for mode in ActionMode:
            injection = mode.prompt_injection
            assert len(injection) > 0
            assert "[ACTION MODE:" in injection
    
    def test_mode_count(self):
        """Should have exactly 6 action modes"""
        assert len(ActionMode) == 6


class TestFeatureVector:
    """Test feature vector creation and conversion"""
    
    def test_to_array(self):
        """Feature vector should convert to 10-element array"""
        features = FeatureVector(
            npc_id_hash=42,
            affinity=0.7,
            mood=1,
            relationship=2,
            player_playstyle=3,
            recent_sentiment=0.5,
            retrieval_topk_mean_sim=0.8,
            retrieval_contradiction_flag=0,
            turn_index_in_convo=5,
            last_action_mode=0
        )
        arr = features.to_array()
        assert len(arr) == 10
        assert arr[0] == 42
        assert arr[1] == 0.7
    
    def test_to_dict(self):
        """Feature vector should convert to dictionary"""
        features = FeatureVector(
            npc_id_hash=42, affinity=0.7, mood=1, relationship=2,
            player_playstyle=3, recent_sentiment=0.5,
            retrieval_topk_mean_sim=0.8, retrieval_contradiction_flag=0,
            turn_index_in_convo=5, last_action_mode=0
        )
        d = features.to_dict()
        assert d["npc_id_hash"] == 42
        assert d["affinity"] == 0.7


class TestPolicyAdapter:
    """Test policy adapter exploration and exploitation"""
    
    def test_exploration_works(self):
        """With epsilon=1.0, should explore all actions"""
        adapter = PolicyAdapter(epsilon=1.0)
        
        features = FeatureVector(
            npc_id_hash=0, affinity=0.5, mood=0, relationship=0,
            player_playstyle=0, recent_sentiment=0.0,
            retrieval_topk_mean_sim=0.0, retrieval_contradiction_flag=0,
            turn_index_in_convo=0, last_action_mode=0
        )
        
        # Run 500 selections
        actions_seen = set()
        for _ in range(500):
            action = adapter.choose_action_mode(features)
            actions_seen.add(action)
        
        # Should see all 6 action modes
        assert len(actions_seen) == 6
    
    def test_exploitation_works(self):
        """With epsilon=0.0, should always pick same action"""
        adapter = PolicyAdapter(epsilon=0.0)
        
        features = FeatureVector(
            npc_id_hash=0, affinity=0.5, mood=0, relationship=0,
            player_playstyle=0, recent_sentiment=0.0,
            retrieval_topk_mean_sim=0.0, retrieval_contradiction_flag=0,
            turn_index_in_convo=0, last_action_mode=0
        )
        
        # Run 100 selections
        actions = [adapter.choose_action_mode(features) for _ in range(100)]
        
        # Should all be the same
        assert len(set(actions)) == 1
    
    def test_weight_persistence(self):
        """Weights should save and load correctly"""
        with tempfile.TemporaryDirectory() as tmpdir:
            weights_path = Path(tmpdir) / "weights.json"
            
            # Create adapter and modify weights
            adapter1 = PolicyAdapter(weights_path=weights_path)
            adapter1.weights[0, 0] = 42.0
            adapter1.save_weights()
            
            # Load in new adapter
            adapter2 = PolicyAdapter(weights_path=weights_path)
            assert adapter2.weights[0, 0] == 42.0


class TestRewardModel:
    """Test reward computation"""
    
    def test_negative_rewards(self):
        """Negative signals should give negative reward"""
        model = RewardModel()
        
        signals = RewardSignals(
            contradiction_detected=True,
            user_correction=True,
            tts_overrun=True
        )
        
        reward = model.compute(signals)
        assert reward < 0
    
    def test_positive_rewards(self):
        """Positive signals should give positive reward"""
        model = RewardModel()
        
        signals = RewardSignals(
            conversation_continued=True,
            follow_up_question=True
        )
        
        reward = model.compute(signals)
        assert reward > 0
    
    def test_reward_clamping(self):
        """Reward should be clamped to [-2.0, 2.0]"""
        model = RewardModel()
        
        # All negative signals
        signals = RewardSignals(
            contradiction_detected=True,
            user_correction=True,
            tts_overrun=True
        )
        reward = model.compute(signals)
        assert reward >= -2.0
        assert reward <= 2.0
    
    def test_user_correction_detection(self):
        """Should detect user corrections"""
        assert RewardModel.detect_user_correction("No, that's wrong")
        assert RewardModel.detect_user_correction("Actually, I said something else")
        assert not RewardModel.detect_user_correction("Yes, that's right")
    
    def test_follow_up_detection(self):
        """Should detect follow-up questions"""
        assert RewardModel.detect_follow_up_question("What about the dragon?")
        assert RewardModel.detect_follow_up_question("Why did that happen?")
        assert not RewardModel.detect_follow_up_question("Okay, thanks")


class TestTrainer:
    """Test online training"""
    
    def test_learning_shifts_probabilities(self):
        """Repeated positive rewards should increase action probability"""
        adapter = PolicyAdapter(epsilon=0.0)  # No exploration
        trainer = Trainer(learning_rate=0.1, decay_rate=1.0)  # No decay
        
        features = FeatureVector(
            npc_id_hash=0, affinity=0.5, mood=0, relationship=0,
            player_playstyle=0, recent_sentiment=0.0,
            retrieval_topk_mean_sim=0.0, retrieval_contradiction_flag=0,
            turn_index_in_convo=0, last_action_mode=0
        )
        
        # Get initial probabilities
        initial_probs = adapter.get_action_probabilities(features)
        
        # Train on action 2 with positive reward 100 times
        action = ActionMode.LORE_EXPLAINER  # Action 2
        for _ in range(100):
            adapter.weights = trainer.update(
                adapter.weights, features, action, reward=1.0
            )
        
        # Get new probabilities
        final_probs = adapter.get_action_probabilities(features)
        
        # Probability of action 2 should increase
        assert final_probs[action.value] > initial_probs[action.value]
    
    def test_turn_logging(self):
        """Turn logs should be written to JSONL"""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "logs.jsonl"
            trainer = Trainer(log_path=log_path)
            
            # Create and log a turn
            features = FeatureVector(
                npc_id_hash=0, affinity=0.5, mood=0, relationship=0,
                player_playstyle=0, recent_sentiment=0.0,
                retrieval_topk_mean_sim=0.0, retrieval_contradiction_flag=0,
                turn_index_in_convo=0, last_action_mode=0
            )
            signals = RewardSignals(conversation_continued=True)
            turn_log = TurnLog.create(
                "test_npc", features, ActionMode.TERSE_DIRECT, 0.4, signals
            )
            
            trainer.log_turn(turn_log)
            
            # Read back
            with open(log_path, 'r') as f:
                logged = json.loads(f.readline())
            
            assert logged["npc_id"] == "test_npc"
            assert logged["action_mode"] == "TERSE_DIRECT"
            assert logged["reward"] == 0.4
