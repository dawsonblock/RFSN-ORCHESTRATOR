"""
Reward Model: Computes scalar reward from observable signals
"""
from .schemas import RewardSignals
import logging

logger = logging.getLogger(__name__)


class RewardModel:
    """
    Computes reward signal from observable turn outcomes
    Uses simple weighted sum of binary signals
    """
    
    # Reward weights for each signal
    CONTRADICTION_PENALTY = -1.0
    USER_CORRECTION_PENALTY = -0.7
    TTS_OVERRUN_PENALTY = -0.2
    CONVERSATION_CONTINUED_REWARD = +0.4
    FOLLOW_UP_QUESTION_REWARD = +0.2
    
    # Reward bounds
    MIN_REWARD = -2.0
    MAX_REWARD = +2.0
    
    def compute(self, signals: RewardSignals) -> float:
        """
        Compute scalar reward from signals
        
        Args:
            signals: RewardSignals with boolean flags
            
        Returns:
            Clamped reward in [-2.0, 2.0]
        """
        reward = 0.0
        
        # Negative signals
        if signals.contradiction_detected:
            reward += self.CONTRADICTION_PENALTY
            logger.debug(f"Contradiction detected: {self.CONTRADICTION_PENALTY}")
        
        if signals.user_correction:
            reward += self.USER_CORRECTION_PENALTY
            logger.debug(f"User correction: {self.USER_CORRECTION_PENALTY}")
        
        if signals.tts_overrun:
            reward += self.TTS_OVERRUN_PENALTY
            logger.debug(f"TTS overrun: {self.TTS_OVERRUN_PENALTY}")
        
        # Positive signals
        if signals.conversation_continued:
            reward += self.CONVERSATION_CONTINUED_REWARD
            logger.debug(f"Conversation continued: {self.CONVERSATION_CONTINUED_REWARD}")
        
        if signals.follow_up_question:
            reward += self.FOLLOW_UP_QUESTION_REWARD
            logger.debug(f"Follow-up question: {self.FOLLOW_UP_QUESTION_REWARD}")
        
        # Clamp to bounds
        reward = max(self.MIN_REWARD, min(self.MAX_REWARD, reward))
        
        logger.info(f"Computed reward: {reward:.2f}")
        return reward
    
    @staticmethod
    def detect_user_correction(user_text: str) -> bool:
        """
        Detect if user is correcting the NPC
        
        Args:
            user_text: User's input text
            
        Returns:
            True if correction detected
        """
        correction_phrases = [
            "no", "wrong", "not true", "that's not what i said",
            "incorrect", "you're mistaken", "actually", "false"
        ]
        user_lower = user_text.lower()
        return any(phrase in user_lower for phrase in correction_phrases)
    
    @staticmethod
    def detect_follow_up_question(user_text: str) -> bool:
        """
        Detect if user asked a follow-up question
        
        Args:
            user_text: User's input text
            
        Returns:
            True if question detected
        """
        question_markers = ["?", "what", "why", "how", "when", "where", "who"]
        user_lower = user_text.lower()
        return any(marker in user_lower for marker in question_markers)
