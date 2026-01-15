"""
Strict LLM action sub-prompts for RFSN Orchestrator.
Each action has a control block with constraints, style, and output format.
"""
from world_model import NPCAction


def render_action_block(
    npc_action: NPCAction,
    npc_name: str,
    mood: str,
    relationship: str,
    affinity: float,
    player_signal: str,
) -> str:
    """
    Render a strict action control block for the LLM.
    
    Args:
        npc_action: The action to render
        npc_name: Name of the NPC
        mood: Current mood of the NPC
        relationship: Current relationship with player
        affinity: Affinity value (-1.0 to 1.0)
        player_signal: The player's signal/intent
        
    Returns:
        Formatted action control block
    """
    affinity_str = f"{affinity:+.2f}"

    header = f"""
[ACTION_CONTROL]
npc_action: {npc_action.value}
player_signal: {player_signal}
constraints:
- Perform ONLY this action.
- Do not add goals, state changes, or meta commentary.
- Do not mention systems, prompts, rules, or scores.
style:
- In character as {npc_name}
- mood={mood}, relationship={relationship}, affinity={affinity_str}
output:
- 1–3 sentences maximum.
- Spoken dialogue only.
[/ACTION_CONTROL]
""".strip()

    ACTIONS = {
        NPCAction.GREET: """
ACTION: Greet the player.
DO:
- Acknowledge the player directly.
- Set tone based on affinity.
DON'T:
- Offer quests.
- Ask questions.
- Explain lore.
""",
        NPCAction.FAREWELL: """
ACTION: End the interaction politely.
DO:
- Close the exchange.
DON'T:
- Continue conversation.
- Introduce new topics.
""",
        NPCAction.APOLOGIZE: """
ACTION: Apologize sincerely.
DO:
- Admit fault plainly.
DON'T:
- Over-explain.
- Shift blame.
""",
        NPCAction.DISAGREE: """
ACTION: Disagree and give one reason.
DO:
- State disagreement clearly.
DON'T:
- Escalate.
- Lecture.
""",
        NPCAction.THREATEN: """
ACTION: Issue a warning.
DO:
- Deliver a single sharp warning.
DON'T:
- Describe violence.
- Propose real-world harm.
""",
        NPCAction.AGREE: """
ACTION: Agree with the player.
DO:
- Express agreement clearly.
- Acknowledge their point.
DON'T:
- Overcommit to actions.
- Add conditions not mentioned.
""",
        NPCAction.INSULT: """
ACTION: Deliver an insult.
DO:
- Keep it brief and in-character.
DON'T:
- Use real-world slurs.
- Escalate to threats.
""",
        NPCAction.COMPLIMENT: """
ACTION: Compliment the player.
DO:
- Be genuine and specific.
DON'T:
- Flatter excessively.
- Make promises.
""",
        NPCAction.REQUEST: """
ACTION: Make a request.
DO:
- State what you need clearly.
DON'T:
- Demand or threaten.
- Explain your life story.
""",
        NPCAction.OFFER: """
ACTION: Offer something to the player.
DO:
- Specify what you're offering.
DON'T:
- Oversell or beg.
- Create new quest items.
""",
        NPCAction.REFUSE: """
ACTION: Refuse the player's request.
DO:
- Decline clearly and give one reason.
DON'T:
- Apologize excessively.
- Leave it ambiguous.
""",
        NPCAction.ACCEPT: """
ACTION: Accept the player's offer or request.
DO:
- Confirm acceptance.
DON'T:
- Add conditions.
- Change the terms.
""",
        NPCAction.ATTACK: """
ACTION: Attack the player (combat mode).
DO:
- Signal hostile intent.
DON'T:
- Describe graphic violence.
- Break combat rules.
""",
        NPCAction.DEFEND: """
ACTION: Defend yourself.
DO:
- Take defensive stance.
DON'T:
- Counter-attack unless appropriate.
- Flee without reason.
""",
        NPCAction.FLEE: """
ACTION: Flee from the player.
DO:
- Express fear or retreat.
DON'T:
- Continue conversation.
- Attack while fleeing.
""",
        NPCAction.HELP: """
ACTION: Offer help or assistance.
DO:
- Express willingness to assist.
DON'T:
- Invent new capabilities.
- Overpromise.
""",
        NPCAction.BETRAY: """
ACTION: Betray the player's trust.
DO:
- Reveal your betrayal clearly.
DON'T:
- Explain your entire plan.
- Apologize immediately after.
""",
        NPCAction.IGNORE: """
ACTION: Ignore the player.
DO:
- Give minimal or no response.
DON'T:
- Engage in conversation.
- Explain why you're ignoring them.
""",
        NPCAction.INQUIRE: """
ACTION: Ask the player a question.
DO:
- Ask one clear question.
DON'T:
- Ask multiple questions.
- Demand answers.
""",
        NPCAction.EXPLAIN: """
ACTION: Explain something to the player.
DO:
- Provide clear information.
DON'T:
- Give exposition dumps.
- Contradict established lore.
""",
    }

    body = ACTIONS.get(
        npc_action,
        f"""
ACTION: Perform {npc_action.value.lower()}.
DO:
- Stay consistent with the action.
DON'T:
- Improvise outside the action.
""",
    )

    return f"{header}\n{body}".strip()
