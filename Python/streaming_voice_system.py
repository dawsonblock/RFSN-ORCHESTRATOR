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
import queue as _queue  # For backwards-compat exceptions
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

    # --- Backwards-compat API (queue.Queue-like) ---
    
    @property
    def maxsize(self) -> int:
        """Backwards-compat: queue.Queue.maxsize"""
        with self._cv:
            return self._maxsize
    
    def qsize(self) -> int:
        """Backwards-compat: queue.Queue.qsize()"""
        with self._cv:
            return len(self._dq)
    
    def empty(self) -> bool:
        """Backwards-compat: queue.Queue.empty()"""
        with self._cv:
            return len(self._dq) == 0
    
    def full(self) -> bool:
        """Backwards-compat: queue.Queue.full()"""
        with self._cv:
            return len(self._dq) >= self._maxsize
    
    def put_nowait(self, item: VoiceChunk) -> None:
        """Backwards-compat: queue.Queue.put_nowait() - never blocks"""
        self.put(item)
    
    def get_nowait(self) -> VoiceChunk:
        """Backwards-compat: queue.Queue.get_nowait() - raises queue.Empty on empty"""
        item = self.get(timeout=0.0)
        if item is None:
            raise _queue.Empty
        return item

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

