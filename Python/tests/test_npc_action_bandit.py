"""
Tests for NPC Action Bandit
Tests Thompson Sampling bandit for action selection learning.
"""
import pytest
import tempfile
import json
from pathlib import Path

from learning.npc_action_bandit import NPCActionBandit, BanditKey
from world_model import NPCAction, PlayerSignal, StateSnapshot


class TestBanditKey:
    """Test BanditKey bucketing logic"""
    
    def test_affinity_bands(self):
        """Test affinity is bucketed into bands"""
        assert BanditKey._affinity_band(-0.8) == "very_neg"
        assert BanditKey._affinity_band(-0.4) == "neg"
        assert BanditKey._affinity_band(0.0) == "neutral"
        assert BanditKey._affinity_band(0.4) == "pos"
        assert BanditKey._affinity_band(0.8) == "very_pos"
    
    def test_from_state(self):
        """Test creating BanditKey from StateSnapshot"""
        state = StateSnapshot(
            mood="happy",
            affinity=0.5,
            relationship="friend",
            recent_sentiment=0.3,
            combat_active=False,
            quest_active=True
        )
        
        key = BanditKey.from_state(state, PlayerSignal.GREET)
        
        assert key.mood == "happy"
        assert key.relationship == "friend"
        assert key.affinity_band == "pos"
        assert key.player_signal == "greet"
        assert key.combat == False
        assert key.quest == True
    
    def test_to_str(self):
        """Test key serialization"""
        key = BanditKey(
            mood="neutral",
            relationship="stranger",
            affinity_band="neutral",
            player_signal="question",
            combat=False,
            quest=False
        )
        
        key_str = key.to_str()
        assert key_str == "neutral|stranger|neutral|question|no_combat|no_quest"


class TestNPCActionBandit:
    """Test NPCActionBandit Thompson Sampling"""
    
    @pytest.fixture
    def temp_path(self):
        """Create temporary file path for bandit storage"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            yield Path(f.name)
            # Cleanup
            if Path(f.name).exists():
                Path(f.name).unlink()
    
    def test_init(self, temp_path):
        """Test bandit initialization"""
        bandit = NPCActionBandit(path=temp_path)
        assert bandit.path == temp_path
        assert bandit._arms == {}
    
    def test_select_single_candidate(self, temp_path):
        """Test selection with single candidate (forced action)"""
        bandit = NPCActionBandit(path=temp_path)
        
        candidates = [NPCAction.FLEE]
        selected = bandit.select("test_key", candidates)
        
        assert selected == NPCAction.FLEE
    
    def test_select_multiple_candidates(self, temp_path):
        """Test selection with multiple candidates"""
        bandit = NPCActionBandit(path=temp_path)
        
        candidates = [NPCAction.GREET, NPCAction.INQUIRE, NPCAction.OFFER]
        selected = bandit.select("test_key", candidates)
        
        assert selected in candidates
    
    def test_select_with_priors(self, temp_path):
        """Test selection respects scorer priors"""
        bandit = NPCActionBandit(path=temp_path)
        
        candidates = [NPCAction.GREET, NPCAction.INQUIRE]
        priors = {
            NPCAction.GREET: 10.0,  # High score
            NPCAction.INQUIRE: -5.0  # Low score
        }
        
        # Over many samples, GREET should be selected more often
        greet_count = 0
        for _ in range(50):
            selected = bandit.select("test_key", candidates, priors=priors, explore_bias=0.0)
            if selected == NPCAction.GREET:
                greet_count += 1
        
        # Should favor GREET (at least 60% of time)
        assert greet_count >= 30
    
    def test_update(self, temp_path):
        """Test bandit update with reward"""
        bandit = NPCActionBandit(path=temp_path)
        
        key = "test_key"
        action = NPCAction.GREET
        
        # Initial arm state
        arm_before = bandit._get_arm(key, action)
        alpha_before = arm_before["alpha"]
        beta_before = arm_before["beta"]
        
        # Update with positive reward
        bandit.update(key, action, reward_01=0.8)
        
        arm_after = bandit._get_arm(key, action)
        assert arm_after["alpha"] > alpha_before
        assert arm_after["beta"] > beta_before  # Beta increases by (1 - reward)
        assert arm_after["n"] == 1.0
    
    def test_update_clamps_reward(self, temp_path):
        """Test reward is clamped to [0, 1]"""
        bandit = NPCActionBandit(path=temp_path)
        
        # Test clamping
        assert bandit._clamp01(-0.5) == 0.0
        assert bandit._clamp01(1.5) == 1.0
        assert bandit._clamp01(0.5) == 0.5
    
    def test_save_and_load(self, temp_path):
        """Test persistence"""
        bandit1 = NPCActionBandit(path=temp_path)
        
        # Update some actions
        bandit1.update("key1", NPCAction.GREET, 0.9)
        bandit1.update("key1", NPCAction.FAREWELL, 0.3)
        bandit1.update("key2", NPCAction.ATTACK, 0.1)
        
        # Save
        bandit1.save()
        
        # Load in new instance
        bandit2 = NPCActionBandit(path=temp_path)
        
        # Check state was restored
        arm1 = bandit2._get_arm("key1", NPCAction.GREET)
        assert arm1["n"] == 1.0
        assert arm1["alpha"] > 1.0  # Should have increased
        
        arm2 = bandit2._get_arm("key2", NPCAction.ATTACK)
        assert arm2["n"] == 1.0
    
    def test_corrupted_file_handling(self, temp_path):
        """Test bandit handles corrupted files gracefully"""
        # Write corrupted JSON
        with open(temp_path, 'w') as f:
            f.write("corrupted json {{{")
        
        # Should start fresh instead of crashing
        bandit = NPCActionBandit(path=temp_path)
        assert bandit._arms == {}
    
    def test_learning_over_time(self, temp_path):
        """Test bandit learns to prefer better actions"""
        bandit = NPCActionBandit(path=temp_path)
        
        key = "test_key"
        candidates = [NPCAction.GREET, NPCAction.INSULT]
        
        # Train: GREET gets high rewards, INSULT gets low rewards
        for _ in range(20):
            selected = bandit.select(key, candidates, explore_bias=0.3)
            
            if selected == NPCAction.GREET:
                reward = 0.9
            else:
                reward = 0.1
            
            bandit.update(key, selected, reward)
        
        # After learning, should strongly prefer GREET
        greet_count = 0
        for _ in range(20):
            selected = bandit.select(key, candidates, explore_bias=0.0)
            if selected == NPCAction.GREET:
                greet_count += 1
        
        # Should prefer GREET most of the time (at least 70%)
        assert greet_count >= 14


class TestBanditIntegration:
    """Integration tests for bandit with action scorer"""
    
    def test_forced_action_bypass(self, tmp_path):
        """Test that forced actions bypass bandit learning"""
        from action_scorer import ActionScorer, UtilityFunction
        from world_model import WorldModel
        
        # Create world model and scorer
        world_model = WorldModel(retrieval_k=3)
        action_scorer = ActionScorer(
            world_model=world_model,
            utility_fn=UtilityFunction()
        )
        
        # Create state that should force FLEE
        state = StateSnapshot(
            mood="fearful",
            affinity=-0.8,
            relationship="enemy",
            recent_sentiment=-0.9,
            combat_active=True,
            trust_level=0.1,
            fear_level=0.9
        )
        
        # Score candidates
        scores = action_scorer.score_candidates(state, PlayerSignal.ATTACK)
        
        # Build candidates (should be singleton if forced)
        candidates = [s.action for s in scores[:4]]
        
        # If only one candidate, bandit should be bypassed
        if len(candidates) == 1:
            assert candidates[0] in [NPCAction.FLEE, NPCAction.DEFEND]
            # In real code, bandit.select would not be called
    
    def test_bandit_respects_scorer_filtering(self, tmp_path):
        """Test bandit only selects from scorer-provided candidates"""
        from action_scorer import ActionScorer, UtilityFunction
        from world_model import WorldModel
        
        bandit_path = tmp_path / "bandit.json"
        bandit = NPCActionBandit(path=bandit_path)
        
        # Create world model and scorer
        world_model = WorldModel(retrieval_k=3)
        action_scorer = ActionScorer(
            world_model=world_model,
            utility_fn=UtilityFunction()
        )
        
        # Create neutral state
        state = StateSnapshot(
            mood="neutral",
            affinity=0.0,
            relationship="stranger",
            recent_sentiment=0.0,
            combat_active=False,
            trust_level=0.5,
            fear_level=0.0
        )
        
        # Score candidates
        scores = action_scorer.score_candidates(state, PlayerSignal.GREET)
        
        # Build candidates
        candidates = [s.action for s in scores[:4]]
        
        # Bandit should only select from these candidates
        key = BanditKey.from_state(state, PlayerSignal.GREET).to_str()
        
        for _ in range(10):
            selected = bandit.select(key, candidates)
            assert selected in candidates


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
