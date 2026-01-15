#!/usr/bin/env python3
"""
Demo script showing how to use the RFSN components:
1. LLM sub-prompt template
2. Bandit learner
3. Integration patterns

This demonstrates the complete flow from observation to dialogue realization.
"""

import json
import sys
from pathlib import Path

# Add Python directory to path
sys.path.insert(0, str(Path(__file__).parent / "Python"))

from bandit_learner import StateActionBandit, BanditConfig


def load_prompt_template():
    """Load the LLM sub-prompt template."""
    template_path = Path(__file__).parent / "llm_subprompt_template.txt"
    with open(template_path, 'r') as f:
        return f.read()


def build_dialogue_prompt(template, **kwargs):
    """Build a dialogue prompt from the template with variable substitution."""
    safe = {}
    for k, v in kwargs.items():
        if v is None:
            safe[k] = ""
        else:
            s = str(v)
            s = s.replace("{", "{{").replace("}", "}}")
            safe[k] = s
    return template.format(**safe)


def demo_bandit_learning():
    """Demonstrate the bandit learner in action."""
    print("=" * 70)
    print("BANDIT LEARNER DEMONSTRATION")
    print("=" * 70)
    print()
    
    # Initialize bandit with Thompson sampling
    config = BanditConfig(
        mode="thompson",
        thompson_binary=True,
        epsilon=0.1,
        min_trials_before_exploit=3
    )
    
    bandit = StateActionBandit("demo_bandit_state.json", config)
    
    # Simulate learning across different NPC states
    states_actions = {
        "FRIENDLY": ["GREET", "HELP", "EXPLAIN", "COMPLIMENT"],
        "ALERT": ["WARN", "INQUIRE", "EXPLAIN"],
        "HOSTILE": ["THREATEN", "WARN", "FLEE"],
    }
    
    print("Learning optimal actions for each state...")
    print()
    
    # Simulate interactions
    for state, actions in states_actions.items():
        print(f"State: {state}")
        print(f"Available actions: {actions}")
        
        # Simulate 20 interactions
        for turn in range(20):
            action = bandit.select_action(state, actions)
            
            # Simulate reward based on action quality for this state
            if state == "FRIENDLY":
                reward = 1.0 if action in ["GREET", "HELP"] else 0.3
            elif state == "ALERT":
                reward = 1.0 if action == "WARN" else 0.5
            else:  # HOSTILE
                reward = 1.0 if action in ["WARN", "FLEE"] else -0.5
            
            bandit.update(state, action, reward)
        
        # Show learned preferences
        snapshot = bandit.snapshot()
        print(f"  Learned action preferences:")
        for action in actions:
            stats = snapshot[state][action]
            print(f"    {action}: n={stats['n']}, mean={stats['value_sum']/stats['n']:.2f}")
        print()
    
    print("Learning complete!")
    print()
    
    # Demonstrate selection after learning
    print("Testing learned policy:")
    for state, actions in states_actions.items():
        action = bandit.select_action(state, actions)
        print(f"  {state} → {action}")
    print()
    
    return bandit


def demo_prompt_template():
    """Demonstrate the LLM sub-prompt template."""
    print("=" * 70)
    print("LLM SUB-PROMPT TEMPLATE DEMONSTRATION")
    print("=" * 70)
    print()
    
    template = load_prompt_template()
    
    # Build a sample prompt
    prompt = build_dialogue_prompt(
        template,
        npc_name="Bjorlam",
        npc_role="Carriage driver",
        setting="Skyrim roadside",
        personality_vector="blunt, pragmatic, road-weary",
        speech_style="short sentences, common speech",
        rfsn_state="FRIENDLY",
        action_id="GREET",
        action_intent="Welcome the player and offer carriage services.",
        allowed_tone="warm but business-like",
        dialogue_constraints="- Do not mention specific quest details\n- Keep prices vague",
        player_utterance="Hello, can you take me somewhere?",
        facts_bullets="- Bjorlam is a carriage driver\n- He travels between major cities\n- Weather is clear today",
        recent_events_bullets="- Player approached carriage -> NPC became FRIENDLY\n- Player greeted NPC politely",
        verbosity="short",
        include_question="true",
        end_with="question"
    )
    
    print("Generated prompt for LLM:")
    print("-" * 70)
    print(prompt)
    print("-" * 70)
    print()
    
    print("This prompt would be sent to the LLM to generate dialogue.")
    print("Expected output: 1-3 sentences spoken by the NPC.")
    print()


def demo_integration_flow():
    """Demonstrate the complete integration flow."""
    print("=" * 70)
    print("COMPLETE INTEGRATION FLOW")
    print("=" * 70)
    print()
    
    # Step 1: Observation from game engine
    observation = {
        "t": 1736962800.123,
        "npc_id": "npc_guard_01",
        "scene_id": "whiterun_gate",
        "player": {
            "distance": 3.5,
            "facing_dot": 0.85,
            "is_weapon_drawn": False,
            "last_utterance": "I'm looking for work."
        },
        "world": {
            "threat_level": 0.0,
            "noise": 0.2,
            "combat_nearby": False
        },
        "flags": ["player_in_dialogue_range"]
    }
    
    print("Step 1: Game Engine Observation")
    print(json.dumps(observation, indent=2))
    print()
    
    # Step 2: RFSN decision (using bandit learner)
    config = BanditConfig(thompson_binary=True, epsilon=0.1)
    bandit = StateActionBandit("demo_integration.json", config)
    
    # Pre-train with some history
    for _ in range(10):
        bandit.update("FRIENDLY", "HELP", 0.8)
    
    state = "FRIENDLY"
    actions = ["GREET", "HELP", "EXPLAIN", "WARN"]
    selected_action = bandit.select_action(state, actions)
    
    decision = {
        "npc_id": "npc_guard_01",
        "state": state,
        "action_id": selected_action,
        "action_intent": "Offer the player information about available work.",
        "dialogue_constraints": ["no quest spoilers", "be professional"],
        "facts": [
            "NPC is a city guard",
            "Player is at the city gate",
            "City is peaceful"
        ],
        "cooldowns": {selected_action: 8.0}
    }
    
    print("Step 2: RFSN Decision (using Bandit Learner)")
    print(json.dumps(decision, indent=2))
    print()
    
    # Step 3: LLM realizes dialogue
    template = load_prompt_template()
    prompt = build_dialogue_prompt(
        template,
        npc_name="Guard",
        npc_role="City Guard",
        setting="Whiterun gate",
        personality_vector="dutiful, professional, helpful",
        speech_style="formal but friendly",
        rfsn_state=decision["state"],
        action_id=decision["action_id"],
        action_intent=decision["action_intent"],
        allowed_tone="professional",
        dialogue_constraints="\n".join(f"- {c}" for c in decision["dialogue_constraints"]),
        player_utterance=observation["player"]["last_utterance"],
        facts_bullets="\n".join(f"- {f}" for f in decision["facts"]),
        recent_events_bullets="- Player approached guard peacefully",
        verbosity="short",
        include_question="false",
        end_with="none"
    )
    
    print("Step 3: LLM Sub-Prompt (snippet)")
    print("-" * 70)
    print(prompt[:500] + "...")
    print("-" * 70)
    print()
    
    # Step 4: Execution report
    execution_report = {
        "npc_id": "npc_guard_01",
        "action_id": selected_action,
        "executed": True,
        "outcome": {
            "player_engaged": True,
            "player_left": False,
            "combat_started": False
        }
    }
    
    print("Step 4: Execution Report from Game Engine")
    print(json.dumps(execution_report, indent=2))
    print()
    
    # Step 5: Reward calculation and learning update
    if execution_report["outcome"]["player_engaged"]:
        reward = 0.8
    elif execution_report["outcome"]["combat_started"]:
        reward = -1.0
    else:
        reward = 0.0
    
    bandit.update(state, selected_action, reward)
    
    print("Step 5: Learning Update")
    print(f"Reward: {reward}")
        """Run all demonstrations."""
        interactive = sys.stdin.isatty()

        print()
        print("╔" + "=" * 68 + "╗")
        print("║" + " RFSN ORCHESTRATOR - COMPONENT DEMONSTRATION ".center(68) + "║")
        print("╚" + "=" * 68 + "╝")
        print()

        # Demo 1: Prompt template
        demo_prompt_template()
        if interactive:
            input("Press Enter to continue to bandit learning demo...")
        print()

        # Demo 2: Bandit learning
        demo_bandit_learning()
        if interactive:
            input("Press Enter to continue to integration flow demo...")
        print()

        # Demo 3: Complete integration
    print()
    
    # Demo 2: Bandit learning
    demo_bandit_learning()
    input("Press Enter to continue to integration flow demo...")
    print()
    
    # Demo 3: Complete integration
    demo_integration_flow()
    
    print("=" * 70)
    print("DEMONSTRATION COMPLETE")
    print("=" * 70)
    print()
    print("Summary:")
    print("  ✓ LLM sub-prompt template loaded and formatted")
    print("  ✓ Bandit learner trained and tested")
    print("  ✓ Complete integration flow demonstrated")
    print()
    print("For more information:")
    print("  - See UNITY_NPC_SPEC.md for Unity integration")
    print("  - See SKYRIM_NPC_SPEC.md for Skyrim integration")
    print("  - See Python/bandit_learner.py for implementation details")
    print()


if __name__ == "__main__":
    main()
