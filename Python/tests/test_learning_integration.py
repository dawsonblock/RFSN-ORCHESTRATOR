"""
Integration test for learning layer in orchestrator
"""
import pytest
from learning import PolicyAdapter, RewardModel, Trainer, ActionMode, FeatureVector, RewardSignals


class TestLearningIntegration:
    """Test full learning layer integration"""
    
    def test_full_turn_cycle(self):
        """Test complete turn: feature extraction → action selection → reward → update"""
        # Initialize components
        adapter = PolicyAdapter(epsilon=0.1)
        reward_model = RewardModel()
        trainer = Trainer(learning_rate=0.1, decay_rate=1.0)
        
        # Simulate CALL SITE A: Feature extraction and action selection
        rfsn_state = {
            "npc_name": "test_npc",
            "affinity": 0.7,
            "mood": "happy",
            "relationship": "friend",
            "playstyle": "diplomatic",
            "recent_sentiment": 0.5
        }
        retrieval_stats = {
            "top_k_scores": [0.8, 0.7, 0.6],
            "contradiction_detected": False
        }
        convo_stats = {
            "turn_count": 5
        }
        
        # Extract features
        features = adapter.build_features(rfsn_state, retrieval_stats, convo_stats)
        assert features is not None
        # Affinity 0.7 (from [-1,1] scale) maps to 0.85 (in [0,1] scale)
        assert features.affinity == pytest.approx(0.85, abs=0.01)
        
        # Choose action mode
        action_mode = adapter.choose_action_mode(features)
        assert action_mode in ActionMode
        
        # Verify prompt injection exists
        prompt_injection = action_mode.prompt_injection
        assert len(prompt_injection) > 0
        assert "[ACTION MODE:" in prompt_injection
        
        # Simulate CALL SITE B: Reward computation and update
        signals = RewardSignals(
            contradiction_detected=False,
            user_correction=False,
            tts_overrun=False,
            conversation_continued=True,
            follow_up_question=True
        )
        
        # Compute reward
        reward = reward_model.compute(signals)
        assert reward > 0  # Should be positive (continued + follow-up)
        
        # Update weights
        initial_weights = adapter.weights.copy()
        adapter.weights = trainer.update(adapter.weights, features, action_mode, reward)
        
        # Weights should change
        assert not (adapter.weights == initial_weights).all()
        
        # Trainer should have logged the update
        assert trainer.update_count == 1
    
    def test_action_mode_affects_prompt(self):
        """Each action mode should inject different control blocks"""
        modes_seen = set()
        prompts_seen = set()
        
        for mode in ActionMode:
            injection = mode.prompt_injection
            modes_seen.add(mode.name)
            prompts_seen.add(injection)
        
        # Should have 6 unique modes and 6 unique prompts
        assert len(modes_seen) == 6
        assert len(prompts_seen) == 6
        
        # Each should have specific keywords
        assert any("TERSE" in p for p in prompts_seen)
        assert any("WARM" in p or "SUPPORTIVE" in p for p in prompts_seen)
        assert any("LORE" in p for p in prompts_seen)
        assert any("CLARIFY" in p for p in prompts_seen)
        assert any("EVIDENCE" in p or "CITE" in p for p in prompts_seen)
        assert any("DEESCALATE" in p for p in prompts_seen)
    
    def test_learning_over_multiple_turns(self):
        """Learning should shift action probabilities over multiple turns"""
        adapter = PolicyAdapter(epsilon=0.0)  # No exploration
        trainer = Trainer(learning_rate=0.1, decay_rate=1.0)
        
        # Fixed features
        features = FeatureVector(
            npc_id_hash=0, affinity=0.5, mood=0, relationship=0,
            player_playstyle=0, recent_sentiment=0.0,
            retrieval_topk_mean_sim=0.0, retrieval_contradiction_flag=0,
            turn_index_in_convo=0, last_action_mode=0
        )
        
        # Get initial probabilities
        initial_probs = adapter.get_action_probabilities(features)
        
        # Simulate 50 turns with positive reward for WARM_SUPPORTIVE
        target_action = ActionMode.WARM_SUPPORTIVE
        for _ in range(50):
            adapter.weights = trainer.update(
                adapter.weights, features, target_action, reward=1.0
            )
        
        # Get final probabilities
        final_probs = adapter.get_action_probabilities(features)
        
        # Probability of WARM_SUPPORTIVE should increase significantly
        assert final_probs[target_action.value] > initial_probs[target_action.value]
        assert final_probs[target_action.value] > 0.3  # Should be significantly increased
    
    def test_no_streaming_tts_modification(self):
        """Learning layer should not require changes to streaming/TTS"""
        # This test verifies the architectural constraint:
        # Learning layer operates at prompt boundary only
        
        adapter = PolicyAdapter()
        
        # Feature extraction doesn't touch streaming
        features = adapter.build_features(
            {"npc_name": "test", "affinity": 0.5, "mood": "neutral",
             "relationship": "stranger", "playstyle": "balanced", "recent_sentiment": 0.0},
            {"top_k_scores": [], "contradiction_detected": False},
            {"turn_count": 0}
        )
        
        # Action selection doesn't touch streaming
        action = adapter.choose_action_mode(features)
        
        # Prompt injection is just string concatenation
        prompt_base = "You are an NPC."
        prompt_with_learning = prompt_base + "\n\n" + action.prompt_injection
        
        # No streaming/TTS APIs were called
        assert len(prompt_with_learning) > len(prompt_base)
        assert "[ACTION MODE:" in prompt_with_learning
