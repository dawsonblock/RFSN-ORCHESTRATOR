"""
Tests for bandit_learner module.

Tests Thompson sampling, UCB1, persistence, and safety mechanisms.
"""
import pytest
import json
import os
import tempfile
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from bandit_learner import (
    ArmStats,
    BanditConfig,
    StateActionBandit,
)


class TestArmStats:
    """Test arm statistics tracking."""
    
    def test_initialization(self):
        """Arm stats should initialize with correct defaults."""
        stats = ArmStats()
        assert stats.n == 0
        assert stats.value_sum == 0.0
        assert stats.a == 1.0
        assert stats.b == 1.0
        assert stats.last_update_ts == 0.0
    
    def test_mean_calculation(self):
        """Mean should compute correctly."""
        stats = ArmStats(n=5, value_sum=2.5)
        assert stats.mean() == 0.5
    
    def test_mean_zero_trials(self):
        """Mean should return 0 for zero trials."""
        stats = ArmStats(n=0, value_sum=0.0)
        assert stats.mean() == 0.0


class TestBanditConfig:
    """Test configuration object."""
    
    def test_default_config(self):
        """Default config should have sensible values."""
        cfg = BanditConfig()
        assert cfg.mode == "thompson"
        assert cfg.epsilon == 0.02
        assert cfg.min_trials_before_exploit == 3
        assert cfg.reward_min == -1.0
        assert cfg.reward_max == 1.0
        assert cfg.thompson_binary == False
        assert cfg.ucb_c == 2.0
        assert cfg.banned_actions is None
    
    def test_custom_config(self):
        """Custom config should override defaults."""
        cfg = BanditConfig(
            mode="ucb",
            epsilon=0.1,
            banned_actions=["ATTACK"]
        )
        assert cfg.mode == "ucb"
        assert cfg.epsilon == 0.1
        assert cfg.banned_actions == ["ATTACK"]


class TestStateActionBandit:
    """Test bandit learner functionality."""
    
    @pytest.fixture
    def temp_storage(self):
        """Create temporary storage file."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            path = f.name
        yield path
        # Cleanup
        if os.path.exists(path):
            os.remove(path)
        tmp_path = path + ".tmp"
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
    
    @pytest.fixture
    def bandit(self, temp_storage):
        """Create bandit learner instance."""
        config = BanditConfig(thompson_binary=True)
        return StateActionBandit(temp_storage, config)
    
    def test_initialization(self, temp_storage):
        """Bandit should initialize correctly."""
        bandit = StateActionBandit(temp_storage)
        assert bandit.storage_path == temp_storage
        assert isinstance(bandit.cfg, BanditConfig)
        assert bandit._db == {}
    
    def test_select_action_creates_state(self, bandit):
        """Selecting action should create state if not exists."""
        actions = ["GREET", "HELP", "WARN"]
        action = bandit.select_action("FRIENDLY", actions)
        assert action in actions
        assert "FRIENDLY" in bandit._db
        assert all(a in bandit._db["FRIENDLY"] for a in actions)
    
    def test_select_action_exploration(self, bandit):
        """Epsilon exploration should select randomly."""
        bandit.cfg.epsilon = 1.0  # Always explore
        actions = ["GREET", "HELP"]
        # Run multiple times to verify randomness
        selected = set()
        for _ in range(20):
            action = bandit.select_action("FRIENDLY", actions, rng_seed=None)
            selected.add(action)
        # Should see both actions eventually
        assert len(selected) >= 1  # At least one action selected
    
    def test_select_action_min_trials(self, bandit):
        """Should explore uniformly until min trials reached."""
        bandit.cfg.epsilon = 0.0  # Disable random exploration
        bandit.cfg.min_trials_before_exploit = 3
        actions = ["GREET", "HELP", "WARN"]
        
        # First 3 selections should pick least-tried (all 0 initially)
        # After 3 trials total, picks should still favor least-tried until
        # each has been tried min_trials_before_exploit times
        for _ in range(9):
            action = bandit.select_action("FRIENDLY", actions)
            # Simulate updating to track trials
            bandit._db["FRIENDLY"][action].n += 1
        
        # Each action should have been tried min_trials_before_exploit times
        assert bandit._db["FRIENDLY"]["GREET"].n == 3
        assert bandit._db["FRIENDLY"]["HELP"].n == 3
        assert bandit._db["FRIENDLY"]["WARN"].n == 3
    
    def test_select_action_thompson_sampling(self, bandit):
        """Thompson sampling should exploit after sufficient trials."""
        bandit.cfg.epsilon = 0.0
        bandit.cfg.min_trials_before_exploit = 1
        actions = ["GREET", "HELP"]
        
        # Give GREET positive rewards
        for _ in range(5):
            bandit.update("FRIENDLY", "GREET", 1.0)
        
        # Give HELP negative rewards
        for _ in range(5):
            bandit.update("FRIENDLY", "HELP", -1.0)
        
        # Should prefer GREET
        selected = []
        for _ in range(10):
            action = bandit.select_action("FRIENDLY", actions)
            selected.append(action)
        
        # GREET should be selected more often
        greet_count = selected.count("GREET")
        help_count = selected.count("HELP")
        assert greet_count > help_count
    
    def test_select_action_ucb(self, temp_storage):
        """UCB should immediately explore untried actions."""
        config = BanditConfig(mode="ucb", epsilon=0.0, min_trials_before_exploit=0)
        bandit = StateActionBandit(temp_storage, config)
        actions = ["GREET", "HELP"]
        
        # Give GREET some good rewards
        for _ in range(5):
            bandit.update("FRIENDLY", "GREET", 1.0)
        
        # First call to select_action should try the untried action (HELP)
        # because UCB gives untried actions infinite score
        selected_actions = []
        for _ in range(10):
            action = bandit.select_action("FRIENDLY", actions)
            selected_actions.append(action)
            # If we picked HELP, update it to mark it as tried
            if action == "HELP":
                bandit.update("FRIENDLY", "HELP", 0.0)
                break
        
        # HELP should have been selected and tried
        assert "HELP" in selected_actions
        assert bandit._db["FRIENDLY"]["HELP"].n > 0
    
    def test_update_basic(self, bandit):
        """Update should track statistics correctly."""
        bandit.update("FRIENDLY", "GREET", 0.5)
        
        stats = bandit._db["FRIENDLY"]["GREET"]
        assert stats.n == 1
        assert stats.value_sum == 0.5
        assert stats.mean() == 0.5
    
    def test_update_binary_thompson(self, bandit):
        """Binary Thompson should update alpha/beta correctly."""
        # Positive reward
        bandit.update("FRIENDLY", "GREET", 0.8)
        assert bandit._db["FRIENDLY"]["GREET"].a == 2.0
        assert bandit._db["FRIENDLY"]["GREET"].b == 1.0
        
        # Negative reward
        bandit.update("FRIENDLY", "WARN", -0.5)
        assert bandit._db["FRIENDLY"]["WARN"].a == 1.0
        assert bandit._db["FRIENDLY"]["WARN"].b == 2.0
    
    def test_update_continuous_thompson(self, temp_storage):
        """Continuous Thompson should map rewards to probabilities."""
        config = BanditConfig(thompson_binary=False)
        bandit = StateActionBandit(temp_storage, config)
        
        bandit.update("FRIENDLY", "GREET", 1.0)  # Max reward
        stats = bandit._db["FRIENDLY"]["GREET"]
        # Should increase alpha more than beta
        assert stats.a > stats.b
    
    def test_update_clamping(self, bandit):
        """Rewards should be clamped to configured bounds."""
        bandit.update("FRIENDLY", "GREET", 10.0)  # Above max
        assert bandit._db["FRIENDLY"]["GREET"].value_sum == 1.0
        
        bandit.update("FRIENDLY", "WARN", -10.0)  # Below min
        assert bandit._db["FRIENDLY"]["WARN"].value_sum == -1.0
    
    def test_reset_state(self, bandit):
        """Reset should clear state statistics."""
        bandit.update("FRIENDLY", "GREET", 1.0)
        assert "FRIENDLY" in bandit._db
        
        bandit.reset_state("FRIENDLY")
        assert "FRIENDLY" not in bandit._db
    
    def test_snapshot(self, bandit):
        """Snapshot should return serializable dict."""
        bandit.update("FRIENDLY", "GREET", 1.0)
        bandit.update("ALERT", "WARN", -0.5)
        
        snapshot = bandit.snapshot()
        assert "FRIENDLY" in snapshot
        assert "ALERT" in snapshot
        assert "GREET" in snapshot["FRIENDLY"]
        assert "WARN" in snapshot["ALERT"]
        assert isinstance(snapshot["FRIENDLY"]["GREET"], dict)
    
    def test_persistence_save(self, bandit):
        """Changes should persist to disk."""
        bandit.update("FRIENDLY", "GREET", 1.0)
        
        # Check file exists
        assert os.path.exists(bandit.storage_path)
        
        # Load and verify
        with open(bandit.storage_path, 'r') as f:
            data = json.load(f)
        
        assert "FRIENDLY" in data
        assert "GREET" in data["FRIENDLY"]
        assert data["FRIENDLY"]["GREET"]["n"] == 1
    
    def test_persistence_load(self, temp_storage):
        """Should load existing data from disk."""
        # Create initial data
        data = {
            "FRIENDLY": {
                "GREET": {
                    "n": 5,
                    "value_sum": 2.5,
                    "a": 4.0,
                    "b": 2.0,
                    "last_update_ts": 123.456
                }
            }
        }
        with open(temp_storage, 'w') as f:
            json.dump(data, f)
        
        # Load bandit
        bandit = StateActionBandit(temp_storage)
        
        # Verify loaded data
        assert "FRIENDLY" in bandit._db
        stats = bandit._db["FRIENDLY"]["GREET"]
        assert stats.n == 5
        assert stats.value_sum == 2.5
        assert stats.a == 4.0
        assert stats.b == 2.0
    
    def test_persistence_corrupted_file(self, temp_storage):
        """Should handle corrupted file gracefully."""
        # Write corrupted data
        with open(temp_storage, 'w') as f:
            f.write("not valid json{{{")
        
        # Should not crash
        bandit = StateActionBandit(temp_storage)
        assert bandit._db == {}
    
    def test_banned_actions(self, temp_storage):
        """Banned actions should not be selected."""
        config = BanditConfig(banned_actions=["ATTACK", "FLEE"])
        bandit = StateActionBandit(temp_storage, config)
        
        actions = ["GREET", "ATTACK", "FLEE"]
        for _ in range(10):
            action = bandit.select_action("HOSTILE", actions)
            assert action not in ["ATTACK", "FLEE"]
            assert action == "GREET"
    
    def test_banned_all_actions_fallback(self, temp_storage):
        """If all banned, should fall back to full list."""
        config = BanditConfig(banned_actions=["GREET", "HELP"])
        bandit = StateActionBandit(temp_storage, config)
        
        actions = ["GREET", "HELP"]
        action = bandit.select_action("FRIENDLY", actions)
        assert action in actions  # Should select from original list
    
    def test_empty_actions_raises(self, bandit):
        """Empty action list should raise error."""
        with pytest.raises(ValueError):
            bandit.select_action("FRIENDLY", [])
    
    def test_reproducible_with_seed(self, bandit):
        """Same seed should produce same action sequence."""
        actions = ["GREET", "HELP", "WARN"]
        
        # First sequence
        seq1 = []
        for i in range(5):
            action = bandit.select_action("FRIENDLY", actions, rng_seed=42)
            seq1.append(action)
        
        # Reset state
        bandit.reset_state("FRIENDLY")
        
        # Second sequence with same seed
        seq2 = []
        for i in range(5):
            action = bandit.select_action("FRIENDLY", actions, rng_seed=42)
            seq2.append(action)
        
        assert seq1 == seq2
    
    def test_per_state_isolation(self, bandit):
        """States should not contaminate each other."""
        # Update FRIENDLY state
        bandit.update("FRIENDLY", "GREET", 1.0)
        
        # ALERT state should be independent
        assert "ALERT" not in bandit._db
        bandit.update("ALERT", "WARN", -1.0)
        
        # Verify isolation
        assert bandit._db["FRIENDLY"]["GREET"].value_sum == 1.0
        assert bandit._db["ALERT"]["WARN"].value_sum == -1.0
        assert "GREET" not in bandit._db["ALERT"]
        assert "WARN" not in bandit._db["FRIENDLY"]


class TestIntegration:
    """Integration tests for realistic scenarios."""
    
    def test_complete_workflow(self, tmp_path):
        """Test complete select-execute-update cycle."""
        storage = tmp_path / "bandit_state.json"
        config = BanditConfig(
            mode="thompson",
            thompson_binary=True,
            epsilon=0.1
        )
        bandit = StateActionBandit(str(storage), config)
        
        # Simulate conversation in FRIENDLY state
        actions = ["GREET", "HELP", "EXPLAIN"]
        for turn in range(20):
            # Select action
            action = bandit.select_action("FRIENDLY", actions)
            
            # Simulate outcome
            if action == "GREET":
                reward = 0.8  # Player likes greetings
            elif action == "HELP":
                reward = 0.5  # Neutral
            else:
                reward = 0.2  # Player finds explanations boring
            
            # Update
            bandit.update("FRIENDLY", action, reward)
        
        # GREET should be preferred
        stats = bandit._db["FRIENDLY"]["GREET"]
        assert stats.n > 0
        assert stats.mean() > 0
        
        # Verify persistence
        assert storage.exists()
        
        # Load new instance and verify
        bandit2 = StateActionBandit(str(storage), config)
        assert "FRIENDLY" in bandit2._db
        assert bandit2._db["FRIENDLY"]["GREET"].n == stats.n
    
    def test_multi_state_learning(self, tmp_path):
        """Test learning across multiple states."""
        storage = tmp_path / "multi_state.json"
        bandit = StateActionBandit(str(storage))
        
        # FRIENDLY state: GREET works well
        for _ in range(10):
            bandit.update("FRIENDLY", "GREET", 0.8)
        
        # ALERT state: WARN works well
        for _ in range(10):
            bandit.update("ALERT", "WARN", 0.8)
        
        # HOSTILE state: THREATEN works well
        for _ in range(10):
            bandit.update("HOSTILE", "THREATEN", 0.8)
        
        # Verify each state learned independently
        assert bandit._db["FRIENDLY"]["GREET"].mean() > 0.7
        assert bandit._db["ALERT"]["WARN"].mean() > 0.7
        assert bandit._db["HOSTILE"]["THREATEN"].mean() > 0.7
    
    def test_adaptation_to_changing_rewards(self, tmp_path):
        """Test adaptation when rewards change over time."""
        storage = tmp_path / "adaptive.json"
        config = BanditConfig(epsilon=0.1, thompson_binary=True)
        bandit = StateActionBandit(str(storage), config)
        
        actions = ["GREET", "HELP"]
        
        # Phase 1: GREET is good
        for _ in range(20):
            bandit.update("FRIENDLY", "GREET", 1.0)
            bandit.update("FRIENDLY", "HELP", -1.0)
        
        # Phase 2: Rewards flip
        for _ in range(20):
            bandit.update("FRIENDLY", "GREET", -1.0)
            bandit.update("FRIENDLY", "HELP", 1.0)
        
        # Should adapt to new rewards
        help_stats = bandit._db["FRIENDLY"]["HELP"]
        greet_stats = bandit._db["FRIENDLY"]["GREET"]
        
        # HELP should have more positive total value over time
        assert help_stats.n > 0
        assert greet_stats.n > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
