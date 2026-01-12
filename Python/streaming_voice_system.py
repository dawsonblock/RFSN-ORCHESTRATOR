# streaming_voice_system.py
# Drop-in replacement for the queue/threading core of StreamingVoiceSystem:
# - Uses deque + Condition (single worker consumer)
# - No task_done/join (removes the heisenbug class)
# - Drop policy runs under the same lock as the worker get
# - Supports resizing max_queue safely

from __future__ import annotations

import threading
import time
import logging
from collections import deque
from dataclasses import dataclass
from typing import Deque, Optional, Callable

logger = logging.getLogger(__name__)


@dataclass
class VoiceChunk:
    text: str
    npc_id: str
    created_ts: float
    is_final: bool = False


class DequeSpeechQueue:
    """
    Thread-safe bounded queue with a single consumer pattern.

    Drop policy:
      - When full, drop the oldest non-final chunk if possible.
      - If only finals exist, drop the oldest chunk.
      - Optionally keep one 'intro' chunk by not dropping index 0 unless necessary.
    """
    def __init__(self, maxsize: int = 3):
        self._maxsize = max(1, int(maxsize))
        self._dq: Deque[VoiceChunk] = deque()
        self._cv = threading.Condition()
        self._closed = False

        # Metrics
        self.dropped_total = 0
        self.enqueued_total = 0
        self.played_total = 0

    def set_maxsize(self, n: int) -> None:
        n = max(1, int(n))
        with self._cv:
            self._maxsize = n
            self._drop_to_fit_locked()
            self._cv.notify_all()

    def close(self) -> None:
        with self._cv:
            self._closed = True
            self._cv.notify_all()

    def __len__(self) -> int:
        with self._cv:
            return len(self._dq)

    def put(self, item: VoiceChunk) -> None:
        with self._cv:
            if self._closed:
                return
            self.enqueued_total += 1
            if len(self._dq) >= self._maxsize:
                self._drop_one_locked()
            self._dq.append(item)
            self._cv.notify()

    def get(self, timeout: Optional[float] = None) -> Optional[VoiceChunk]:
        """
        Returns None on timeout or if closed+empty.
        """
        end = None if timeout is None else (time.time() + timeout)
        with self._cv:
            while True:
                if self._dq:
                    return self._dq.popleft()
                if self._closed:
                    return None
                if timeout is None:
                    self._cv.wait()
                else:
                    remaining = end - time.time()
                    if remaining <= 0:
                        return None
                    self._cv.wait(timeout=remaining)

    def clear(self) -> None:
        with self._cv:
            self._dq.clear()
            self._cv.notify_all()

    def _drop_to_fit_locked(self) -> None:
        while len(self._dq) > self._maxsize:
            self._drop_one_locked()

    def _drop_one_locked(self) -> None:
        if not self._dq:
            return

        # Prefer dropping oldest non-final chunk, but try not to drop index 0 unless needed.
        # Strategy:
        #   scan from left->right skipping index 0; drop first non-final
        #   else scan including index 0; drop first non-final
        #   else drop leftmost
        idx_to_drop = None

        # pass 1: skip index 0
        for i in range(1, len(self._dq)):
            if not self._dq[i].is_final:
                idx_to_drop = i
                break

        # pass 2: allow index 0
        if idx_to_drop is None:
            for i in range(0, len(self._dq)):
                if not self._dq[i].is_final:
                    idx_to_drop = i
                    break

        if idx_to_drop is None:
            # all finals, drop oldest
            self._dq.popleft()
            self.dropped_total += 1
            return

        # remove by index (deque has no O(1) remove by idx; rotate is fine at size<=few)
        self._dq.rotate(-idx_to_drop)
        self._dq.popleft()
        self._dq.rotate(idx_to_drop)
        self.dropped_total += 1


class StreamingVoiceSystemV2:
    """
    Safe streaming voice worker:
      - enqueue(text) from any thread
      - worker consumes sequentially
      - drop policy + resize safe
    """

    def __init__(
        self,
        tts_synthesize: Callable[[str, str], Optional[bytes]],
        audio_play: Callable[[bytes], None],
        max_queue: int = 3,
        worker_idle_timeout: float = 0.5,
    ):
        """
        tts_synthesize(text, npc_id) -> audio bytes or None
        audio_play(audio_bytes) -> blocking play
        """
        self._tts_synthesize = tts_synthesize
        self._audio_play = audio_play

        self._q = DequeSpeechQueue(maxsize=max_queue)
        self._worker_idle_timeout = worker_idle_timeout

        self._running = False
        self._thread: Optional[threading.Thread] = None

        # Optional hard lock around audio playback if your audio backend isn't thread-safe.
        self._play_lock = threading.Lock()

    @property
    def dropped_total(self) -> int:
        return self._q.dropped_total

    @property
    def queue_size(self) -> int:
        return len(self._q)

    @property
    def enqueued_total(self) -> int:
        return self._q.enqueued_total

    @property
    def played_total(self) -> int:
        return self._q.played_total

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, name="voice-worker", daemon=True)
        self._thread.start()
        logger.info("[VoiceSystemV2] Worker started")

    def stop(self) -> None:
        self._running = False
        self._q.close()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        logger.info("[VoiceSystemV2] Worker stopped")

    def set_max_queue_size(self, n: int) -> None:
        self._q.set_maxsize(n)
        logger.info(f"[VoiceSystemV2] Queue resized to {n}")

    def flush(self) -> None:
        self._q.clear()

    def enqueue_text(self, text: str, npc_id: str = "default", is_final: bool = False) -> None:
        text = (text or "").strip()
        if not text:
            return
        self._q.put(VoiceChunk(text=text, npc_id=npc_id, created_ts=time.time(), is_final=is_final))

    def _run(self) -> None:
        while self._running:
            item = self._q.get(timeout=self._worker_idle_timeout)
            if item is None:
                continue

            audio = None
            try:
                audio = self._tts_synthesize(item.text, item.npc_id)
            except Exception as e:
                logger.error(f"[TTS] synth failed npc={item.npc_id}: {e}")

            if not audio:
                continue

            try:
                with self._play_lock:
                    self._audio_play(audio)
                self._q.played_total += 1
            except Exception as e:
                logger.error(f"[AUDIO] play failed npc={item.npc_id}: {e}")


# Factory function to create voice system with Piper TTS
def make_piper_voice_system(piper_engine, max_queue: int = 3) -> StreamingVoiceSystemV2:
    """
    Creates a StreamingVoiceSystemV2 configured for Piper TTS.
    
    Args:
        piper_engine: PiperTTSEngine instance with speak_sync(text) method
        max_queue: Maximum queue size for backpressure
    
    Returns:
        Configured and started StreamingVoiceSystemV2
    """
    def synth(text: str, npc_id: str) -> Optional[bytes]:
        # Piper's speak_sync returns None (plays directly), so we adapt
        # For now, return a sentinel that triggers direct playback
        return text.encode('utf-8')  # Just pass text through

    def play(audio: bytes) -> None:
        # Decode text and call piper directly
        text = audio.decode('utf-8')
        piper_engine.speak_sync(text)

    vs = StreamingVoiceSystemV2(
        tts_synthesize=synth,
        audio_play=play,
        max_queue=max_queue,
    )
    vs.start()
    return vs
