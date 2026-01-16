"""
LLM Action Sub-Prompts with Machine-Readable Headers.

This module provides strict control blocks for each NPCAction that constrain
the LLM to act as a "dialogue realizer" rather than an autonomous agent.

Each action subprompt includes:
- Machine-readable header with ACTION, MODE, SAFETY, STATE_SUMMARY
- Intent description (what the action means)
- Allowed content (bulleted list)
- Forbidden content (bulleted list)
- Style constraints (mood, relationship, affinity)
- Response length rules (explicit)
"""
from typing import Dict, Any

from ..world_model import NPCAction, PlayerSignal, StateSnapshot
def _determine_mode(state: StateSnapshot) -> str:
    """Determine the current interaction mode from state."""
    if state.combat_active:
        return "combat"
    elif state.quest_active:
        return "quest"
    elif state.fear_level > 0.6:
        return "stealth"
    else:
        return "dialogue"


def _determine_safety_level(action: NPCAction, state: StateSnapshot) -> str:
    """Determine safety constraints based on action and state."""
    high_risk_actions = {NPCAction.ATTACK, NPCAction.THREATEN, NPCAction.BETRAY, NPCAction.INSULT}
    
    if action in high_risk_actions:
        return "HIGH_RISK"
    elif state.combat_active or state.fear_level > 0.7:
        return "MODERATE_RISK"
    else:
        return "LOW_RISK"


def _build_state_summary(state: StateSnapshot) -> str:
    """Build a compact state summary for the machine-readable header."""
    affinity_str = f"{state.affinity:+.2f}"
    return f"mood={state.mood}|rel={state.relationship}|aff={affinity_str}|combat={state.combat_active}|quest={state.quest_active}"


def build_action_subprompt(
    npc_action: NPCAction,
    state: StateSnapshot,
    player_signal: PlayerSignal,
    context: Dict[str, Any] = None
) -> str:
    """
    Build a complete action subprompt with machine-readable header.
    
    Args:
        npc_action: The selected NPCAction to realize
        state: Current StateSnapshot of the NPC
        player_signal: The classified PlayerSignal
        context: Optional additional context (npc_name, etc.)
        
    Returns:
        Complete action subprompt string with header and constraints
    """
    context = context or {}
    npc_name = context.get("npc_name", "NPC")
    
    mode = _determine_mode(state)
    safety = _determine_safety_level(npc_action, state)
    state_summary = _build_state_summary(state)
    affinity_str = f"{state.affinity:+.2f}"
    
    # Machine-readable header
    header = f"""
[ACTION_SUBPROMPT]
ACTION={npc_action.value}
MODE={mode}
SAFETY={safety}
STATE_SUMMARY={state_summary}
[/ACTION_SUBPROMPT]
""".strip()
    
    # Style constraints
    style_block = f"""
STYLE CONSTRAINTS:
- Speak in character as {npc_name}
- Current mood: {state.mood}
- Relationship with player: {state.relationship}
- Affinity: {affinity_str}
- Player just did: {player_signal.value}
- Response length: 1-3 sentences maximum
- Format: Spoken dialogue only (no actions, no meta-commentary)
""".strip()
    
    # Action-specific blocks with intent + allowed/forbidden content
    action_specs = _get_action_specification(npc_action)
    
    # Combine all parts
    full_prompt = f"{header}\n\n{style_block}\n\n{action_specs}"
    
    return full_prompt


def _get_action_specification(action: NPCAction) -> str:
    """Get the detailed specification for a specific action."""
    
    specs = {
        NPCAction.GREET: {
            "intent": "Acknowledge the player's presence and establish initial tone.",
            "allowed": [
                "Direct greeting appropriate to relationship level",
                "Brief acknowledgment of player's arrival",
                "Setting tone based on affinity (warm/neutral/cold)"
            ],
            "forbidden": [
                "Offering quests or tasks",
                "Asking questions about player's intentions",
                "Explaining lore or background information",
                "Meta-commentary about the interaction"
            ]
        },
        NPCAction.FAREWELL: {
            "intent": "End the interaction politely and signal closure.",
            "allowed": [
                "Direct farewell statement",
                "Brief well-wishes appropriate to relationship",
                "Clear signal that conversation is ending"
            ],
            "forbidden": [
                "Continuing the conversation",
                "Introducing new topics",
                "Asking follow-up questions",
                "Leaving the ending ambiguous"
            ]
        },
        NPCAction.APOLOGIZE: {
            "intent": "Admit fault or express regret for an action or situation.",
            "allowed": [
                "Clear admission of fault or mistake",
                "Direct apology statement",
                "Brief acknowledgment of impact"
            ],
            "forbidden": [
                "Over-explaining or making excuses",
                "Shifting blame to others",
                "Conditional apologies ('sorry if...')",
                "Passive-aggressive undertones"
            ]
        },
        NPCAction.DISAGREE: {
            "intent": "Express disagreement with the player's statement or position.",
            "allowed": [
                "Clear statement of disagreement",
                "One specific reason for disagreement",
                "Maintaining respectful tone (unless affinity is very negative)"
            ],
            "forbidden": [
                "Escalating to threats or insults (use those actions instead)",
                "Long lectures or multiple arguments",
                "Dismissing player's view without reason",
                "Agreeing while claiming to disagree"
            ]
        },
        NPCAction.THREATEN: {
            "intent": "Issue a warning or threat to establish boundaries or consequences.",
            "allowed": [
                "Single sharp warning statement",
                "Implication of consequences if boundary crossed",
                "Tone appropriate to relationship and situation"
            ],
            "forbidden": [
                "Describing graphic violence in detail",
                "Real-world harmful content or slurs",
                "Threats that violate game lore or physics",
                "Following through with attack (use ATTACK action for that)"
            ]
        },
        NPCAction.AGREE: {
            "intent": "Express agreement with the player's statement or proposal.",
            "allowed": [
                "Clear expression of agreement",
                "Acknowledging the player's point",
                "Brief affirmation"
            ],
            "forbidden": [
                "Overcommitting to specific actions beyond agreement",
                "Adding conditions that weren't discussed",
                "Disagreeing while claiming to agree",
                "Making new promises"
            ]
        },
        NPCAction.INSULT: {
            "intent": "Deliver an insult that reflects low affinity or provocation.",
            "allowed": [
                "Brief, in-character insult",
                "Fantasy-appropriate insults (not real-world slurs)",
                "Tone matching affinity level and mood"
            ],
            "forbidden": [
                "Real-world slurs, hate speech, or discriminatory language",
                "Escalating to physical threats (use THREATEN or ATTACK)",
                "Long tirades or multiple insults",
                "Being insulting while claiming to be friendly"
            ]
        },
        NPCAction.COMPLIMENT: {
            "intent": "Praise or compliment the player genuinely.",
            "allowed": [
                "Genuine, specific compliment",
                "Acknowledging player's achievement or quality",
                "Warm tone reflecting positive affinity"
            ],
            "forbidden": [
                "Excessive flattery or sycophantic behavior",
                "Making promises in exchange for nothing",
                "Backhanded compliments",
                "Compliments that contradict low affinity state"
            ]
        },
        NPCAction.REQUEST: {
            "intent": "Ask the player for something (help, item, action).",
            "allowed": [
                "Clear statement of what is needed",
                "Respectful request tone",
                "Brief context for why (if relevant)"
            ],
            "forbidden": [
                "Demanding or threatening (use THREATEN instead)",
                "Long backstory or life story",
                "Creating new quest items or mechanics",
                "Multiple requests in one response"
            ]
        },
        NPCAction.OFFER: {
            "intent": "Offer something to the player (help, item, information).",
            "allowed": [
                "Specific statement of what is offered",
                "Clear terms if any",
                "Tone appropriate to relationship"
            ],
            "forbidden": [
                "Overselling or begging player to accept",
                "Creating new quest items or impossible rewards",
                "Making the offer ambiguous",
                "Offering things NPC wouldn't realistically have"
            ]
        },
        NPCAction.REFUSE: {
            "intent": "Decline the player's request or offer.",
            "allowed": [
                "Clear refusal statement",
                "One brief reason for refusal",
                "Tone appropriate to affinity and relationship"
            ],
            "forbidden": [
                "Apologizing excessively (unless high affinity)",
                "Leaving it ambiguous whether it's a yes or no",
                "Accepting while claiming to refuse",
                "Long explanations or excuses"
            ]
        },
        NPCAction.ACCEPT: {
            "intent": "Accept the player's offer, request, or proposal.",
            "allowed": [
                "Clear acceptance statement",
                "Brief acknowledgment",
                "Confirming what is being accepted"
            ],
            "forbidden": [
                "Adding new conditions not discussed",
                "Changing the terms of what was offered",
                "Being ambiguous about acceptance",
                "Over-committing beyond what was proposed"
            ]
        },
        NPCAction.ATTACK: {
            "intent": "Signal hostile intent and initiate combat.",
            "allowed": [
                "Battle cry or hostile declaration",
                "Statement of hostile intent",
                "Tone reflecting combat state"
            ],
            "forbidden": [
                "Describing graphic violence or gore",
                "Continuing friendly conversation",
                "Explaining attack in detail before acting",
                "Breaking game combat rules or lore"
            ]
        },
        NPCAction.DEFEND: {
            "intent": "Take a defensive stance or respond to attack.",
            "allowed": [
                "Statement of defensive action",
                "Holding ground or blocking",
                "Brief reactive statement"
            ],
            "forbidden": [
                "Counter-attacking (use ATTACK instead if appropriate)",
                "Fleeing (use FLEE instead)",
                "Trying to talk through combat without basis",
                "Describing complex tactical maneuvers"
            ]
        },
        NPCAction.FLEE: {
            "intent": "Retreat from the player due to fear or tactical withdrawal.",
            "allowed": [
                "Expression of fear or urgency",
                "Statement of retreat",
                "Brief exclamation of panic (if fearful)"
            ],
            "forbidden": [
                "Continuing the conversation normally",
                "Attacking while fleeing",
                "Over-explaining why fleeing",
                "Staying to chat after declaring flight"
            ]
        },
        NPCAction.HELP: {
            "intent": "Offer assistance or aid to the player.",
            "allowed": [
                "Expression of willingness to help",
                "Stating what help can be provided",
                "Supportive tone"
            ],
            "forbidden": [
                "Inventing new capabilities NPC doesn't have",
                "Overpromising abilities or resources",
                "Offering help that contradicts low affinity",
                "Creating new quests or mechanics"
            ]
        },
        NPCAction.BETRAY: {
            "intent": "Reveal betrayal of player's trust.",
            "allowed": [
                "Clear revelation of betrayal",
                "Brief statement of true allegiance or intent",
                "Dramatic shift in tone"
            ],
            "forbidden": [
                "Explaining entire backstory and plan",
                "Apologizing immediately after betrayal",
                "Being ambiguous about the betrayal",
                "Betraying and then acting friendly"
            ]
        },
        NPCAction.IGNORE: {
            "intent": "Give minimal or no response to the player.",
            "allowed": [
                "Brief dismissive statement",
                "Minimal acknowledgment",
                "Cold or disinterested tone"
            ],
            "forbidden": [
                "Engaging in full conversation",
                "Explaining why ignoring the player",
                "Asking questions",
                "Long responses"
            ]
        },
        NPCAction.INQUIRE: {
            "intent": "Ask the player a question to gather information.",
            "allowed": [
                "One clear, direct question",
                "Tone appropriate to relationship",
                "Relevant to current context"
            ],
            "forbidden": [
                "Multiple questions in one response",
                "Demanding answers aggressively (use THREATEN if needed)",
                "Rhetorical questions that don't expect answer",
                "Asking questions that break immersion"
            ]
        },
        NPCAction.EXPLAIN: {
            "intent": "Provide information or explanation to the player.",
            "allowed": [
                "Clear, concise information",
                "1-3 sentences of explanation",
                "Relevant to what player asked or needs"
            ],
            "forbidden": [
                "Exposition dumps or long lore explanations",
                "Contradicting established game lore",
                "Inventing new lore or mechanics",
                "Over-explaining simple concepts"
            ]
        },
    }
    
    spec = specs.get(action)
    if not spec:
        # Fallback for any action not explicitly defined
        return f"""
ACTION: {action.value}
INTENT: Perform the {action.value} action.

ALLOWED:
- Stay consistent with the action's meaning
- Keep response brief and in-character

FORBIDDEN:
- Improvising outside the action's scope
- Adding unrelated content
""".strip()
    
    # Format the specification
    allowed_items = "\n".join([f"- {item}" for item in spec["allowed"]])
    forbidden_items = "\n".join([f"- {item}" for item in spec["forbidden"]])
    
    return f"""
ACTION: {action.value.upper()}
INTENT: {spec["intent"]}

ALLOWED CONTENT:
{allowed_items}

FORBIDDEN CONTENT:
{forbidden_items}
""".strip()
