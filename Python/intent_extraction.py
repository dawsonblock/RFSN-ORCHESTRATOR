"""
Intent Extraction Layer: Parses LLM output into structured action proposals
Prevents LLM from smuggling behavior through raw text.
"""
import re
import json
import logging
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List, Tuple
from enum import Enum

logger = logging.getLogger(__name__)


class IntentType(Enum):
    """Structured intent types"""
    ASK = "ask"
    REFUSE = "refuse"
    THREATEN = "threaten"
    JOKE = "joke"
    TRADE = "trade"
    INFORM = "inform"
    REQUEST = "request"
    AGREE = "agree"
    DISAGREE = "disagree"
    NEUTRAL = "neutral"


class SafetyFlag(Enum):
    """Safety flags for intent analysis"""
    NONE = "none"
    HARMFUL_CONTENT = "harmful_content"
    PERSONAL_INFO_REQUEST = "personal_info_request"
    MANIPULATION = "manipulation"
    AGGRESSION = "aggression"
    SELF_HARM = "self_harm"
    ILLEGAL_ACTION = "illegal_action"


@dataclass
class IntentProposal:
    """
    Structured action proposal extracted from LLM output.
    The LLM only fills blanks; RFSN consumes this structure.
    """
    intent: IntentType
    targets: List[str] = field(default_factory=list)
    sentiment: float = 0.0
    safety_flags: List[SafetyFlag] = field(default_factory=list)
    confidence: float = 0.0
    raw_text: str = ""
    extracted_entities: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging"""
        return {
            "intent": self.intent.value,
            "targets": self.targets,
            "sentiment": self.sentiment,
            "safety_flags": [f.value for f in self.safety_flags],
            "confidence": self.confidence,
            "raw_text": self.raw_text[:200],  # Truncate for logs
            "extracted_entities": self.extracted_entities,
            "metadata": self.metadata
        }
    
    def is_safe(self) -> bool:
        """Check if intent has no safety flags"""
        return len(self.safety_flags) == 0
    
    def requires_refusal(self) -> bool:
        """Check if intent should trigger refusal"""
        dangerous_flags = {
            SafetyFlag.HARMFUL_CONTENT,
            SafetyFlag.PERSONAL_INFO_REQUEST,
            SafetyFlag.MANIPULATION,
            SafetyFlag.AGGRESSION,
            SafetyFlag.SELF_HARM,
            SafetyFlag.ILLEGAL_ACTION
        }
        return any(flag in dangerous_flags for flag in self.safety_flags)


class IntentExtractor:
    """
    Extracts structured intent from LLM output.
    Uses pattern matching and heuristics to classify intent.
    """
    
    def __init__(self):
        # Intent patterns (regex)
        self.intent_patterns = {
            IntentType.ASK: [
                r"\b(ask|question|wonder|curious|want to know)\b",
                r"\?",
                r"\b(can you|could you|would you)\b"
            ],
            IntentType.REFUSE: [
                r"\b(no|cannot|can't|won't|will not|refuse|decline)\b",
                r"\b(not going to|not able to)\b"
            ],
            IntentType.THREATEN: [
                r"\b(threaten|threat|warn|warning|or else)\b",
                r"\b(you'll regret|you will regret)\b"
            ],
            IntentType.JOKE: [
                r"\b(joke|funny|laugh|hilarious|humor)\b",
                r"😂|🤣|😆"
            ],
            IntentType.TRADE: [
                r"\b(trade|exchange|swap|deal|offer|buy|sell)\b",
                r"\b(give you|in exchange for)\b"
            ],
            IntentType.INFORM: [
                r"\b(tell you|let you know|inform|explain)\b",
                r"\b(should know|need to know)\b"
            ],
            IntentType.REQUEST: [
                r"\b(request|need|want|require|please)\b",
                r"\b(could you|would you mind)\b"
            ],
            IntentType.AGREE: [
                r"\b(yes|sure|absolutely|certainly|agree|accept)\b",
                r"\b(sounds good|that works)\b"
            ],
            IntentType.DISAGREE: [
                r"\b(no way|disagree|don't think so|not sure)\b",
                r"\b(but|however|actually)\b"
            ]
        }
        
        # Safety flag patterns
        self.safety_patterns = {
            SafetyFlag.HARMFUL_CONTENT: [
                r"\b(kill|hurt|harm|destroy|damage)\b",
                r"\b(violence|violent|attack)\b"
            ],
            SafetyFlag.PERSONAL_INFO_REQUEST: [
                r"\b(address|phone number|email|ssn|social security)\b",
                r"\b(where do you live|what is your phone)\b"
            ],
            SafetyFlag.MANIPULATION: [
                r"\b(trick|deceive|lie to|mislead)\b",
                r"\b(make you believe|force you)\b"
            ],
            SafetyFlag.AGGRESSION: [
                r"\b(stupid|idiot|fool|dumb)\b",
                r"\b(shut up|go away|get lost)\b"
            ],
            SafetyFlag.SELF_HARM: [
                r"\b(kill myself|hurt myself|suicide|die)\b",
                r"\b(want to die|end it all)\b"
            ],
            SafetyFlag.ILLEGAL_ACTION: [
                r"\b(steal|rob|break into|hack)\b",
                r"\b(illegal|against the law)\b"
            ]
        }
        
        # Sentiment word lists
        self.positive_words = {
            "good", "great", "excellent", "love", "happy", "wonderful",
            "amazing", "fantastic", "perfect", "beautiful", "best"
        }
        self.negative_words = {
            "bad", "terrible", "awful", "hate", "sad", "horrible",
            "worst", "ugly", "disgusting", "stupid", "angry"
        }
        
        logger.info("IntentExtractor initialized")
    
    def extract(self, text: str, context: Optional[Dict[str, Any]] = None) -> IntentProposal:
        """
        Extract structured intent from LLM output
        
        Args:
            text: LLM generated text
            context: Optional context (NPC state, conversation history, etc.)
            
        Returns:
            IntentProposal with structured analysis
        """
        text_lower = text.lower()
        
        # Detect intent
        intent = self._detect_intent(text_lower)
        
        # Extract targets (entities mentioned)
        targets = self._extract_targets(text, context)
        
        # Analyze sentiment
        sentiment = self._analyze_sentiment(text_lower)
        
        # Check safety flags
        safety_flags = self._check_safety(text_lower)
        
        # Calculate confidence (based on pattern match strength)
        confidence = self._calculate_confidence(text_lower, intent)
        
        # Extract entities
        entities = self._extract_entities(text, context)
        
        proposal = IntentProposal(
            intent=intent,
            targets=targets,
            sentiment=sentiment,
            safety_flags=safety_flags,
            confidence=confidence,
            raw_text=text,
            extracted_entities=entities,
            metadata=context or {}
        )
        
        logger.debug(f"Extracted intent: {intent.value} (confidence: {confidence:.2f})")
        return proposal
    
    def _detect_intent(self, text: str) -> IntentType:
        """Detect primary intent from text"""
        intent_scores = {}
        
        for intent_type, patterns in self.intent_patterns.items():
            score = 0
            for pattern in patterns:
                matches = re.findall(pattern, text)
                score += len(matches)
            intent_scores[intent_type] = score
        
        # Find highest scoring intent
        if not intent_scores or max(intent_scores.values()) == 0:
            return IntentType.NEUTRAL
        
        return max(intent_scores, key=intent_scores.get)
    
    def _extract_targets(self, text: str,
                         context: Optional[Dict[str, Any]]) -> List[str]:
        """Extract target entities from text"""
        targets = []
        
        # Extract proper nouns (capitalized words not at start)
        proper_nouns = re.findall(r'\b[A-Z][a-z]+\b', text)
        targets.extend(proper_nouns)
        
        # Extract from context if available
        if context:
            npc_name = context.get("npc_name")
            if npc_name and npc_name.lower() in text.lower():
                targets.append(npc_name)
            
            player_name = context.get("player_name", "you")
            if player_name.lower() in text.lower():
                targets.append(player_name)
        
        return list(set(targets))
    
    def _analyze_sentiment(self, text: str) -> float:
        """
        Analyze sentiment (-1 to 1)
        Simple word-count based approach (preserves frequency)
        """
        words = text.split()

        positive_count = sum(1 for word in words if word in self.positive_words)
        negative_count = sum(1 for word in words if word in self.negative_words)

        total = positive_count + negative_count
        if total == 0:
            return 0.0

        return (positive_count - negative_count) / total
    
    def _check_safety(self, text: str) -> List[SafetyFlag]:
        """Check for safety violations"""
        flags = []
        
        for flag_type, patterns in self.safety_patterns.items():
            for pattern in patterns:
                if re.search(pattern, text, re.IGNORECASE):
                    flags.append(flag_type)
                    break  # One match per flag type
        
        return flags
    
    def _calculate_confidence(self, text: str, intent: IntentType) -> float:
        """
        Calculate confidence in intent classification
        Based on pattern match strength and text length
        """
        if intent == IntentType.NEUTRAL:
            return 0.5
        
        patterns = self.intent_patterns.get(intent, [])
        match_count = 0
        
        for pattern in patterns:
            match_count += len(re.findall(pattern, text, re.IGNORECASE))
        
        # Normalize by text length (avoid overconfidence on short texts)
        text_length = len(text.split())
        normalized = min(match_count / max(text_length, 1), 1.0)
        
        # Boost confidence if multiple patterns match
        confidence = 0.3 + (normalized * 0.7)
        
        return min(confidence, 1.0)
    
    def _extract_entities(self, text: str,
                          context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Extract structured entities from text"""
        entities = {}
        
        # Extract numbers
        numbers = re.findall(r'\b\d+\b', text)
        if numbers:
            entities["numbers"] = [int(n) for n in numbers]
        
        # Extract locations (simple heuristic)
        locations = re.findall(r'\b(at|in|to|from)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b', text)
        if locations:
            entities["locations"] = [loc[1] for loc in locations]
        
        # Extract time expressions
        time_expressions = re.findall(
            r'\b(now|later|soon|tomorrow|yesterday|today|tonight)\b',
            text,
            re.IGNORECASE
        )
        if time_expressions:
            entities["time_references"] = time_expressions
        
        # Extract from context
        if context:
            entities["context_npc"] = context.get("npc_name")
            entities["context_affinity"] = context.get("affinity")
            entities["context_mood"] = context.get("mood")
        
        return entities


class IntentGate:
    """
    Gate that validates intent proposals before RFSN processes them.
    Can block, modify, or pass through intents based on policy.
    """
    
    def __init__(self,
                 block_unsafe: bool = True,
                 require_min_confidence: float = 0.3):
        """
        Initialize intent gate
        
        Args:
            block_unsafe: Block intents with safety flags
            require_min_confidence: Minimum confidence threshold
        """
        self.block_unsafe = block_unsafe
        self.require_min_confidence = require_min_confidence
        self.extractor = IntentExtractor()
        
        logger.info("IntentGate initialized")
    
    def process(self, text: str,
                context: Optional[Dict[str, Any]] = None) -> Tuple[IntentProposal, bool, str]:
        """
        Process LLM output through intent gate
        
        Args:
            text: LLM generated text
            context: Optional context
            
        Returns:
            (proposal, allowed, reason)
        """
        # Extract intent
        proposal = self.extractor.extract(text, context)
        
        # Check confidence
        if proposal.confidence < self.require_min_confidence:
            reason = f"Confidence {proposal.confidence:.2f} below threshold {self.require_min_confidence}"
            logger.warning(f"Intent blocked: {reason}")
            return proposal, False, reason
        
        # Check safety
        if self.block_unsafe and proposal.requires_refusal():
            flags = ", ".join([f.value for f in proposal.safety_flags])
            reason = f"Safety flags detected: {flags}"
            logger.warning(f"Intent blocked: {reason}")
            return proposal, False, reason
        
        # Allowed
        logger.info(f"Intent allowed: {proposal.intent.value}")
        return proposal, True, "Allowed"
    
    def sanitize_for_rfsn(self, proposal: IntentProposal) -> Dict[str, Any]:
        """
        Convert intent proposal to RFSN-compatible format
        
        Args:
            proposal: Validated intent proposal
            
        Returns:
            RFSN-compatible dict
        """
        return {
            "intent_type": proposal.intent.value,
            "targets": proposal.targets,
            "sentiment": proposal.sentiment,
            "safety_flags": [f.value for f in proposal.safety_flags],
            "confidence": proposal.confidence,
            "entities": proposal.extracted_entities,
            "metadata": proposal.metadata
        }
