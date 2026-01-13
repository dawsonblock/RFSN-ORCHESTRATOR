"""
Tests for World Model and Action Scorer
Tests retrieval-based prediction, hand-authored rules, and action scoring.
"""
import pytest
from pathlib import Path
import tempfile
import json

from world_model import (
    WorldModel, StateSnapshot, NPCAction, PlayerSignal,
    HandAuthoredRules, RetrievalWorldModel, Transition
)
from action_scorer import (
    ActionScorer, UtilityFunction, ActionScore, DecisionPipeline
)


class TestStateSnapshot:
    """Test StateSnapshot dataclass"""
    
    def test_state_creation(self):
        """Test creating a state snapshot"""
        state = StateSnapshot(
            mood="happy",
            affinity=0.5,
            relationship="friend",
            recent_sentiment=0.8
        )
        assert state.mood == "happy"
        assert state.affinity == 0.5
        assert state.relationship == "friend"
        assert state.recent_sentiment == 0.8
    
    def test_state_to_dict(self):
        """Test converting state to dictionary"""
        state = StateSnapshot(
            mood="angry",
            affinity=-0.3,
            relationship="enemy",
            recent_sentiment=-0.5
        )
        data = state.to_dict()
        assert data["mood"] == "angry"
        assert data["affinity"] == -0.3
        assert data["relationship"] == "enemy"
    
    def test_state_from_dict(self):
        """Test creating state from dictionary"""
        data = {
            "mood": "neutral",
            "affinity": 0.0,
            "relationship": "stranger",
            "recent_sentiment": 0.0
        }
        state = StateSnapshot.from_dict(data)
        assert state.mood == "neutral"
        assert state.affinity == 0.0
        assert state.relationship == "stranger"
    
    def test_state_distance(self):
        """Test calculating distance between states"""
        state1 = StateSnapshot(
            mood="happy",
            affinity=0.5,
            relationship="friend",
            recent_sentiment=0.8
        )
        state2 = StateSnapshot(
            mood="happy",
            affinity=0.5,
            relationship="friend",
            recent_sentiment=0.8
        )
        # Same state should have zero distance
        assert state1.distance_to(state2) == 0.0
        
        state3 = StateSnapshot(
            mood="angry",
            affinity=-0.5,
            relationship="enemy",
            recent_sentiment=-0.8
        )
        # Different state should have positive distance
        assert state1.distance_to(state3) > 0.0


class TestHandAuthoredRules:
    """Test hand-authored transition rules"""
    
    def test_mutual_insult(self):
        """Test mutual insult rule"""
        rules = HandAuthoredRules()
        state = StateSnapshot(
            mood="neutral",
            affinity=0.0,
            relationship="stranger",
            recent_sentiment=0.0
        )
        predicted = rules.predict(
            state, NPCAction.INSULT, PlayerSignal.INSULT
        )
        assert predicted is not None
        assert predicted.mood == "angry"
        assert predicted.affinity < 0
        assert predicted.recent_sentiment < 0
    
    def test_mutual_compliment(self):
        """Test mutual compliment rule"""
        rules = HandAuthoredRules()
        state = StateSnapshot(
            mood="neutral",
            affinity=0.0,
            relationship="stranger",
            recent_sentiment=0.0
        )
        predicted = rules.predict(
            state, NPCAction.COMPLIMENT, PlayerSignal.COMPLIMENT
        )
        assert predicted is not None
        assert predicted.mood == "happy"
        assert predicted.affinity > 0
    
    def test_escalate_to_combat(self):
        """Test escalation to combat rule"""
        rules = HandAuthoredRules()
        state = StateSnapshot(
            mood="neutral",
            affinity=0.0,
            relationship="stranger",
            recent_sentiment=0.0,
            combat_active=False
        )
        predicted = rules.predict(
            state, NPCAction.THREATEN, PlayerSignal.THREATEN
        )
        assert predicted is not None
        assert predicted.combat_active == True
        assert predicted.affinity == -1.0
        assert predicted.relationship == "enemy"
    
    def test_no_rule_returns_none(self):
        """Test that no matching rule returns None"""
        rules = HandAuthoredRules()
        state = StateSnapshot(
            mood="neutral",
            affinity=0.0,
            relationship="stranger",
            recent_sentiment=0.0
        )
        # No rule for this combination
        predicted = rules.predict(
            state, NPCAction.GREET, PlayerSignal.QUESTION
        )
        assert predicted is None


class TestRetrievalWorldModel:
    """Test retrieval-based world model"""
    
    def test_add_transition(self):
        """Test adding transitions"""
        model = RetrievalWorldModel(k_neighbors=3)
        state_before = StateSnapshot(
            mood="neutral", affinity=0.0, relationship="stranger",
            recent_sentiment=0.0
        )
        state_after = StateSnapshot(
            mood="happy", affinity=0.5, relationship="friend",
            recent_sentiment=0.8
        )
        transition = Transition(
            state_before=state_before,
            npc_action=NPCAction.GREET,
            player_signal=PlayerSignal.GREET,
            state_after=state_after,
            reward=1.0
        )
        model.add_transition(transition)
        assert model.get_transition_count() == 1
    
    def test_predict_with_similar_transitions(self):
        """Test prediction with similar transitions"""
        model = RetrievalWorldModel(k_neighbors=3)
        
        # Add some training data
        state_before = StateSnapshot(
            mood="neutral", affinity=0.0, relationship="stranger",
            recent_sentiment=0.0
        )
        state_after = StateSnapshot(
            mood="happy", affinity=0.5, relationship="friend",
            recent_sentiment=0.8
        )
        transition = Transition(
            state_before=state_before,
            npc_action=NPCAction.GREET,
            player_signal=PlayerSignal.GREET,
            state_after=state_after,
            reward=1.0
        )
        model.add_transition(transition)
        
        # Predict with similar state
        test_state = StateSnapshot(
            mood="neutral", affinity=0.1, relationship="stranger",
            recent_sentiment=0.1
        )
        predicted = model.predict(
            test_state, NPCAction.GREET, PlayerSignal.GREET
        )
        assert predicted is not None
        assert predicted.mood == "happy"
    
    def test_predict_no_transitions(self):
        """Test prediction with no transitions"""
        model = RetrievalWorldModel(k_neighbors=3)
        state = StateSnapshot(
            mood="neutral", affinity=0.0, relationship="stranger",
            recent_sentiment=0.0
        )
        predicted = model.predict(
            state, NPCAction.GREET, PlayerSignal.GREET
        )
        assert predicted is None
    
    def test_save_and_load(self):
        """Test saving and loading transitions"""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "transitions.json"
            
            # Create model and add transition
            model1 = RetrievalWorldModel(k_neighbors=3)
            state_before = StateSnapshot(
                mood="neutral", affinity=0.0, relationship="stranger",
                recent_sentiment=0.0
            )
            state_after = StateSnapshot(
                mood="happy", affinity=0.5, relationship="friend",
                recent_sentiment=0.8
            )
            transition = Transition(
                state_before=state_before,
                npc_action=NPCAction.GREET,
                player_signal=PlayerSignal.GREET,
                state_after=state_after,
                reward=1.0
            )
            model1.add_transition(transition)
            model1.save_to_file(path)
            
            # Load into new model
            model2 = RetrievalWorldModel(k_neighbors=3)
            model2.load_from_file(path)
            assert model2.get_transition_count() == 1


class TestWorldModel:
    """Test combined world model"""
    
    def test_hand_authored_priority(self):
        """Test that hand-authored rules have priority"""
        model = WorldModel(retrieval_k=3)
        state = StateSnapshot(
            mood="neutral", affinity=0.0, relationship="stranger",
            recent_sentiment=0.0, combat_active=False
        )
        predicted = model.predict(
            state, NPCAction.THREATEN, PlayerSignal.THREATEN
        )
        # Hand-authored rule should trigger combat
        assert predicted.combat_active == True
    
    def test_fallback_to_retrieval(self):
        """Test fallback to retrieval when no hand-authored rule"""
        model = WorldModel(retrieval_k=3)
        
        # Add training data
        state_before = StateSnapshot(
            mood="neutral", affinity=0.0, relationship="stranger",
            recent_sentiment=0.0
        )
        state_after = StateSnapshot(
            mood="happy", affinity=0.5, relationship="friend",
            recent_sentiment=0.8
        )
        model.record_transition(
            state_before, NPCAction.GREET, PlayerSignal.GREET,
            state_after, reward=1.0
        )
        
        # Predict (no hand-authored rule for this)
        test_state = StateSnapshot(
            mood="neutral", affinity=0.1, relationship="stranger",
            recent_sentiment=0.1
        )
        predicted = model.predict(
            test_state, NPCAction.GREET, PlayerSignal.GREET
        )
        assert predicted is not None
        assert predicted.mood == "happy"
    
    def test_no_prediction_returns_unchanged(self):
        """Test that no prediction returns unchanged state"""
        model = WorldModel(retrieval_k=3)
        state = StateSnapshot(
            mood="neutral", affinity=0.0, relationship="stranger",
            recent_sentiment=0.0
        )
        predicted = model.predict(
            state, NPCAction.GREET, PlayerSignal.QUESTION
        )
        # Should return state unchanged
        assert predicted.mood == state.mood
        assert predicted.affinity == state.affinity


class TestUtilityFunction:
    """Test utility function"""
    
    def test_score_positive_state(self):
        """Test scoring a positive state"""
        util = UtilityFunction()
        state = StateSnapshot(
            mood="happy",
            affinity=0.8,
            relationship="friend",
            recent_sentiment=0.9,
            trust_level=0.7,
            fear_level=0.0,
            quest_active=True
        )
        score = util.score(state)
        assert score > 0  # Should be positive
    
    def test_score_negative_state(self):
        """Test scoring a negative state"""
        util = UtilityFunction()
        state = StateSnapshot(
            mood="angry",
            affinity=-0.8,
            relationship="enemy",
            recent_sentiment=-0.9,
            trust_level=0.0,
            fear_level=0.8,
            combat_active=True
        )
        score = util.score(state)
        assert score < 0  # Should be negative
    
    def test_calculate_risk_combat(self):
        """Test risk calculation for combat"""
        util = UtilityFunction()
        state = StateSnapshot(
            mood="angry",
            affinity=-0.5,
            relationship="enemy",
            recent_sentiment=-0.5,
            combat_active=True
        )
        risk = util.calculate_risk(state)
        assert risk > 0.5  # Combat is risky
    
    def test_calculate_risk_safe(self):
        """Test risk calculation for safe state"""
        util = UtilityFunction()
        state = StateSnapshot(
            mood="happy",
            affinity=0.5,
            relationship="friend",
            recent_sentiment=0.5,
            combat_active=False,
            fear_level=0.0
        )
        risk = util.calculate_risk(state)
        assert risk < 0.3  # Should be low risk


class TestActionScorer:
    """Test action scorer"""
    
    def test_propose_candidates(self):
        """Test proposing candidate actions"""
        world_model = WorldModel(retrieval_k=3)
        scorer = ActionScorer(world_model)
        state = StateSnapshot(
            mood="neutral", affinity=0.0, relationship="stranger",
            recent_sentiment=0.0
        )
        candidates = scorer.propose_candidates(
            state, PlayerSignal.GREET, max_candidates=5
        )
        assert len(candidates) > 0
        assert len(candidates) <= 5
    
    def test_score_action(self):
        """Test scoring a single action"""
        world_model = WorldModel(retrieval_k=3)
        scorer = ActionScorer(world_model)
        state = StateSnapshot(
            mood="neutral", affinity=0.0, relationship="stranger",
            recent_sentiment=0.0
        )
        score = scorer.score_action(
            state, NPCAction.GREET, PlayerSignal.GREET
        )
        assert isinstance(score, ActionScore)
        assert score.action == NPCAction.GREET
        assert hasattr(score, 'utility_score')
        assert hasattr(score, 'risk_score')
        assert hasattr(score, 'total_score')
    
    def test_score_candidates(self):
        """Test scoring multiple candidates"""
        world_model = WorldModel(retrieval_k=3)
        scorer = ActionScorer(world_model)
        state = StateSnapshot(
            mood="neutral", affinity=0.0, relationship="stranger",
            recent_sentiment=0.0
        )
        candidates = [NPCAction.GREET, NPCAction.AGREE, NPCAction.APOLOGIZE]
        scores = scorer.score_candidates(state, PlayerSignal.GREET, candidates)
        assert len(scores) == len(candidates)
        # Should be sorted by total_score descending
        for i in range(len(scores) - 1):
            assert scores[i].total_score >= scores[i + 1].total_score
    
    def test_select_best_action(self):
        """Test selecting best action"""
        world_model = WorldModel(retrieval_k=3)
        scorer = ActionScorer(world_model)
        state = StateSnapshot(
            mood="neutral", affinity=0.0, relationship="stranger",
            recent_sentiment=0.0
        )
        best = scorer.select_best_action(state, PlayerSignal.GREET)
        assert best is not None
        assert isinstance(best, ActionScore)


class TestDecisionPipeline:
    """Test decision pipeline"""
    
    def test_decide(self):
        """Test making a decision"""
        world_model = WorldModel(retrieval_k=3)
        pipeline = DecisionPipeline(world_model)
        state = StateSnapshot(
            mood="neutral", affinity=0.0, relationship="stranger",
            recent_sentiment=0.0
        )
        decision = pipeline.decide(state, PlayerSignal.GREET, num_candidates=5)
        assert decision is not None
        assert isinstance(decision, ActionScore)
        assert hasattr(decision, 'action')
        assert hasattr(decision, 'predicted_state')
    
    def test_record_outcome(self):
        """Test recording outcome for learning"""
        world_model = WorldModel(retrieval_k=3)
        pipeline = DecisionPipeline(world_model)
        
        state_before = StateSnapshot(
            mood="neutral", affinity=0.0, relationship="stranger",
            recent_sentiment=0.0
        )
        state_after = StateSnapshot(
            mood="happy", affinity=0.5, relationship="friend",
            recent_sentiment=0.8
        )
        
        pipeline.record_outcome(
            state_before, NPCAction.GREET, PlayerSignal.GREET,
            state_after, reward=1.0
        )
        
        # Should have recorded transition
        assert world_model.get_transition_count() == 1


class TestIntegration:
    """Integration tests for world model system"""
    
    def test_full_decision_cycle(self):
        """Test full decision cycle with learning"""
        world_model = WorldModel(retrieval_k=3)
        pipeline = DecisionPipeline(world_model)
        
        # Initial state
        state = StateSnapshot(
            mood="neutral", affinity=0.0, relationship="stranger",
            recent_sentiment=0.0
        )
        
        # Make decision
        decision = pipeline.decide(state, PlayerSignal.GREET)
        assert decision is not None
        
        # Simulate outcome
        new_state = StateSnapshot(
            mood="happy", affinity=0.5, relationship="friend",
            recent_sentiment=0.8
        )
        
        # Record outcome
        pipeline.record_outcome(
            state, decision.action, PlayerSignal.GREET,
            new_state, reward=1.0
        )
        
        # Verify learning
        assert world_model.get_transition_count() == 1
        
        # Next decision should use learned transition
        next_decision = pipeline.decide(new_state, PlayerSignal.COMPLIMENT)
        assert next_decision is not None
    
    def test_hand_authored_overrides_retrieval(self):
        """Test that hand-authored rules override retrieval"""
        world_model = WorldModel(retrieval_k=3)
        
        # Add retrieval data that contradicts hand-authored rule
        state_before = StateSnapshot(
            mood="neutral", affinity=0.0, relationship="stranger",
            recent_sentiment=0.0, combat_active=False
        )
        state_after = StateSnapshot(
            mood="happy", affinity=0.5, relationship="friend",
            recent_sentiment=0.8, combat_active=False
        )
        world_model.record_transition(
            state_before, NPCAction.THREATEN, PlayerSignal.THREATEN,
            state_after, reward=1.0
        )
        
        # Predict - hand-authored rule should still trigger combat
        predicted = world_model.predict(
            state_before, NPCAction.THREATEN, PlayerSignal.THREATEN
        )
        
        # Hand-authored rule should override retrieval
        assert predicted.combat_active == True
