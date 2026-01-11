#!/usr/bin/env python3
"""
RFSN Streaming Engine v8.7 - Hardened Reliability
Fixes: sentence fragmentation, race conditions, token bleeding, backpressure
"""

import threading
import queue
import re
import time
import logging
from typing import Generator, Optional, List, Callable, Dict, Any
from dataclasses import dataclass, field
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

CLOSERS = set(['"', "'", "”", "’", ")", "]", "}"])
BOUNDARY_FLUSH_MS = 180  # flush boundary if no continuation arrives quickly

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
        
        # Deferred split state
        self._pending_boundary = False
        self._pending_boundary_deadline = 0.0
        
        # Abbreviations that end in dot but shouldn't split
        self.abbreviations = {
            'mr', 'mrs', 'ms', 'dr', 'prof', 'sr', 'jr', 'st', 
            'mt', 'capt', 'col', 'gen', 'lt', 'sgt', 'corp', 
            'etc', 'vs', 'inc', 'ltd', 'fig', 'op'
        }
    
    def _peek_after_closers(self, s: str, i: int) -> int:
        j = i + 1
        while j < len(s) and s[j] in CLOSERS:
            j += 1
        return j
    
    def process(self, token: str) -> List[str]:
        """
        Process a new token and return list of completed sentences.
        """
        sentences = []

        
        # CRITICAL (Patch v8.9): Check if new token CANCELS pending boundary BEFORE deadline flush
        # This prevents premature flush of abbreviations like "Mr." + " Jones"
        if self._pending_boundary and len(token) > 0:
            # Skip leading closers/whitespace to find first content char
            c_idx = 0
            while c_idx < len(token) and (token[c_idx] in CLOSERS or token[c_idx].isspace()):
                c_idx += 1
            
            if c_idx < len(token):  # Found a content char
                # If alphanumeric, it canceled the boundary (continuation)
                if token[c_idx].isalnum():
                    self._pending_boundary = False

                # Else (punctuation?), pending boundary stands until flush time
            # Else (all closers/space), effectively still boundary-ish, let timer flush it
        
        # Check pending flush deadline AFTER cancellation check
        now = time.time()
        if self._pending_boundary and now >= self._pending_boundary_deadline:

            sentences.extend(self.flush())
            self._pending_boundary = False
            
        self.buffer += token

        
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
            
            # Terminator check logic (Patch A)
            if char in ('.', '!', '?'):

                # Check for "..."
                if char == '.' and self.buffer[cursor:cursor+3] == '...':
                    cursor += 2
                    continue

                j = self._peek_after_closers(self.buffer, cursor)
                should_split = False

                
                # Boundary conditions
                if j >= len(self.buffer):
                    # End-of-buffer: defer split (Patch B)
                    self._pending_boundary = True
                    self._pending_boundary_deadline = time.time() + (BOUNDARY_FLUSH_MS / 1000.0)

                    # Don't split yet
                elif self.buffer[j].isspace():
                    should_split = True

                
                # Abbreviation Check
                if char == '.' and should_split:
                    word_match = re.search(r'(\w+)$', self.buffer[:cursor])
                    if word_match:
                        word = word_match.group(1).lower()
                        if word in self.abbreviations:
                            should_split = False

                
                if should_split:
                    # Point j is where the next sentence *starts* (after space)
                    # But actually we want to slice up to j (keeping punctuation+closers)
                    # self.buffer[j] is space.
                    split_idx = j 
                    sentence = self.buffer[:split_idx].strip()
                    if sentence:
                        sentences.append(sentence)
                    
                    self.buffer = self.buffer[split_idx:]
                    cursor = -1 # Restart scanning new buffer
                    self._pending_boundary = False
                    self.in_quotes = False # Sentence boundary creates clean slate
            
            cursor += 1
            
        return sentences
    
    def flush(self) -> List[str]:
        """Flush remaining buffer as a sentence"""
        res = []
        # If pending boundary, we definitely flush now
        if self.buffer.strip():
            res.append(self.buffer.strip())
        self.buffer = ""
        self.in_quotes = False
        self._pending_boundary = False
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
        
        # Queue management locks and sentinels (Patch v8.8)
        self._queue_lock = threading.Lock()
        self._worker_wakeup = object()

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
                # Reduced timeout to prevents stalls if queue reference changes (Patch v8.8)
                chunk = self.speech_queue.get(timeout=0.5)
                
                # Check for sentinel (resize wakeup)
                if chunk is self._worker_wakeup:
                    self.speech_queue.task_done()
                    continue

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
                
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"TTS worker error: {e}", exc_info=True)

    def set_max_queue_size(self, new_max: int):
        """Safely resize the queue at runtime with backlog preservation (Patch v8.8)"""
        new_max = int(new_max)
        if new_max < 1: new_max = 1
        if new_max > 50: new_max = 50
        
        with self._queue_lock:
            old_q = self.speech_queue
            old_items = []

            # Drain old queue without blocking
            while True:
                try:
                    x = old_q.get_nowait()
                    if x is not self._worker_wakeup:
                        old_items.append(x)
                    old_q.task_done() # Mark extracted as done
                except queue.Empty:
                    break

            # If shrinking, trim coherently while "preserving backlog"
            if len(old_items) > new_max:
                if new_max == 1:
                    old_items = [old_items[-1]]  # keep most recent only
                elif new_max == 2:
                    old_items = [old_items[0], old_items[-1]]
                else:
                    # keep first + last, fill remaining from the end (most recent)
                    keep = [old_items[0]]
                    tail = old_items[1:-1]
                    needed = new_max - 2
                    keep_mid = tail[-needed:]  # most recent middle items
                    old_items = keep + keep_mid + [old_items[-1]]
            
            # Create new queue
            new_q = queue.Queue(maxsize=new_max)
            for x in old_items:
                try:
                    new_q.put_nowait(x)
                except queue.Full:
                    break

            self.speech_queue = new_q
            logger.info(f"[VoiceSystem] Resized queue to {new_max}, preserved {len(old_items)} items")

            # Wake worker: best effort push sentinel to new queue
            try:
                self.speech_queue.put_nowait(self._worker_wakeup)
            except queue.Full:
                pass
            
            self.metrics.tts_queue_size = self.speech_queue.qsize()
    
    def _clean_for_tts(self, text: str) -> str:
        """Targeted cleaning for TTS"""
        original = text
        for token in self.BAD_TOKENS:
            text = text.replace(token, "")
        text = re.sub(r'\*[^\*]+\*', '', text)
        text = re.sub(r'\[[^\]]+\]', '', text)
        text = re.sub(r'<[^>]+>', '', text)
        text = ' '.join(text.split())
        if len(text) < 2 and not text.isalnum(): return ""
        alpha_count = sum(c.isalpha() for c in text)
        if len(text) > 20 and alpha_count / len(text) < 0.3: return ""
        return text.strip()
    
    def _subprocess_speak(self, text: str):
        """Process-safe audio playback"""
        if self._tts_engine_ref is not None:
            try:
                self._tts_engine_ref.speak_sync(text)
            except Exception as e:
                logger.error(f"TTS subprocess error: {e}")
        else:
            logger.info(f"[TTS-MOCK] Would speak: {text[:50]}...")

    def _drop_policy(self):
        """
        Coherence-preserving policy (Patch 2):
        - If queue has 1 item: drop it
        - If 2+: drop middle, keep first (context) and last (latest)
        """
        items = []
        while True:
            try:
                items.append(self.speech_queue.get_nowait())
                self.speech_queue.task_done()
            except queue.Empty:
                break

        if not items:
            return

        if len(items) == 1:
            # Drop the only item
            self._dropped_count += 1
            self.metrics.dropped_sentences += 1
            return

        # Keep first and last, drop a middle item
        mid = len(items) // 2
        dropped_item = items.pop(mid)
        self._dropped_count += 1
        self.metrics.dropped_sentences += 1
        logger.warning(f"Backpressure drop (middle): {dropped_item.text[:20]}...")

        for it in items:
            try:
                self.speech_queue.put_nowait(it)
            except queue.Full:
                break # Should not happen if we just removed one

    def speak(self, text: str) -> bool:
        """Queue text for TTS with backpressure handling (Patch 2)"""
        if not text or self._shutdown:
            return False
        
        chunk = SentenceChunk(text=text)
        try:
            self.speech_queue.put_nowait(chunk)
            return True
        except queue.Full:
            # Backpressure: smart drop
            self._drop_policy()
            # Try again
            try:
                self.speech_queue.put_nowait(chunk)
                return True
            except queue.Full:
                self.metrics.dropped_sentences += 1
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
    
    def flush_pending(self):
        """Enqueue any remaining buffered text as final sentence(s)."""
        leftovers = self.tokenizer.flush()
        for s in leftovers:
            self.speak(s)
    
    def reset(self):
        """Hard reset: clears queue + tokenizer + metrics."""
        self.tokenizer = StreamTokenizer()
        # Drain queue safely with size snapshot to avoid race conditions
        queue_size = self.speech_queue.qsize()
        for _ in range(queue_size):
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
                n_gpu_layers=-1, 
                verbose=False,
            )
            logger.info(f"StreamingMantellaEngine loaded: {Path(model_path).name}")
        except ImportError:
            logger.warning("llama-cpp-python not installed. Running in mock mode.")
        except Exception as e:
            logger.error(f"Failed to load model: {e}")
    
    def generate_streaming(self, prompt: str, max_tokens: int = 512, temperature: float = 0.7) -> Generator[SentenceChunk, None, None]:
        """Generate with streaming and full metrics - Patch 3 Stop Conditions"""
        
        if self.llm is None:
            # Mock token stream
            def mock_tokens():
                text = "I am a Skyrim NPC running in mock mode. I should still detect sentences, abbreviate Dr. correctly, and queue for TTS."
                for word in text.split(" "):
                    yield word + " "
                    time.sleep(0.05)
                yield ""
            yield from self.voice.process_stream(mock_tokens())
            return
        
        # Create token generator with Expanded Stops (Patch 3)
        def token_gen():
            stream = self.llm(
                prompt,
                max_tokens=max_tokens,
                stop=[
                    "<" + "|eot_id|>", "<" + "|end|>", "</s>", 
                    "\nPlayer:", "\nUser:", "\nYou:", "\nNPC:", "Player:", "User:"
                ],
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
