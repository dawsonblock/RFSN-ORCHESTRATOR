"""
Tests for action_prompts module.
"""
import pytest
from prompting.action_prompts import build_action_subprompt
from world_model import NPCAction, PlayerSignal, StateSnapshot


def test_build_action_subprompt_basic():
    """Test basic subprompt generation."""
    state = StateSnapshot(
        mood="friendly",
        affinity=0.5,
        relationship="acquaintance",
        recent_sentiment=0.3
    )
    
    prompt = build_action_subprompt(
        NPCAction.GREET,
        state,
        PlayerSignal.GREET,
        {"npc_name": "Lydia"}
    )
    
    # Check for machine-readable header
    assert "[ACTION_SUBPROMPT]" in prompt
    assert "ACTION=greet" in prompt
    assert "MODE=dialogue" in prompt
    assert "SAFETY=" in prompt
    assert "STATE_SUMMARY=" in prompt
    assert "[/ACTION_SUBPROMPT]" in prompt
    
    # Check for style constraints
    assert "STYLE CONSTRAINTS:" in prompt
    assert "Lydia" in prompt
    assert "friendly" in prompt
    assert "acquaintance" in prompt
    
    # Check for action spec
    assert "ACTION: GREET" in prompt
    assert "INTENT:" in prompt
    assert "ALLOWED CONTENT:" in prompt
    assert "FORBIDDEN CONTENT:" in prompt


def test_build_action_subprompt_combat_mode():
    """Test that combat state triggers combat mode."""
    state = StateSnapshot(
        mood="hostile",
        affinity=-0.8,
        relationship="enemy",
        recent_sentiment=-0.9,
        combat_active=True
    )
    
    prompt = build_action_subprompt(
        NPCAction.ATTACK,
        state,
        PlayerSignal.THREATEN
    )
    
    assert "MODE=combat" in prompt
    assert "SAFETY=HIGH_RISK" in prompt
    assert "ACTION: ATTACK" in prompt


def test_build_action_subprompt_quest_mode():
    """Test that quest state triggers quest mode."""
    state = StateSnapshot(
        mood="determined",
        affinity=0.3,
        relationship="ally",
        recent_sentiment=0.2,
        quest_active=True
    )
    
    prompt = build_action_subprompt(
        NPCAction.EXPLAIN,
        state,
        PlayerSignal.QUESTION
    )
    
    assert "MODE=quest" in prompt
    assert "quest=True" in prompt


def test_build_action_subprompt_stealth_mode():
    """Test that high fear triggers stealth mode."""
    state = StateSnapshot(
        mood="fearful",
        affinity=0.0,
        relationship="stranger",
        recent_sentiment=-0.2,
        fear_level=0.8
    )
    
    prompt = build_action_subprompt(
        NPCAction.FLEE,
        state,
        PlayerSignal.THREATEN
    )
    
    assert "MODE=stealth" in prompt


def test_all_npc_actions_have_specs():
    """Test that all NPCAction values generate valid prompts."""
    state = StateSnapshot(
        mood="neutral",
        affinity=0.0,
        relationship="stranger",
        recent_sentiment=0.0
    )
    
    for action in NPCAction:
        prompt = build_action_subprompt(
            action,
            state,
            PlayerSignal.GREET
        )
        
        # Every action should have the basic structure
        assert "[ACTION_SUBPROMPT]" in prompt
        assert f"ACTION={action.value}" in prompt
        assert "STYLE CONSTRAINTS:" in prompt
        assert "ACTION:" in prompt


def test_state_summary_format():
    """Test that state summary has correct format."""
    state = StateSnapshot(
        mood="happy",
        affinity=0.75,
        relationship="friend",
        recent_sentiment=0.5,
        combat_active=False,
        quest_active=True
    )
    
    prompt = build_action_subprompt(
        NPCAction.GREET,
        state,
        PlayerSignal.GREET
    )
    
    # Check state summary format
    assert "STATE_SUMMARY=mood=happy|rel=friend|aff=+0.75|combat=False|quest=True" in prompt


def test_safety_levels():
    """Test safety level determination."""
    # High risk action
    state_peaceful = StateSnapshot(
        mood="neutral",
        affinity=0.0,
        relationship="stranger",
        recent_sentiment=0.0
    )
    
    prompt = build_action_subprompt(
        NPCAction.ATTACK,
        state_peaceful,
        PlayerSignal.GREET
    )
    assert "SAFETY=HIGH_RISK" in prompt
    
    # Low risk action
    prompt = build_action_subprompt(
        NPCAction.GREET,
        state_peaceful,
        PlayerSignal.GREET
    )
    assert "SAFETY=LOW_RISK" in prompt
    
    # Moderate risk due to state
    state_combat = StateSnapshot(
        mood="hostile",
        affinity=-0.5,
        relationship="enemy",
        recent_sentiment=-0.5,
        combat_active=True
    )
    
    prompt = build_action_subprompt(
        NPCAction.DEFEND,
        state_combat,
        PlayerSignal.ATTACK
    )
    assert "SAFETY=MODERATE_RISK" in prompt


def test_negative_affinity_formatting():
    """Test that negative affinity is formatted with sign."""
    state = StateSnapshot(
        mood="hostile",
        affinity=-0.65,
        relationship="rival",
        recent_sentiment=-0.4
    )
    
    prompt = build_action_subprompt(
        NPCAction.INSULT,
        state,
        PlayerSignal.INSULT
    )
    
    assert "-0.65" in prompt
    assert "aff=-0.65" in prompt


def test_prompt_contains_player_signal():
    """Test that the player signal is included in the prompt."""
    state = StateSnapshot(
        mood="curious",
        affinity=0.2,
        relationship="acquaintance",
        recent_sentiment=0.1
    )
    
    prompt = build_action_subprompt(
        NPCAction.INQUIRE,
        state,
        PlayerSignal.QUESTION
    )
    
    assert "Player just did: question" in prompt


def test_response_length_constraint():
    """Test that all prompts include response length constraints."""
    state = StateSnapshot(
        mood="neutral",
        affinity=0.0,
        relationship="stranger",
        recent_sentiment=0.0
    )
    
    prompt = build_action_subprompt(
        NPCAction.EXPLAIN,
        state,
        PlayerSignal.QUESTION
    )
    
    assert "1-3 sentences maximum" in prompt


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
