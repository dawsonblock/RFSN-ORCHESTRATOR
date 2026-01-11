#!/usr/bin/env python3
"""
RFSN Multi-NPC System v8.2
Concurrent NPC conversations, voice mapping, and emotion detection.
"""

import asyncio
import json
import logging
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable
from enum import Enum

logger = logging.getLogger(__name__)


# =============================================================================
# EMOTION DETECTION
# =============================================================================

class Emotion(Enum):
    """Detected emotions for TTS prosody"""
    NEUTRAL = "neutral"
    HAPPY = "happy"
    SAD = "sad"
    ANGRY = "angry"
    FEARFUL = "fearful"
    SURPRISED = "surprised"
    DISGUSTED = "disgusted"
    CONTEMPT = "contempt"


@dataclass
class EmotionResult:
    """Result of emotion analysis"""
    primary: Emotion
    confidence: float
    secondary: Optional[Emotion] = None
    valence: float = 0.0  # -1 negative, +1 positive
    arousal: float = 0.5  # 0 calm, 1 excited


class EmotionDetector:
    """
    Simple keyword-based emotion detection.
    For production, consider using a proper NLP model.
    """
    
    # Emotion keywords (Skyrim-themed)
    EMOTION_PATTERNS = {
        Emotion.HAPPY: [
            r'\b(joy|happy|glad|pleased|delighted|wonderful|great|excellent)\b',
            r'\b(thank|grateful|appreciate|bless|honor)\b',
            r'\b(laugh|smile|cheer|celebrate)\b',
            r'!{2,}',  # Multiple exclamation marks
        ],
        Emotion.SAD: [
            r'\b(sad|sorrow|grief|mourn|weep|cry|loss|miss)\b',
            r'\b(unfortunate|tragic|terrible|awful)\b',
            r'\b(alone|lonely|abandoned|forgotten)\b',
        ],
        Emotion.ANGRY: [
            r'\b(angry|rage|fury|hate|despise|loathe)\b',
            r'\b(damn|curse|fool|idiot|traitor)\b',
            r'\b(kill|destroy|crush|annihilate)\b',
            r'\b(how dare|you dare)\b',
        ],
        Emotion.FEARFUL: [
            r'\b(fear|afraid|scared|terrified|dread)\b',
            r'\b(danger|threat|peril|doom)\b',
            r'\b(dragon|draugr|vampire|werewolf)\b',
            r'\b(run|flee|escape|hide)\b',
        ],
        Emotion.SURPRISED: [
            r'\b(what|really|truly|impossible|unbelievable)\b',
            r'\b(surprised|amazed|astonished|shocked)\b',
            r'\b(by the (gods|divines|nine))\b',
            r'\?{2,}',  # Multiple question marks
        ],
        Emotion.DISGUSTED: [
            r'\b(disgust|revolting|vile|filth|wretched)\b',
            r'\b(skeever|thalmor|imperial milk drinker)\b',
        ],
        Emotion.CONTEMPT: [
            r'\b(pathetic|weak|coward|worthless)\b',
            r'\b(beneath|unworthy|peasant)\b',
        ],
    }
    
    # Valence modifiers
    POSITIVE_WORDS = {'good', 'great', 'well', 'happy', 'joy', 'love', 'honor', 'glory', 'victory'}
    NEGATIVE_WORDS = {'bad', 'terrible', 'awful', 'hate', 'death', 'doom', 'curse', 'fail'}
    
    def analyze(self, text: str) -> EmotionResult:
        """
        Analyze text for emotional content.
        
        Returns:
            EmotionResult with primary emotion and confidence
        """
        text_lower = text.lower()
        scores: Dict[Emotion, float] = {e: 0.0 for e in Emotion}
        
        # Score each emotion based on pattern matches
        for emotion, patterns in self.EMOTION_PATTERNS.items():
            for pattern in patterns:
                matches = re.findall(pattern, text_lower, re.IGNORECASE)
                scores[emotion] += len(matches) * 0.2
        
        # Calculate valence
        words = set(text_lower.split())
        pos_count = len(words & self.POSITIVE_WORDS)
        neg_count = len(words & self.NEGATIVE_WORDS)
        total = pos_count + neg_count + 1
        valence = (pos_count - neg_count) / total
        
        # Calculate arousal based on punctuation and caps
        caps_ratio = sum(1 for c in text if c.isupper()) / max(len(text), 1)
        punct_count = text.count('!') + text.count('?')
        arousal = min(1.0, 0.3 + caps_ratio + punct_count * 0.1)
        
        # Find primary emotion
        max_score = max(scores.values())
        if max_score > 0:
            primary = max(scores, key=scores.get)
            confidence = min(1.0, max_score)
            
            # Find secondary
            scores[primary] = 0
            second_max = max(scores.values())
            secondary = max(scores, key=scores.get) if second_max > 0.1 else None
        else:
            primary = Emotion.NEUTRAL
            confidence = 0.8
            secondary = None
        
        return EmotionResult(
            primary=primary,
            confidence=confidence,
            secondary=secondary,
            valence=valence,
            arousal=arousal
        )
    
    def get_prosody_hints(self, emotion: EmotionResult) -> Dict[str, Any]:
        """
        Get TTS prosody hints based on emotion.
        
        Returns dict with:
        - rate: speaking rate multiplier
        - pitch: pitch adjustment
        - volume: volume adjustment
        """
        hints = {
            Emotion.NEUTRAL: {"rate": 1.0, "pitch": 0, "volume": 1.0},
            Emotion.HAPPY: {"rate": 1.1, "pitch": 2, "volume": 1.1},
            Emotion.SAD: {"rate": 0.85, "pitch": -2, "volume": 0.9},
            Emotion.ANGRY: {"rate": 1.15, "pitch": 1, "volume": 1.2},
            Emotion.FEARFUL: {"rate": 1.2, "pitch": 3, "volume": 0.95},
            Emotion.SURPRISED: {"rate": 1.1, "pitch": 4, "volume": 1.1},
            Emotion.DISGUSTED: {"rate": 0.95, "pitch": -1, "volume": 1.0},
            Emotion.CONTEMPT: {"rate": 0.9, "pitch": -1, "volume": 1.0},
        }
        
        base = hints.get(emotion.primary, hints[Emotion.NEUTRAL])
        
        # Adjust by arousal
        base["rate"] *= 0.9 + 0.2 * emotion.arousal
        base["volume"] *= 0.9 + 0.2 * emotion.arousal
        
        return base


# =============================================================================
# VOICE MAPPING
# =============================================================================

@dataclass
class VoiceConfig:
    """Voice configuration for an NPC"""
    model_name: str = "en_US-lessac-medium"
    speaker_id: int = 0
    rate_multiplier: float = 1.0
    pitch_offset: int = 0


class VoiceMapper:
    """
    Maps NPCs to voice configurations.
    Supports custom Piper models per NPC.
    """
    
    DEFAULT_VOICE = VoiceConfig()
    
    # Predefined voice mappings for Skyrim NPCs
    SKYRIM_VOICES = {
        # Male voices
        "Jarl Balgruuf": VoiceConfig(speaker_id=0, pitch_offset=-2, rate_multiplier=0.95),
        "Ulfric Stormcloak": VoiceConfig(speaker_id=0, pitch_offset=-3, rate_multiplier=0.9),
        "General Tullius": VoiceConfig(speaker_id=0, pitch_offset=-1, rate_multiplier=1.0),
        "Farengar": VoiceConfig(speaker_id=0, pitch_offset=1, rate_multiplier=1.1),
        
        # Female voices  
        "Lydia": VoiceConfig(speaker_id=0, pitch_offset=3, rate_multiplier=1.0),
        "Serana": VoiceConfig(speaker_id=0, pitch_offset=2, rate_multiplier=0.95),
        "Mjoll": VoiceConfig(speaker_id=0, pitch_offset=1, rate_multiplier=1.05),
        "Aela": VoiceConfig(speaker_id=0, pitch_offset=2, rate_multiplier=1.0),
        
        # Elder/wise voices
        "Paarthurnax": VoiceConfig(speaker_id=0, pitch_offset=-4, rate_multiplier=0.8),
        "Arngeir": VoiceConfig(speaker_id=0, pitch_offset=-2, rate_multiplier=0.85),
    }
    
    def __init__(self, custom_mappings: Dict[str, VoiceConfig] = None):
        self.mappings = {**self.SKYRIM_VOICES}
        if custom_mappings:
            self.mappings.update(custom_mappings)
        
        self.config_file = Path("voice_mappings.json")
        self._load_custom_mappings()
    
    def _load_custom_mappings(self):
        """Load custom voice mappings from file"""
        if self.config_file.exists():
            try:
                data = json.loads(self.config_file.read_text())
                for name, config in data.items():
                    self.mappings[name] = VoiceConfig(**config)
            except Exception as e:
                logger.warning(f"Failed to load voice mappings: {e}")
    
    def save_mappings(self):
        """Save current mappings to file"""
        data = {
            name: {
                "model_name": cfg.model_name,
                "speaker_id": cfg.speaker_id,
                "rate_multiplier": cfg.rate_multiplier,
                "pitch_offset": cfg.pitch_offset
            }
            for name, cfg in self.mappings.items()
        }
        self.config_file.write_text(json.dumps(data, indent=2))
    
    def get_voice(self, npc_name: str) -> VoiceConfig:
        """Get voice config for an NPC"""
        # Exact match
        if npc_name in self.mappings:
            return self.mappings[npc_name]
        
        # Partial match
        for name, config in self.mappings.items():
            if name.lower() in npc_name.lower() or npc_name.lower() in name.lower():
                return config
        
        return self.DEFAULT_VOICE
    
    def set_voice(self, npc_name: str, config: VoiceConfig):
        """Set voice config for an NPC"""
        self.mappings[npc_name] = config
        self.save_mappings()


# =============================================================================
# MULTI-NPC MANAGER
# =============================================================================

@dataclass
class NPCSession:
    """Active NPC conversation session"""
    npc_name: str
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_activity: datetime = field(default_factory=datetime.utcnow)
    turn_count: int = 0
    voice_config: VoiceConfig = field(default_factory=VoiceConfig)
    emotion_state: Emotion = Emotion.NEUTRAL
    
    def touch(self):
        """Update last activity time"""
        self.last_activity = datetime.utcnow()
        self.turn_count += 1


class MultiNPCManager:
    """
    Manages concurrent NPC conversations.
    
    Features:
    - Session tracking per NPC
    - Memory isolation
    - Voice configuration
    - Emotion state tracking
    """
    
    def __init__(self, max_sessions: int = 50, session_timeout_minutes: int = 30):
        self.sessions: Dict[str, NPCSession] = {}
        self.max_sessions = max_sessions
        self.session_timeout = session_timeout_minutes * 60
        self._lock = threading.Lock()
        
        self.voice_mapper = VoiceMapper()
        self.emotion_detector = EmotionDetector()
    
    def get_session(self, npc_name: str) -> NPCSession:
        """Get or create a session for an NPC"""
        with self._lock:
            # Cleanup old sessions
            self._cleanup_sessions()
            
            if npc_name not in self.sessions:
                # Create new session
                voice_config = self.voice_mapper.get_voice(npc_name)
                self.sessions[npc_name] = NPCSession(
                    npc_name=npc_name,
                    voice_config=voice_config
                )
                logger.info(f"Created session for NPC: {npc_name}")
            
            session = self.sessions[npc_name]
            session.touch()
            return session
    
    def _cleanup_sessions(self):
        """Remove expired sessions"""
        now = datetime.utcnow()
        expired = [
            name for name, session in self.sessions.items()
            if (now - session.last_activity).total_seconds() > self.session_timeout
        ]
        
        for name in expired:
            del self.sessions[name]
            logger.info(f"Expired session for NPC: {name}")
        
        # Remove oldest if at capacity
        while len(self.sessions) >= self.max_sessions:
            oldest = min(self.sessions.values(), key=lambda s: s.last_activity)
            del self.sessions[oldest.npc_name]
            logger.warning(f"Evicted session for NPC: {oldest.npc_name}")
    
    def process_response(self, npc_name: str, response_text: str) -> Dict[str, Any]:
        """
        Process an NPC response for emotion and voice hints.
        
        Returns:
            Dict with emotion and prosody information
        """
        session = self.get_session(npc_name)
        
        # Detect emotion
        emotion = self.emotion_detector.analyze(response_text)
        session.emotion_state = emotion.primary
        
        # Get prosody hints
        prosody = self.emotion_detector.get_prosody_hints(emotion)
        
        # Merge with voice config
        prosody["rate"] *= session.voice_config.rate_multiplier
        prosody["pitch"] += session.voice_config.pitch_offset
        
        return {
            "npc_name": npc_name,
            "emotion": {
                "primary": emotion.primary.value,
                "secondary": emotion.secondary.value if emotion.secondary else None,
                "confidence": emotion.confidence,
                "valence": emotion.valence,
                "arousal": emotion.arousal
            },
            "prosody": prosody,
            "voice_config": {
                "model": session.voice_config.model_name,
                "speaker_id": session.voice_config.speaker_id
            },
            "session": {
                "turn_count": session.turn_count,
                "created_at": session.created_at.isoformat(),
                "last_activity": session.last_activity.isoformat()
            }
        }
    
    def list_active_sessions(self) -> List[Dict[str, Any]]:
        """List all active NPC sessions"""
        with self._lock:
            return [
                {
                    "npc_name": s.npc_name,
                    "turn_count": s.turn_count,
                    "emotion": s.emotion_state.value,
                    "created_at": s.created_at.isoformat(),
                    "last_activity": s.last_activity.isoformat()
                }
                for s in self.sessions.values()
            ]
    
    def end_session(self, npc_name: str) -> bool:
        """End an NPC session"""
        with self._lock:
            if npc_name in self.sessions:
                del self.sessions[npc_name]
                logger.info(f"Ended session for NPC: {npc_name}")
                return True
            return False


# =============================================================================
# CONTEXT COMPRESSION
# =============================================================================

class ContextCompressor:
    """
    Compresses conversation history to fit token limits.
    Uses summarization for old turns.
    """
    
    def __init__(self, max_tokens: int = 1500, summary_threshold: int = 8):
        self.max_tokens = max_tokens
        self.summary_threshold = summary_threshold
        
        # Rough token estimate: 1 token ~= 4 chars
        self.chars_per_token = 4
    
    def estimate_tokens(self, text: str) -> int:
        """Estimate token count for text"""
        return len(text) // self.chars_per_token
    
    def compress(self, turns: List[Dict[str, str]], npc_name: str) -> str:
        """
        Compress conversation turns into a context string.
        
        Recent turns are kept verbatim; older turns are summarized.
        """
        if not turns:
            return ""
        
        # Always keep the most recent turns
        recent_count = min(4, len(turns))
        recent = turns[-recent_count:]
        older = turns[:-recent_count] if len(turns) > recent_count else []
        
        # Format recent turns
        recent_text = "\n".join(
            f"Player: {t['user_input']}\n{npc_name}: {t['npc_response']}"
            for t in recent
        )
        recent_tokens = self.estimate_tokens(recent_text)
        
        # If older turns exist and we have room, add summary
        if older and recent_tokens < self.max_tokens * 0.7:
            summary = self._summarize_turns(older, npc_name)
            summary_text = f"[Previous conversation summary: {summary}]\n\n"
            
            if self.estimate_tokens(summary_text + recent_text) < self.max_tokens:
                return summary_text + recent_text
        
        return recent_text
    
    def _summarize_turns(self, turns: List[Dict[str, str]], npc_name: str) -> str:
        """
        Create a simple summary of conversation turns.
        
        For production, consider using an LLM for summarization.
        """
        topics = set()
        
        for turn in turns:
            # Extract key topics from user input
            words = turn['user_input'].lower().split()
            
            # Simple topic extraction
            topic_words = {'quest', 'dragon', 'jarl', 'war', 'stormcloak', 'imperial',
                          'thalmor', 'draugr', 'vampire', 'werewolf', 'guild', 'college',
                          'companions', 'thieves', 'assassin', 'daedric', 'artifact',
                          'weapon', 'armor', 'magic', 'shout', 'word', 'wall'}
            
            for word in words:
                if word in topic_words:
                    topics.add(word)
        
        if topics:
            return f"Discussed: {', '.join(sorted(topics))}. {len(turns)} previous exchanges."
        else:
            return f"{len(turns)} previous exchanges with {npc_name}."


if __name__ == "__main__":
    # Quick test
    print("Testing Multi-NPC System...")
    
    manager = MultiNPCManager()
    
    # Test emotion detection
    detector = EmotionDetector()
    
    test_texts = [
        "Thank you so much! This is wonderful news!",
        "I will destroy you, traitor! You dare betray us?",
        "Alas, my brother has fallen. I mourn his loss.",
        "By the Nine! What is that creature?!",
        "I serve the Jarl. What do you need?",
    ]
    
    print("\nEmotion Detection:")
    for text in test_texts:
        result = detector.analyze(text)
        print(f"  '{text[:40]}...'")
        print(f"    -> {result.primary.value} ({result.confidence:.2f})")
    
    # Test multi-NPC
    print("\nMulti-NPC Sessions:")
    for npc in ["Lydia", "Jarl Balgruuf", "Serana"]:
        info = manager.process_response(npc, "Greetings, traveler!")
        print(f"  {npc}: voice={info['voice_config']}, emotion={info['emotion']['primary']}")
    
    print(f"\nActive sessions: {len(manager.list_active_sessions())}")
    
    # Test compression
    print("\nContext Compression:")
    compressor = ContextCompressor()
    
    turns = [
        {"user_input": f"Question {i}", "npc_response": f"Answer {i}"}
        for i in range(10)
    ]
    
    compressed = compressor.compress(turns, "Lydia")
    print(f"  Original: 10 turns")
    print(f"  Compressed: {compressor.estimate_tokens(compressed)} tokens")
    print(f"  Preview: {compressed[:100]}...")
    
    print("\nTests complete!")
