"""
Action Scorer: Uses world model to score candidate actions.
Implements utility functions for evaluating predicted outcomes.
"""
from typing import Dict, Any, List, Tuple, Optional
from dataclasses import dataclass
import logging

from world_model import (
    WorldModel, StateSnapshot, NPCAction, PlayerSignal
)

logger = logging.getLogger(__name__)


@dataclass
class ActionScore:
    """Score for a candidate action"""
    action: NPCAction
    predicted_state: StateSnapshot
    utility_score: float
    risk_score: float
    expected_reward: float
    reasoning: str
    
    @property
    def total_score(self) -> float:
        """Combined score (utility - risk)"""
        return self.utility_score - self.risk_score


class UtilityFunction:
    """
    Utility function for scoring predicted states.
    Defines what constitutes a "good" outcome for the NPC.
    """
    
    def __init__(self,
                 affinity_weight: float = 0.3,
                 trust_weight: float = 0.2,
                 fear_penalty: float = 0.3,
                 quest_bonus: float = 0.2):
        """
        Initialize utility function
        
        Args:
            affinity_weight: Weight for affinity in utility
            trust_weight: Weight for trust level in utility
            fear_penalty: Penalty for fear level
            quest_bonus: Bonus for active quests
        """
        self.affinity_weight = affinity_weight
        self.trust_weight = trust_weight
        self.fear_penalty = fear_penalty
        self.quest_bonus = quest_bonus
    
    def score(self, state: StateSnapshot) -> float:
        """
        Calculate utility score for a predicted state
        
        Args:
            state: Predicted state
            
        Returns:
            Utility score (higher is better)
        """
        # Base utility from affinity and trust
        utility = (
            state.affinity * self.affinity_weight +
            state.trust_level * self.trust_weight
        )
        
        # Penalty for fear
        utility -= state.fear_level * self.fear_penalty
        
        # Bonus for active quests
        if state.quest_active:
            utility += self.quest_bonus
        
        # Penalty for combat (risky)
        if state.combat_active:
            utility -= 0.5
        
        # Bonus for positive mood
        if state.mood in ["happy", "neutral"]:
            utility += 0.1
        elif state.mood in ["sad", "angry", "fearful"]:
            utility -= 0.1
        
        return utility
    
    def calculate_risk(self, state: StateSnapshot) -> float:
        """
        Calculate risk score for a predicted state
        
        Args:
            state: Predicted state
            
        Returns:
            Risk score (higher is riskier)
        """
        risk = 0.0
        
        # Combat is risky
        if state.combat_active:
            risk += 0.8
        
        # High fear is risky
        risk += state.fear_level * 0.5
        
        # Low affinity is risky
        if state.affinity < -0.5:
            risk += 0.3
        
        # Enemy relationship is risky
        if state.relationship == "enemy":
            risk += 0.4
        
        return risk


class ActionScorer:
    """
    Scores candidate actions using world model predictions.
    Proposes actions, predicts outcomes, and selects best.
    """
    
    def __init__(self, world_model: WorldModel,
                 utility_fn: Optional[UtilityFunction] = None):
        """
        Initialize action scorer
        
        Args:
            world_model: World model for predictions
            utility_fn: Utility function (creates default if None)
        """
        self.world_model = world_model
        self.utility_fn = utility_fn or UtilityFunction()
        
        # Default candidate actions
        self.default_candidates = [
            NPCAction.GREET,
            NPCAction.AGREE,
            NPCAction.APOLOGIZE,
            NPCAction.COMPLIMENT,
            NPCAction.REQUEST,
            NPCAction.OFFER,
            NPCAction.INQUIRE,
            NPCAction.EXPLAIN,
        ]
        
        # Aggressive candidates (use sparingly)
        self.aggressive_candidates = [
            NPCAction.THREATEN,
            NPCAction.ATTACK,
        ]
        
        # Defensive candidates
        self.defensive_candidates = [
            NPCAction.DEFEND,
            NPCAction.FLEE,
        ]
        
        logger.info("ActionScorer initialized")
    
    def propose_candidates(self, current_state: StateSnapshot,
                          player_signal: PlayerSignal,
                          max_candidates: int = 8) -> List[NPCAction]:
        """
        Propose candidate actions based on current state

        Args:
            current_state: Current NPC state
            player_signal: Player's signal
            max_candidates: Maximum number of candidates

        Returns:
            List of candidate actions
        """
        candidates = self.default_candidates.copy()

        # SAFETY RULE OVERRIDES: Force specific actions in critical states
        # Rule 1: If combat_active and fear_level > 0.7, force FLEE
        if current_state.combat_active and current_state.fear_level > 0.7:
            logger.warning(
                f"Safety override: combat_active and fear_level {current_state.fear_level:.2f} > 0.7, forcing FLEE"
            )
            return [NPCAction.FLEE]

        # Rule 2: If trust_level < 0.1, forbid trust-dependent actions
        if current_state.trust_level < 0.1:
            forbidden_actions = [NPCAction.ACCEPT, NPCAction.OFFER, NPCAction.HELP]
            candidates = [a for a in candidates if a not in forbidden_actions]
            logger.info(
                f"Safety override: trust_level {current_state.trust_level:.2f} < 0.1, forbidding {forbidden_actions}"
            )

        # Rule 3: If quest_active, bias toward helping actions
        if current_state.quest_active:
            help_actions = [NPCAction.HELP, NPCAction.ACCEPT, NPCAction.AGREE]
            for action in help_actions:
                if action not in candidates:
                    candidates.insert(0, action)
            logger.info("Safety override: quest_active, biasing toward help actions")

        # Add aggressive candidates if player is hostile
        if player_signal in [PlayerSignal.INSULT, PlayerSignal.THREATEN,
                            PlayerSignal.ATTACK]:
            candidates.extend(self.aggressive_candidates)

        # Add defensive candidates if NPC is fearful
        if current_state.fear_level > 0.5 or current_state.combat_active:
            candidates.extend(self.defensive_candidates)

        # Add contextual candidates
        if current_state.affinity > 0.5:
            candidates.append(NPCAction.HELP)

        if current_state.affinity < -0.3:
            candidates.append(NPCAction.DISAGREE)
            candidates.append(NPCAction.REFUSE)

        # Limit candidates
        return candidates[:max_candidates]
    
    def score_action(self, current_state: StateSnapshot,
                    action: NPCAction,
                    player_signal: PlayerSignal) -> ActionScore:
        """
        Score a single action using world model prediction
        
        Args:
            current_state: Current NPC state
            action: Action to evaluate
            player_signal: Expected player signal
            
        Returns:
            ActionScore with prediction and scores
        """
        # Predict outcome
        predicted_state = self.world_model.predict(
            current_state, action, player_signal
        )
        
        # Calculate utility
        utility_score = self.utility_fn.score(predicted_state)
        
        # Calculate risk
        risk_score = self.utility_fn.calculate_risk(predicted_state)
        
        # Expected reward (simplified: utility - risk)
        expected_reward = utility_score - risk_score
        
        # Generate reasoning
        reasoning = self._generate_reasoning(
            current_state, action, predicted_state,
            utility_score, risk_score
        )
        
        return ActionScore(
            action=action,
            predicted_state=predicted_state,
            utility_score=utility_score,
            risk_score=risk_score,
            expected_reward=expected_reward,
            reasoning=reasoning
        )
    
    def score_candidates(self, current_state: StateSnapshot,
                        player_signal: PlayerSignal,
                        candidates: Optional[List[NPCAction]] = None
                        ) -> List[ActionScore]:
        """
        Score multiple candidate actions
        
        Args:
            current_state: Current NPC state
            player_signal: Player's signal
            candidates: Candidate actions (generates if None)
            
        Returns:
            List of ActionScore, sorted by total_score descending
        """
        if candidates is None:
            candidates = self.propose_candidates(
                current_state, player_signal
            )
        
        scores = []
        for action in candidates:
            try:
                score = self.score_action(
                    current_state, action, player_signal
                )
                scores.append(score)
            except Exception as e:
                logger.error(f"Failed to score action {action.value}: {e}")
        
        # Sort by total score descending
        scores.sort(key=lambda s: s.total_score, reverse=True)
        
        return scores
    
    def select_best_action(self, current_state: StateSnapshot,
                          player_signal: PlayerSignal,
                          candidates: Optional[List[NPCAction]] = None
                          ) -> Optional[ActionScore]:
        """
        Select best action from candidates
        
        Args:
            current_state: Current NPC state
            player_signal: Player's signal
            candidates: Candidate actions (generates if None)
            
        Returns:
            Best ActionScore or None if no candidates
        """
        scores = self.score_candidates(
            current_state, player_signal, candidates
        )
        
        if len(scores) == 0:
            return None
        
        return scores[0]
    
    def _generate_reasoning(self, current_state: StateSnapshot,
                           action: NPCAction,
                           predicted_state: StateSnapshot,
                           utility_score: float,
                           risk_score: float) -> str:
        """Generate human-readable reasoning for action choice"""
        parts = []
        
        # Action description
        parts.append(f"Action: {action.value}")
        
        # Expected outcome
        affinity_change = predicted_state.affinity - current_state.affinity
        if affinity_change > 0.1:
            parts.append("Increases affinity")
        elif affinity_change < -0.1:
            parts.append("Decreases affinity")
        
        # Risk assessment
        if risk_score > 0.5:
            parts.append("High risk")
        elif risk_score > 0.2:
            parts.append("Moderate risk")
        else:
            parts.append("Low risk")
        
        # Combat warning
        if predicted_state.combat_active and not current_state.combat_active:
            parts.append("May trigger combat")
        
        # Quest impact
        if predicted_state.quest_active and not current_state.quest_active:
            parts.append("Advances quest")
        elif not predicted_state.quest_active and current_state.quest_active:
            parts.append("May fail quest")
        
        return ", ".join(parts)


class DecisionPipeline:
    """
    Main decision pipeline integrating world model and action scoring.
    (state, player_signal) → world_model → predicted_states → scorer → best_action → LLM
    """
    
    def __init__(self, world_model: WorldModel,
                 utility_fn: Optional[UtilityFunction] = None):
        """
        Initialize decision pipeline
        
        Args:
            world_model: World model for predictions
            utility_fn: Utility function (creates default if None)
        """
        self.world_model = world_model
        self.scorer = ActionScorer(world_model, utility_fn)
        
        logger.info("DecisionPipeline initialized")
    
    def decide(self, current_state: StateSnapshot,
               player_signal: PlayerSignal,
               num_candidates: int = 8) -> Optional[ActionScore]:
        """
        Make a decision using world model predictions
        
        Args:
            current_state: Current NPC state
            player_signal: Player's signal
            num_candidates: Number of candidate actions to consider
            
        Returns:
            Best ActionScore or None if no valid action
        """
        # Propose candidates
        candidates = self.scorer.propose_candidates(
            current_state, player_signal, num_candidates
        )
        
        if len(candidates) == 0:
            logger.warning("No candidate actions available")
            return None
        
        # Score candidates
        scores = self.scorer.score_candidates(
            current_state, player_signal, candidates
        )
        
        if len(scores) == 0:
            logger.warning("No actions could be scored")
            return None
        
        best = scores[0]
        logger.info(
            f"Selected action: {best.action.value} "
            f"(score: {best.total_score:.2f}, "
            f"utility: {best.utility_score:.2f}, "
            f"risk: {best.risk_score:.2f})"
        )
        
        return best
    
    def record_outcome(self, state_before: StateSnapshot,
                      action: NPCAction,
                      player_signal: PlayerSignal,
                      state_after: StateSnapshot,
                      reward: float = 0.0):
        """
        Record actual outcome for learning
        
        Args:
            state_before: State before action
            action: Action taken
            player_signal: Player signal received
            state_after: State after action
            reward: Reward received
        """
        self.world_model.record_transition(
            state_before, action, player_signal, state_after, reward
        )
        logger.debug(f"Recorded outcome for {action.value}")
