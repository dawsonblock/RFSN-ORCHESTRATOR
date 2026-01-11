"""
Policy Behavior Tests (Patch 7)
Verify that exploration and learning work at realistic epsilon values.
"""
import pytest
import numpy as np
from pathlib import Path
import tempfile

from learning.schemas import ActionMode, FeatureVector
from learning.policy_adapter import PolicyAdapter, stable_bucket_id
from learning.trainer import Trainer


class TestStableBucketId:
    """Test stable NPC bucketing (Patch 2)"""
    
    def test_stable_across_calls(self):
        """Same input should always produce same bucket"""
        npc_name = "Lydia"
        bucket1 = stable_bucket_id(npc_name, 256)
        bucket2 = stable_bucket_id(npc_name, 256)
        assert bucket1 == bucket2
    
    def test_different_names_differ(self):
        """Different NPCs should (usually) get different buckets"""
        buckets = {stable_bucket_id(f"npc_{i}", 256) for i in range(100)}
        # With 100 NPCs and 256 buckets, expect good distribution
        assert len(buckets) > 80  # At least 80% unique


class TestExplorationAtRealisticEpsilon:
    """Test exploration at realistic epsilon values (Patch 7)"""
    
    def test_exploration_finds_multiple_actions(self):
        """With epsilon=0.1, should still explore multiple actions over 500 trials"""
        adapter = PolicyAdapter(epsilon=0.1)
        
        # Fixed features
        features = FeatureVector(
            npc_id_hash=0.5, affinity=0.5, mood=0.2, relationship=0.0,
            player_playstyle=0.5, recent_sentiment=0.0,
            retrieval_topk_mean_sim=0.0, retrieval_contradiction_flag=0,
            turn_index_in_convo=0.1, last_action_mode=0.0
        )
        
        # Run 500 selections
        actions_seen = set()
        for _ in range(500):
            action = adapter.choose_action_mode(features)
            actions_seen.add(action)
        
        # With 10% exploration over 500 trials (~50 random), should see >1 unique action
        assert len(actions_seen) > 1, "Exploration should produce multiple distinct actions"


class TestLearningShiftsProbabilities:
    """Test that positive reward actually increases probability (Patch 7)"""
    
    def test_positive_reward_increases_probability(self):
        """100 positive rewards on action A should increase P(A|x)"""
        adapter = PolicyAdapter(epsilon=0.0)  # Pure exploitation
        trainer = Trainer(learning_rate=0.1, decay_rate=1.0)  # No decay for clean test
        
        # Fixed normalized features
        features = FeatureVector(
            npc_id_hash=0.3, affinity=0.5, mood=0.2, relationship=0.0,
            player_playstyle=0.5, recent_sentiment=0.0,
            retrieval_topk_mean_sim=0.0, retrieval_contradiction_flag=0,
            turn_index_in_convo=0.1, last_action_mode=0.0
        )
        
        # Get initial probability of action 2
        initial_probs = adapter.get_action_probabilities(features)
        action = ActionMode.LORE_EXPLAINER  # Action 2
        initial_prob = initial_probs[action.value]
        
        # Train on action 2 with positive reward 100 times
        for _ in range(100):
            adapter.weights = trainer.update(
                adapter.weights, features, action, reward=1.0
            )
        
        # Get new probability
        final_probs = adapter.get_action_probabilities(features)
        final_prob = final_probs[action.value]
        
        assert final_prob > initial_prob, \
            f"Probability should increase: {initial_prob:.4f} -> {final_prob:.4f}"
    
    def test_negative_reward_decreases_probability(self):
        """100 negative rewards on action A should decrease P(A|x)"""
        adapter = PolicyAdapter(epsilon=0.0)
        trainer = Trainer(learning_rate=0.1, decay_rate=1.0)
        
        # First, train action 2 to have high probability
        features = FeatureVector(
            npc_id_hash=0.3, affinity=0.5, mood=0.2, relationship=0.0,
            player_playstyle=0.5, recent_sentiment=0.0,
            retrieval_topk_mean_sim=0.0, retrieval_contradiction_flag=0,
            turn_index_in_convo=0.1, last_action_mode=0.0
        )
        
        action = ActionMode.LORE_EXPLAINER
        
        # Boost it first
        for _ in range(50):
            adapter.weights = trainer.update(
                adapter.weights, features, action, reward=1.0
            )
        
        boosted_prob = adapter.get_action_probabilities(features)[action.value]
        
        # Now punish it
        for _ in range(100):
            adapter.weights = trainer.update(
                adapter.weights, features, action, reward=-1.0
            )
        
        final_prob = adapter.get_action_probabilities(features)[action.value]
        
        assert final_prob < boosted_prob, \
            f"Probability should decrease after punishment: {boosted_prob:.4f} -> {final_prob:.4f}"


class TestTrainerStability:
    """Test trainer stability controls (Patch 4)"""
    
    def test_weights_stay_bounded(self):
        """Weights should not exceed WEIGHT_CAP even with extreme rewards"""
        adapter = PolicyAdapter(epsilon=0.0)
        trainer = Trainer(learning_rate=1.0, decay_rate=1.0)  # Aggressive for test
        
        features = FeatureVector(
            npc_id_hash=1.0, affinity=1.0, mood=1.0, relationship=1.0,
            player_playstyle=1.0, recent_sentiment=1.0,
            retrieval_topk_mean_sim=1.0, retrieval_contradiction_flag=1,
            turn_index_in_convo=1.0, last_action_mode=1.0
        )
        
        action = ActionMode.TERSE_DIRECT
        
        # Apply extreme positive rewards
        for _ in range(1000):
            adapter.weights = trainer.update(
                adapter.weights, features, action, reward=10.0  # Will be clipped to 2.0
            )
        
        # Weights should be capped
        assert np.abs(adapter.weights).max() <= trainer.WEIGHT_CAP, \
            f"Weights exceeded cap: {np.abs(adapter.weights).max()}"
    
    def test_features_are_clipped(self):
        """Features outside [-5, 5] should be clipped"""
        trainer = Trainer()
        
        # Create features with extreme values (should be clipped internally)
        features = FeatureVector(
            npc_id_hash=100.0,  # Way outside normal range
            affinity=50.0,
            mood=-100.0,
            relationship=0.0,
            player_playstyle=0.0,
            recent_sentiment=0.0,
            retrieval_topk_mean_sim=0.0,
            retrieval_contradiction_flag=0,
            turn_index_in_convo=0.0,
            last_action_mode=0.0
        )
        
        weights = np.zeros((6, 10))
        action = ActionMode.TERSE_DIRECT
        
        # Should not crash or produce NaN
        new_weights = trainer.update(weights, features, action, reward=1.0)
        
        assert not np.any(np.isnan(new_weights)), "Weights should not be NaN"
        assert not np.any(np.isinf(new_weights)), "Weights should not be infinite"
