"""
Tests for bandit_core module.
"""
import pytest
import json
import tempfile
from pathlib import Path
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from learning.bandit_core import (
    BanditCore,
    ArmStats,
    ThompsonBetaStrategy,
    SoftmaxStrategy,
    UCB1Strategy
)


@pytest.fixture
def temp_path():
    """Create a temporary path for testing persistence."""
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json") as f:
        path = Path(f.name)
    yield path
    if path.exists():
        path.unlink()


def test_bandit_core_initialization():
    """Test basic initialization of BanditCore."""
    bandit = BanditCore(strategy="thompson_beta", seed=42)
    assert bandit.strategy_name == "thompson_beta"
    assert bandit.seed == 42


def test_bandit_core_select_basic():
    """Test basic selection."""
    bandit = BanditCore(strategy="thompson_beta", seed=42)
    candidates = ["action_a", "action_b", "action_c"]
    
    selected = bandit.select("key1", candidates)
    assert selected in candidates


def test_bandit_core_thompson_learning():
    """Test that Thompson Beta learns to prefer higher reward action."""
    bandit = BanditCore(strategy="thompson_beta", seed=42)
    candidates = ["good_action", "bad_action"]
    
    # Simulate many rounds
    for _ in range(100):
        selected = bandit.select("test_key", candidates)
        
        # Give higher reward to good_action
        if selected == "good_action":
            bandit.update("test_key", selected, 0.9)
        else:
            bandit.update("test_key", selected, 0.1)
    
    # After learning, should prefer good_action more often
    selections = []
    for _ in range(50):
        selections.append(bandit.select("test_key", candidates, explore_bias=0.0))
    
    good_count = selections.count("good_action")
    bad_count = selections.count("bad_action")
    
    # Should select good_action significantly more
    assert good_count > bad_count


def test_bandit_core_softmax_learning():
    """Test that Softmax learns to prefer higher reward action."""
    bandit = BanditCore(strategy="softmax", seed=42, strategy_params={"temperature": 0.1})
    candidates = ["good_action", "bad_action"]
    
    # Simulate many rounds
    for _ in range(100):
        selected = bandit.select("test_key", candidates, explore_bias=0.0)
        
        if selected == "good_action":
            bandit.update("test_key", selected, 0.9)
        else:
            bandit.update("test_key", selected, 0.1)
    
    # Check that good_action has better stats
    good_stats = bandit.get_stats("test_key", "good_action")
    bad_stats = bandit.get_stats("test_key", "bad_action")
    
    assert good_stats is not None
    assert bad_stats is not None
    assert good_stats.mean() > bad_stats.mean()


def test_bandit_core_ucb1_learning():
    """Test that UCB1 learns to prefer higher reward action."""
    bandit = BanditCore(strategy="ucb1", seed=42, strategy_params={"c": 2.0})
    candidates = ["good_action", "bad_action"]
    
    # Simulate many rounds
    for _ in range(100):
        selected = bandit.select("test_key", candidates, explore_bias=0.0)
        
        if selected == "good_action":
            bandit.update("test_key", selected, 0.9)
        else:
            bandit.update("test_key", selected, 0.1)
    
    # Check that good_action has better stats
    good_stats = bandit.get_stats("test_key", "good_action")
    bad_stats = bandit.get_stats("test_key", "bad_action")
    
    assert good_stats is not None
    assert bad_stats is not None
    assert good_stats.mean() > bad_stats.mean()


def test_bandit_core_persistence(temp_path):
    """Test save and load functionality."""
    # Create bandit and train it
    bandit1 = BanditCore(strategy="thompson_beta", path=temp_path, seed=42)
    candidates = ["action_a", "action_b"]
    
    for _ in range(20):
        selected = bandit1.select("key1", candidates)
        bandit1.update("key1", selected, 0.8)
    
    bandit1.save()
    
    # Load into new bandit
    bandit2 = BanditCore(strategy="thompson_beta", path=temp_path)
    
    # Check that stats were restored
    stats1 = bandit1.get_stats("key1", "action_a")
    stats2 = bandit2.get_stats("key1", "action_a")
    
    if stats1 and stats2:
        assert stats1.n == stats2.n
        assert stats1.total_reward == stats2.total_reward


def test_bandit_core_priors_respected():
    """Test that priors influence selection."""
    bandit = BanditCore(strategy="thompson_beta", seed=42)
    candidates = ["action_a", "action_b", "action_c"]
    
    # Give strong prior to action_b
    priors = {
        "action_a": 0.0,
        "action_b": 100.0,  # Strong positive prior
        "action_c": 0.0
    }
    
    # With no history, priors should influence selection
    selections = []
    for _ in range(50):
        selected = bandit.select("new_key", candidates, priors=priors, explore_bias=0.0)
        selections.append(selected)
    
    # action_b should be selected more often due to prior
    b_count = selections.count("action_b")
    assert b_count > 10  # Should be picked fairly often


def test_bandit_core_deterministic_with_seed():
    """Test that same seed produces same results."""
    candidates = ["a1", "a2", "a3"]
    
    bandit1 = BanditCore(strategy="thompson_beta", seed=123)
    selections1 = []
    for _ in range(10):
        s = bandit1.select("key", candidates)
        selections1.append(s)
        bandit1.update("key", s, 0.5)
    
    bandit2 = BanditCore(strategy="thompson_beta", seed=123)
    selections2 = []
    for _ in range(10):
        s = bandit2.select("key", candidates)
        selections2.append(s)
        bandit2.update("key", s, 0.5)
    
    assert selections1 == selections2


def test_bandit_core_banned_actions_fallback():
    """Test fallback when all candidates have poor history."""
    bandit = BanditCore(strategy="thompson_beta", seed=42)
    candidates = ["bad1", "bad2"]
    
    # Give all actions poor history
    for _ in range(20):
        for action in candidates:
            bandit.update("key", action, 0.0)
    
    # Should still select something (not crash)
    selected = bandit.select("key", candidates)
    assert selected in candidates


def test_bandit_core_reward_clamping():
    """Test that rewards are clamped to [0, 1]."""
    bandit = BanditCore(strategy="thompson_beta", seed=42)
    
    # Try to update with out-of-range rewards
    bandit.update("key", "action1", 2.0)  # Too high
    bandit.update("key", "action2", -1.0)  # Too low
    
    stats1 = bandit.get_stats("key", "action1")
    stats2 = bandit.get_stats("key", "action2")
    
    # Should be clamped
    assert stats1.total_reward <= 1.0
    assert stats2.total_reward >= 0.0


def test_bandit_core_empty_candidates_error():
    """Test that empty candidates list raises error."""
    bandit = BanditCore(strategy="thompson_beta", seed=42)
    
    with pytest.raises(ValueError):
        bandit.select("key", [])


def test_bandit_core_reset():
    """Test reset functionality."""
    bandit = BanditCore(strategy="thompson_beta", seed=42)
    
    # Add some history
    bandit.update("key1", "action1", 0.8)
    bandit.update("key2", "action2", 0.7)
    
    # Reset specific key
    bandit.reset("key1")
    assert bandit.get_stats("key1", "action1") is None
    assert bandit.get_stats("key2", "action2") is not None
    
    # Reset all
    bandit.reset()
    assert bandit.get_stats("key2", "action2") is None


def test_bandit_core_multiple_keys():
    """Test that different keys maintain separate state."""
    bandit = BanditCore(strategy="thompson_beta", seed=42)
    
    # Update different keys
    bandit.update("combat", "attack", 0.9)
    bandit.update("dialogue", "greet", 0.8)
    
    stats_combat = bandit.get_stats("combat", "attack")
    stats_dialogue = bandit.get_stats("dialogue", "greet")
    
    assert stats_combat is not None
    assert stats_dialogue is not None
    assert stats_combat.total_reward == 0.9
    assert stats_dialogue.total_reward == 0.8


def test_arm_stats_mean():
    """Test ArmStats mean calculation."""
    arm = ArmStats()
    assert arm.mean() == 0.5  # Default for no trials
    
    arm.n = 10
    arm.total_reward = 7.5
    assert arm.mean() == 0.75


def test_thompson_strategy_cold_start_penalty():
    """Test that cold start penalty encourages exploration."""
    strategy = ThompsonBetaStrategy(min_trials_before_exploit=5)
    
    # Create arms with different trial counts
    arms = {
        "experienced": ArmStats(alpha=10, beta=2, n=10, total_reward=8.0),
        "new": ArmStats(alpha=1, beta=1, n=0, total_reward=0.0)
    }
    
    # Should sometimes pick "new" even though "experienced" has better stats
    new_count = 0
    for _ in range(100):
        selected = strategy.select(["experienced", "new"], arms, explore_bias=0.0)
        if selected == "new":
            new_count += 1
    
    # Should explore "new" at least sometimes
    assert new_count > 0


def test_softmax_temperature_zero():
    """Test that temperature=0 gives greedy selection."""
    strategy = SoftmaxStrategy(temperature=0.0)
    
    arms = {
        "good": ArmStats(n=10, total_reward=9.0),
        "bad": ArmStats(n=10, total_reward=2.0)
    }
    
    # Should always pick "good" with temperature=0
    selections = [strategy.select(["good", "bad"], arms, explore_bias=0.0) for _ in range(20)]
    assert all(s == "good" for s in selections)


def test_ucb1_explores_unplayed_arms():
    """Test that UCB1 tries all arms initially."""
    strategy = UCB1Strategy(c=2.0)
    
    arms = {
        "played": ArmStats(n=10, total_reward=7.0),
        "unplayed": ArmStats(n=0, total_reward=0.0)
    }
    
    # Should immediately try unplayed arm
    selected = strategy.select(["played", "unplayed"], arms, explore_bias=0.0)
    assert selected == "unplayed"


def test_persistence_atomic_write(temp_path):
    """Test that persistence uses atomic write."""
    bandit = BanditCore(strategy="thompson_beta", path=temp_path, seed=42)
    bandit.update("key", "action", 0.8)
    bandit.save()
    
    # Check that .tmp file doesn't exist (was replaced)
    tmp_path = temp_path.with_suffix(".tmp")
    assert not tmp_path.exists()
    
    # Check that main file exists and is valid JSON
    assert temp_path.exists()
    with open(temp_path, "r") as f:
        data = json.load(f)
    assert "arms" in data


def test_corrupted_data_recovery(temp_path):
    """Test that corrupted data is handled gracefully."""
    # Write corrupted JSON
    temp_path.parent.mkdir(parents=True, exist_ok=True)
    with open(temp_path, "w") as f:
        f.write("{corrupted json")
    
    # Should not crash, should start fresh
    bandit = BanditCore(strategy="thompson_beta", path=temp_path)
    assert len(bandit._arms) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
