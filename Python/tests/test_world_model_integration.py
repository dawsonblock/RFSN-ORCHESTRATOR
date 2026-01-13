"""
Tests for World Model and Action Scoring Integration
"""
import pytest
from world_model import (
    NPCAction, PlayerSignal, StateSnapshot
)
from action_scorer import ActionScorer, UtilityFunction
from state_machine import RFSNStateMachine


class TestActionScorerDeterminism:
    """Test that propose_candidates is deterministic"""

    def test_propose_candidates_deterministic(self):
        """
        Given the same state + player_signal, propose_candidate_actions()
        returns the same set.
        """
        # Create a mock world model (we don't need it for propose_candidates)
        class MockWorldModel:
            def predict(self, state, action, signal):
                return state

        scorer = ActionScorer(
            world_model=MockWorldModel(),
            utility_fn=UtilityFunction()
        )

        # Create a fixed state
        state = StateSnapshot(
            mood="neutral",
            affinity=0.0,
            relationship="stranger",
            recent_sentiment=0.0,
            combat_active=False,
            quest_active=False,
            trust_level=0.5,
            fear_level=0.0
        )

        player_signal = PlayerSignal.GREET

        # Call propose_candidates multiple times
        candidates1 = scorer.propose_candidates(state, player_signal)
        candidates2 = scorer.propose_candidates(state, player_signal)
        candidates3 = scorer.propose_candidates(state, player_signal)

        # All should return the same list
        assert candidates1 == candidates2 == candidates3
        assert len(candidates1) > 0


class TestScoringSanity:
    """Test scoring sanity for hostile states"""

    def test_hostile_state_deescalates(self):
        """
        For a hostile state, THREATEN should score lower than
        deescalating actions (unless intimidation is explicitly allowed).
        """
        # Create a mock world model
        class MockWorldModel:
            def predict(self, state, action, signal):
                # THREATEN makes things worse
                if action == NPCAction.THREATEN:
                    return StateSnapshot(
                        mood=state.mood,
                        affinity=max(-1.0, state.affinity - 0.3),
                        relationship=state.relationship,
                        recent_sentiment=-0.5,
                        combat_active=True,
                        quest_active=state.quest_active,
                        trust_level=state.trust_level - 0.2,
                        fear_level=state.fear_level + 0.1
                    )
                # APOLOGIZE makes things better
                elif action == NPCAction.APOLOGIZE:
                    return StateSnapshot(
                        mood="sad",
                        affinity=min(1.0, state.affinity + 0.2),
                        relationship=state.relationship,
                        recent_sentiment=0.3,
                        combat_active=False,
                        quest_active=state.quest_active,
                        trust_level=state.trust_level + 0.1,
                        fear_level=state.fear_level - 0.1
                    )
                return state

        scorer = ActionScorer(
            world_model=MockWorldModel(),
            utility_fn=UtilityFunction()
        )

        # Create a hostile state
        state = StateSnapshot(
            mood="angry",
            affinity=-0.6,
            relationship="enemy",
            recent_sentiment=-0.5,
            combat_active=False,
            quest_active=False,
            trust_level=0.2,
            fear_level=0.3
        )

        player_signal = PlayerSignal.INSULT

        # Score both actions
        threaten_score = scorer.score_action(state, NPCAction.THREATEN, player_signal)
        apologize_score = scorer.score_action(state, NPCAction.APOLOGIZE, player_signal)

        # APOLOGIZE should score higher (better utility, lower risk)
        assert apologize_score.total_score > threaten_score.total_score


class TestStateTransition:
    """Test authoritative state transitions"""

    def test_apply_transition_consistency(self):
        """
        Test that apply_transition produces consistent results
        and respects bounds.
        """
        state_machine = RFSNStateMachine()

        state_before = {
            "mood": "neutral",
            "affinity": 0.0,
            "relationship": "stranger",
            "playstyle": "balanced",
            "recent_sentiment": 0.0
        }

        # Apply a positive transition
        state_after = state_machine.apply_transition(
            state_before,
            player_signal="greet",
            npc_action="COMPLIMENT"
        )

        # Affinity should increase
        assert state_after["affinity"] > state_before["affinity"]
        # Should be bounded
        assert -1.0 <= state_after["affinity"] <= 1.0

        # Apply a negative transition
        state_after2 = state_machine.apply_transition(
            state_after,
            player_signal="insult",
            npc_action="THREATEN"
        )

        # Affinity should decrease
        assert state_after2["affinity"] < state_after["affinity"]
        # Should still be bounded
        assert -1.0 <= state_after2["affinity"] <= 1.0

    def test_apply_transition_bounds(self):
        """
        Test that apply_transition respects affinity bounds [-1, 1]
        """
        state_machine = RFSNStateMachine()

        # Start at maximum affinity
        state_max = {
            "mood": "happy",
            "affinity": 1.0,
            "relationship": "ally",
            "playstyle": "balanced",
            "recent_sentiment": 1.0
        }

        # Apply positive transition (should stay at 1.0)
        state_after = state_machine.apply_transition(
            state_max,
            player_signal="help",
            npc_action="HELP"
        )

        assert state_after["affinity"] == 1.0

        # Start at minimum affinity
        state_min = {
            "mood": "angry",
            "affinity": -1.0,
            "relationship": "enemy",
            "playstyle": "aggressive",
            "recent_sentiment": -1.0
        }

        # Apply negative transition (should stay at -1.0)
        state_after2 = state_machine.apply_transition(
            state_min,
            player_signal="threaten",
            npc_action="ATTACK"
        )

        assert state_after2["affinity"] == -1.0


class TestSafetyRules:
    """Test safety rule overrides"""

    def test_combat_fear_forces_flee(self):
        """
        If combat_active and fear_level > 0.7, force FLEE.
        """
        class MockWorldModel:
            def predict(self, state, action, signal):
                return state

        scorer = ActionScorer(
            world_model=MockWorldModel(),
            utility_fn=UtilityFunction()
        )

        # Create a high-fear combat state
        state = StateSnapshot(
            mood="fearful",
            affinity=-0.5,
            relationship="enemy",
            recent_sentiment=-0.8,
            combat_active=True,
            quest_active=False,
            trust_level=0.1,
            fear_level=0.8
        )

        player_signal = PlayerSignal.ATTACK

        # Should only return FLEE
        candidates = scorer.propose_candidates(state, player_signal)
        assert candidates == [NPCAction.FLEE]

    def test_low_trust_forbids_trust_actions(self):
        """
        If trust_level < 0.1, forbid trust-dependent actions.
        """
        class MockWorldModel:
            def predict(self, state, action, signal):
                return state

        scorer = ActionScorer(
            world_model=MockWorldModel(),
            utility_fn=UtilityFunction()
        )

        # Create a low-trust state
        state = StateSnapshot(
            mood="angry",
            affinity=-0.8,
            relationship="enemy",
            recent_sentiment=-0.7,
            combat_active=False,
            quest_active=False,
            trust_level=0.05,
            fear_level=0.2
        )

        player_signal = PlayerSignal.REQUEST

        # Should not contain trust-dependent actions
        candidates = scorer.propose_candidates(state, player_signal)
        assert NPCAction.ACCEPT not in candidates
        assert NPCAction.OFFER not in candidates
        assert NPCAction.HELP not in candidates

    def test_quest_active_biases_help(self):
        """
        If quest_active, bias toward helping actions.
        """
        class MockWorldModel:
            def predict(self, state, action, signal):
                return state

        scorer = ActionScorer(
            world_model=MockWorldModel(),
            utility_fn=UtilityFunction()
        )

        # Create a quest-active state
        state = StateSnapshot(
            mood="neutral",
            affinity=0.3,
            relationship="friend",
            recent_sentiment=0.2,
            combat_active=False,
            quest_active=True,
            trust_level=0.6,
            fear_level=0.1
        )

        player_signal = PlayerSignal.REQUEST

        # Help actions should be at the front
        candidates = scorer.propose_candidates(state, player_signal)
        assert candidates[0] in [NPCAction.HELP, NPCAction.ACCEPT, NPCAction.AGREE]
