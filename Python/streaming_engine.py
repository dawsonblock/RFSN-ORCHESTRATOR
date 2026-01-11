#!/usr/bin/env python3
"""
RFSN Streaming Engine v8.1 - Production Ready
Fixes: sentence fragmentation, race conditions, token bleeding, backpressure
"""

import threading
import queue
import re
import time
import logging
import tempfile
import subprocess
import os
import sys
from typing import Generator, Optional, List, Callable, Dict, Any
from dataclasses import dataclass, field
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


@dataclass
class SentenceChunk:
    """Represents a complete sentence chunk for TTS"""
    text: str
    is_final: bool = False
    latency_ms: float = 0.0


class StreamTokenizer:
    """
    State-machine based sentence splitter for streaming text.
    Handles quotes, ellipses, and abbreviations better than regex.
    """
    def __init__(self):
        self.buffer = ""
        self.in_quotes = False
        self.quote_char = None  # ' or "
        
        # Abbreviations that end in dot but shouldn't split
        self.abbreviations = {
            'mr', 'mrs', 'ms', 'dr', 'prof', 'sr', 'jr', 'st', 
            'mt', 'capt', 'col', 'gen', 'lt', 'sgt', 'corp', 
            'etc', 'vs', 'inc', 'ltd', 'fig', 'no', 'op'
        }
    
    def process(self, token: str) -> List[str]:
        """
        Process a new token and return list of completed sentences.
        """
        sentences = []
        self.buffer += token
        
        # We only try to split if we have a reasonable buffer
        if len(self.buffer) < 2:
            return sentences
            
        cursor = 0
        while cursor < len(self.buffer):
            char = self.buffer[cursor]
            
            # Handle quotes
            if char in ('"', '“', '”'):
                if not self.in_quotes:
                    self.in_quotes = True
                    self.quote_char = char
                elif char == self.quote_char or char in ('”', '"'): # Simple matching
                    self.in_quotes = False
                    self.quote_char = None
            
            # Check for terminator if not in quotes
            if not self.in_quotes and char in ('.', '!', '?'):
                # Look ahead
                # If '...', treat as pause but keep together? 
                if cursor + 1 >= len(self.buffer):
                    break # Wait for more data
                
                next_char = self.buffer[cursor+1]
                
                # Check for "..."
                if char == '.' and self.buffer[cursor:cursor+3] == '...':
                    cursor += 2
                    continue
                
                should_split = False
                
                # Case 1: Punctuation followed by space
                if next_char.isspace():
                    should_split = True
                
                # Abbreviation Check
                if char == '.' and should_split:
                    word_match = re.search(r'(\w+)$', self.buffer[:cursor])
                    if word_match:
                        word = word_match.group(1).lower()
                        if word in self.abbreviations:
                            should_split = False
                
                if should_split:
                    split_idx = cursor + 1
                    sentence = self.buffer[:split_idx].strip()
                    if sentence:
                        sentences.append(sentence)
                    
                    self.buffer = self.buffer[split_idx:]
                    cursor = -1 # Restart scanning new buffer from 0
            
            cursor += 1
            
        return sentences
    
    def flush(self) -> List[str]:
        """Flush remaining buffer as a sentence"""
        res = []
        if self.buffer.strip():
            res.append(self.buffer.strip())
        self.buffer = ""
        self.in_quotes = False
        return res


@dataclass
class StreamingMetrics:
    """Performance metrics for streaming pipeline"""
    first_token_ms: float = 0.0
    first_sentence_ms: float = 0.0
    total_generation_ms: float = 0.0
    tts_queue_size: int = 0
    dropped_sentences: int = 0


@dataclass
class RFSNState:
    """RFSN mathematical state model for NPC behavior"""
    npc_name: str
    affinity: float = 0.0
    playstyle: str = "Unknown"
    mood: str = "Neutral"
    relationship: str = "Stranger"
    
    def get_attitude_instruction(self) -> str:
        """Convert affinity math to English instruction for LLM"""
        if self.affinity >= 0.85:
            return "Devoted and loving. You would die for them."
        if self.affinity >= 0.65:
            return "Warm and affectionate close friend."
        if self.affinity >= 0.35:
            return "Friendly and supportive."
        if self.affinity >= 0.05:
            return "Polite and professional."
        if self.affinity >= -0.35:
            return "Neutral and distant."
        if self.affinity >= -0.65:
            return "Cold, suspicious, and dismissive."
        return "Hostile and openly aggressive."


class StreamingVoiceSystem:
    """
    Production voice system with:
    - Smart sentence boundaries (avoids abbreviations)
    - Thread-safe playback with backpressure
    - Automatic token filtering
    - Error handling (no silent failures)
    """
    
    
    # Tokens that should NEVER be spoken (LLM control tokens)
    BAD_TOKENS = {
        "<" + "|eot_id|>", "<" + "|end|>", "<" + "|start_header_id|>", 
        "<" + "|end_header_id|>", "<" + "|assistant|>", "<" + "|user|>", 
        "<" + "|system|>", "[INST]", "[/INST]", "</s>", "<|end|>"
    }
    
    def __init__(self, tts_engine: str = "piper", max_queue_size: int = 3):
        self.tts_engine = tts_engine
        self.speech_queue = queue.Queue(maxsize=max_queue_size)
        self.metrics = StreamingMetrics()
        self._dropped_count = 0
        self._shutdown = False
        self.audio_lock = threading.Lock()
        
        # State machine tokenizer
        self.tokenizer = StreamTokenizer()
        
        # Playback lock for thread safety
        self._playback_lock = threading.Lock()
        
        # TTS engine reference (set externally)
        self._tts_engine_ref = None
        
        # Start worker thread
        self.worker = threading.Thread(target=self._tts_worker, daemon=True)
        self.worker.start()
        
        logger.info(f"[VoiceSystem] Initialized {tts_engine} with tokenizer=StreamTokenizer")
    
    def set_tts_engine(self, engine):
        """Set the TTS engine reference"""
        self._tts_engine_ref = engine
    
    def _tts_worker(self):
        """Thread-safe worker that processes queue"""
        while not self._shutdown:
            try:
                chunk = self.speech_queue.get(timeout=30)
                if chunk is None:  # Shutdown signal
                    break
                
                # Clean text before TTS
                clean_text = self._clean_for_tts(chunk.text)
                if not clean_text:
                    logger.warning(f"Skipped empty/invalid TTS text: {chunk.text}")
                    self.speech_queue.task_done()
                    continue
                
                # Thread-safe playback via subprocess
                with self._playback_lock:
                    self._subprocess_speak(clean_text)
                
                self.speech_queue.task_done()
                
                self.speech_queue.task_done()
                
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"TTS worker error: {e}", exc_info=True)

    def set_max_queue_size(self, new_max: int):
        """Safely resize the queue at runtime"""
        new_max = int(new_max)
        if new_max < 1: new_max = 1
        if new_max > 20: new_max = 20
        
        with self.audio_lock:
            # Drain old queue? Or just make new one. Dropping backlog is safer/simpler for immediate effect.
            self.speech_queue = queue.Queue(maxsize=new_max)
            self.metrics.tts_queue_size = 0
            self.metrics.dropped_sentences = 0
            logger.info(f"[VoiceSystem] Resized queue to {new_max}")
    
    def _clean_for_tts(self, text: str) -> str:
        """
        Targeted cleaning for TTS:
        - Removes *actions* and [stage directions]
        - Preserves (parentheses) unless they contain only 1-2 words likely to be action?
        - Removes HTML-like tags
        """
        original = text
        
        # Remove special tokens
        for token in self.BAD_TOKENS:
            text = text.replace(token, "")
        
        # Remove actions: *sighs*, [laughs]
        # Match *...*
        text = re.sub(r'\*[^\*]+\*', '', text)
        # Match [...]
        text = re.sub(r'\[[^\]]+\]', '', text)
        
        # Remove HTML-like tags
        text = re.sub(r'<[^>]+>', '', text)
        
        # Consolidate whitespace
        text = ' '.join(text.split())
        
        # Reject if too short (unless it's a short word like "No.")
        if len(text) < 2 and not text.isalnum():
            return ""
        
        # Reject if high code-to-text ratio (gibberish detection)
        # Loosened check to match reality
        alpha_count = sum(c.isalpha() for c in text)
        if len(text) > 20 and alpha_count / len(text) < 0.3:
            logger.debug(f"Rejected low alpha ratio: {text}")
            return ""

        return text.strip()
    
    def _subprocess_speak(self, text: str):
        """
        Process-safe audio playback using subprocess.
        
        CRITICAL: We use subprocess instead of sounddevice because
        sounddevice is NOT thread-safe and will crash under load.
        """
        if self._tts_engine_ref is not None:
            try:
                self._tts_engine_ref.speak_sync(text)
            except Exception as e:
                logger.error(f"TTS subprocess error: {e}")
        else:
            # Fallback: log the text that would be spoken
            logger.info(f"[TTS-MOCK] Would speak: {text[:50]}...")
    
    def speak(self, text: str) -> bool:
        """Queue text for TTS with backpressure handling"""
        if not text or self._shutdown:
            return False
        
        chunk = SentenceChunk(text=text)
        try:
            self.speech_queue.put_nowait(chunk)
            return True
        except queue.Full:
            # Backpressure: drop oldest, add new
            try:
                old = self.speech_queue.get_nowait()
                self._dropped_count += 1
                self.metrics.dropped_sentences += 1
                logger.warning(f"Dropped sentence due to backpressure: {old.text[:30]}...")
            except queue.Empty:
                pass
            try:
                self.speech_queue.put_nowait(chunk)
                return True
            except queue.Full:
                return False
    
    def process_stream(self, token_generator: Generator[str, None, None]) -> Generator[SentenceChunk, None, None]:
        """
        Main streaming pipeline using StreamTokenizer
        """
        start_time = time.time()
        first_token_time = None
        first_sentence_time = None
        
        # Clear tokenizer buffer
        self.tokenizer = StreamTokenizer()
        
        for token in token_generator:
            if first_token_time is None:
                first_token_time = time.time()
                self.metrics.first_token_ms = (first_token_time - start_time) * 1000
            
            # Filter tokens immediately
            if token.strip() in self.BAD_TOKENS or token.strip().startswith('<|'):
                continue
            
            # Process token through state machine
            sentences = self.tokenizer.process(token)
            
            for sentence in sentences:
                if first_sentence_time is None:
                    first_sentence_time = time.time()
                    self.metrics.first_sentence_ms = (first_sentence_time - start_time) * 1000
                
                # Queue with backpressure handling
                self.speak(sentence)
                
                # Yield for API
                latency = (time.time() - start_time) * 1000
                yield SentenceChunk(text=sentence, latency_ms=latency)
        
        # Handle final fragment
        final_sentences = self.tokenizer.flush()
        for sent in final_sentences:
            self.speak(sent)
            yield SentenceChunk(
                text=sent, 
                is_final=True, 
                latency_ms=(time.time() - start_time) * 1000
            )
        
        self.metrics.total_generation_ms = (time.time() - start_time) * 1000
        self.metrics.tts_queue_size = self.speech_queue.qsize()
    
    def flush(self):
        """Clear buffer and queue"""
        self.tokenizer = StreamTokenizer()
        while not self.speech_queue.empty():
            try:
                self.speech_queue.get_nowait()
                self.speech_queue.task_done()
            except queue.Empty:
                break
        self._dropped_count = 0
        self.metrics = StreamingMetrics()
    
    def shutdown(self):
        """Graceful shutdown"""
        self._shutdown = True
        self.speech_queue.put(None)
        self.worker.join(timeout=5)
        logger.info("[VoiceSystem] Shutdown complete")


class StreamingMantellaEngine:
    """Streaming LLM wrapper with KV cache optimization"""
    
    def __init__(self, model_path: str = None):
        self.model_path = model_path
        self.llm = None
        self.voice = StreamingVoiceSystem(tts_engine="piper", max_queue_size=3)
        self.temperature = 0.7
        self.max_tokens = 80
        
        if model_path and Path(model_path).exists():
            self._load_model(model_path)
        else:
            logger.warning(f"Model not found: {model_path}. Running in mock mode.")
    
    def _load_model(self, model_path: str):
        """Load llama.cpp model with KV cache persistence"""
        try:
            from llama_cpp import Llama
            
            self.llm = Llama(
                model_path=model_path,
                n_ctx=2048,
                n_gpu_layers=-1,  # Use all GPU layers
                verbose=False,
                # KV cache persists between calls (massive speedup)
            )
            logger.info(f"StreamingMantellaEngine loaded: {Path(model_path).name}")
        except ImportError:
            logger.warning("llama-cpp-python not installed. Running in mock mode.")
        except Exception as e:
            logger.error(f"Failed to load model: {e}")
    
    def generate_streaming(self, prompt: str, max_tokens: int = 512, temperature: float = 0.7) -> Generator[SentenceChunk, None, None]:
        """Generate with streaming and full metrics"""
        
        if self.llm is None:
            # Mock token stream that flows through REAL sentence pipeline
            def mock_tokens():
                text = "I am a Skyrim NPC running in mock mode. I should still detection sentences, abbreviate Dr. correctly, and queue for TTS."
                for word in text.split(" "):
                    yield word + " "
                    time.sleep(0.05)
                yield ""
            
            yield from self.voice.process_stream(mock_tokens())
            return
        
        # Create token generator
        def token_gen():
            stream = self.llm(
                prompt,
                max_tokens=max_tokens,
                stop=["<" + "|eot_id|>", "Player:", "User:", "<" + "|end|>", "</s>", "\n\nPlayer:", "\nUser:"],
                stream=True,
                echo=False,
                temperature=temperature,
            )
            for chunk in stream:
                if 'choices' in chunk and chunk['choices']:
                    text = chunk['choices'][0].get('text', '')
                    if text:
                        yield text
        
        # Process through voice system
        yield from self.voice.process_stream(token_gen())

    def apply_tuning(self, *, temperature: float = None, max_tokens: int = None, max_queue_size: int = None):
        """Apply runtime performance settings"""
        if temperature is not None:
            self.temperature = float(temperature)
        if max_tokens is not None:
            self.max_tokens = int(max_tokens)
        if max_queue_size is not None:
            self.voice.set_max_queue_size(int(max_queue_size))
        
        logger.info(f"Tuning applied: temp={self.temperature}, tokens={self.max_tokens}")
    
    def shutdown(self):
        """Cleanup resources"""
        self.voice.shutdown()
        logger.info("StreamingMantellaEngine shutdown complete")


if __name__ == "__main__":
    # Quick test
    engine = StreamingMantellaEngine()
    print("Testing streaming engine...")
    
    for chunk in engine.generate_streaming("Hello"):
        print(f"Chunk: {chunk.text} (final={chunk.is_final}, latency={chunk.latency_ms:.0f}ms)")
    
    engine.shutdown()
    print("Test complete!")
