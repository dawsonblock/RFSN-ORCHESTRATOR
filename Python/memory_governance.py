"""
Memory Governance: Provenance tracking, confidence scoring, TTL, and admission policy
Ensures all memories have traceable origins and automatic decay.
"""
import threading
import hashlib
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, Optional, List, Set, Tuple
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class MemoryType(Enum):
    """Types of memories"""
    CONVERSATION_TURN = "conversation_turn"
    FACT_CLAIM = "fact_claim"
    USER_PREFERENCE = "user_preference"
    EMOTIONAL_STATE = "emotional_state"
    SYSTEM_EVENT = "system_event"


class MemorySource(Enum):
    """Sources of memory"""
    USER_INPUT = "user_input"
    NPC_RESPONSE = "npc_response"
    LEARNER_INFERENCE = "learner_inference"
    SYSTEM = "system"
    MANUAL_ENTRY = "manual_entry"


@dataclass
class EvidenceSpan:
    """Reference to evidence supporting a memory"""
    source_id: str
    content_snippet: str
    confidence: float
    timestamp: datetime


@dataclass
class GovernedMemory:
    """A memory with full governance metadata"""
    memory_id: str
    memory_type: MemoryType
    source: MemorySource
    content: str
    confidence: float
    timestamp: datetime
    ttl_seconds: Optional[float] = None
    evidence_spans: List[EvidenceSpan] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    is_quarantined: bool = False
    quarantine_reason: Optional[str] = None
    
    def __post_init__(self):
        if not self.memory_id:
            content_hash = hashlib.sha256(
                f"{self.content}:{self.timestamp.isoformat()}".encode()
            ).hexdigest()[:16]
            self.memory_id = content_hash
    
    def is_expired(self) -> bool:
        """Check if memory has expired based on TTL"""
        if self.ttl_seconds is None:
            return False
        expiry_time = self.timestamp + timedelta(seconds=self.ttl_seconds)
        return datetime.utcnow() > expiry_time
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage"""
        return {
            "memory_id": self.memory_id,
            "memory_type": self.memory_type.value,
            "source": self.source.value,
            "content": self.content,
            "confidence": self.confidence,
            "timestamp": self.timestamp.isoformat(),
            "ttl_seconds": self.ttl_seconds,
            "evidence_spans": [
                {
                    "source_id": e.source_id,
                    "content_snippet": e.content_snippet,
                    "confidence": e.confidence,
                    "timestamp": e.timestamp.isoformat()
                }
                for e in self.evidence_spans
            ],
            "metadata": self.metadata,
            "is_quarantined": self.is_quarantined,
            "quarantine_reason": self.quarantine_reason
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'GovernedMemory':
        """Create from dictionary"""
        evidence_spans = [
            EvidenceSpan(
                source_id=e["source_id"],
                content_snippet=e["content_snippet"],
                confidence=e["confidence"],
                timestamp=datetime.fromisoformat(e["timestamp"])
            )
            for e in data.get("evidence_spans", [])
        ]
        
        return cls(
            memory_id=data["memory_id"],
            memory_type=MemoryType(data["memory_type"]),
            source=MemorySource(data["source"]),
            content=data["content"],
            confidence=data["confidence"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            ttl_seconds=data.get("ttl_seconds"),
            evidence_spans=evidence_spans,
            metadata=data.get("metadata", {}),
            is_quarantined=data.get("is_quarantined", False),
            quarantine_reason=data.get("quarantine_reason")
        )


class AdmissionPolicy:
    """
    Policy for admitting memories into the system.
    Enforces deduplication, contradiction checks, and minimum confidence.
    """
    
    def __init__(self,
                 min_confidence: float = 0.3,
                 enable_dedup: bool = True,
                 enable_contradiction_check: bool = True,
                 similarity_threshold: float = 0.85):
        """
        Initialize admission policy
        
        Args:
            min_confidence: Minimum confidence for admission
            enable_dedup: Enable deduplication
            enable_contradiction_check: Enable contradiction detection
            similarity_threshold: Threshold for similarity-based dedup
        """
        self.min_confidence = min_confidence
        self.enable_dedup = enable_dedup
        self.enable_contradiction_check = enable_contradiction_check
        self.similarity_threshold = similarity_threshold
    
    def should_admit(self, memory: GovernedMemory,
                     existing_memories: List[GovernedMemory]) -> Tuple[bool, str]:
        """
        Determine if memory should be admitted
        
        Args:
            memory: Memory to check
            existing_memories: Existing memories for dedup/contradiction
            
        Returns:
            (should_admit, reason)
        """
        # Check confidence
        if memory.confidence < self.min_confidence:
            return False, f"Confidence {memory.confidence} below minimum {self.min_confidence}"
        
        # Check quarantine
        if memory.is_quarantined:
            return False, f"Memory quarantined: {memory.quarantine_reason}"
        
        # Deduplication check
        if self.enable_dedup:
            for existing in existing_memories:
                if existing.memory_id == memory.memory_id:
                    return False, f"Duplicate memory ID {memory.memory_id}"
                
                # Content similarity check
                similarity = self._compute_similarity(memory.content, existing.content)
                if similarity >= self.similarity_threshold:
                    return False, f"Similar memory exists (similarity: {similarity:.2f})"
        
        # Contradiction check
        if self.enable_contradiction_check:
            contradictions = self._detect_contradictions(memory, existing_memories)
            if contradictions:
                return False, f"Contradicts existing memories: {contradictions}"
        
        return True, "Admitted"
    
    def _compute_similarity(self, text1: str, text2: str) -> float:
        """Simple Jaccard similarity for deduplication"""
        set1 = set(text1.lower().split())
        set2 = set(text2.lower().split())
        
        if not set1 or not set2:
            return 0.0
        
        intersection = len(set1 & set2)
        union = len(set1 | set2)
        
        return intersection / union if union > 0 else 0.0
    
    def _detect_contradictions(self, memory: GovernedMemory,
                               existing_memories: List[GovernedMemory]) -> List[str]:
        """Detect contradictions with existing memories"""
        contradictions = []
        
        # Simple contradiction patterns
        negation_pairs = [
            ("is", "is not"),
            ("likes", "dislikes"),
            ("wants", "does not want"),
            ("will", "will not"),
            ("can", "cannot")
        ]
        
        memory_lower = memory.content.lower()
        
        for existing_memory in existing_memories:
            existing_lower = existing_memory.content.lower()
            
            # Check for direct negation
            for pos, neg in negation_pairs:
                if pos in memory_lower and neg in existing_lower:
                    contradictions.append(
                        f"Contradicts '{existing_memory.content}' on {pos}/{neg}"
                    )
                elif neg in memory_lower and pos in existing_lower:
                    contradictions.append(
                        f"Contradicts '{existing_memory.content}' on {neg}/{pos}"
                    )
        
        return contradictions


class MemoryGovernance:
    """
    Manages memory with full governance: provenance, admission, TTL, quarantine.
    """
    
    def __init__(self,
                 admission_policy: Optional[AdmissionPolicy] = None,
                 storage_path: Optional[Path] = None):
        """
        Initialize memory governance
        
        Args:
            admission_policy: Policy for admitting memories
            storage_path: Path to store persisted memories
        """
        self.admission_policy = admission_policy or AdmissionPolicy()
        self.storage_path = storage_path or Path("data/memory/governed")
        self.storage_path.mkdir(parents=True, exist_ok=True)
        
        # Active memories
        self._memories: Dict[str, GovernedMemory] = {}
        
        # Quarantine bucket
        self._quarantine: Dict[str, GovernedMemory] = {}
        
        # Thread safety
        self._lock = threading.RLock()
        
        # Load persisted memories
        self._load_persisted()
        
        logger.info("MemoryGovernance initialized")
    
    def _load_persisted(self):
        """Load persisted memories from disk"""
        for memory_file in self.storage_path.glob("*.json"):
            try:
                with open(memory_file, 'r') as f:
                    data = json.load(f)
                    memory = GovernedMemory.from_dict(data)
                    
                    if memory.is_expired():
                        memory_file.unlink()
                        logger.debug(f"Skipped expired memory {memory.memory_id}")
                        continue
                    
                    # Check quarantine status from persisted data
                    if memory.is_quarantined:
                        self._quarantine[memory.memory_id] = memory
                    else:
                        self._memories[memory.memory_id] = memory
            except Exception as e:
                logger.warning(f"Failed to load memory {memory_file}: {e}")
    
    def add_memory(self, memory: GovernedMemory) -> Tuple[bool, str, Optional[str]]:
        """
        Add a memory subject to admission policy
        
        Args:
            memory: Memory to add
            
        Returns:
            (success, reason, memory_id)
        """
        with self._lock:
            # Check admission policy
            should_admit, reason = self.admission_policy.should_admit(
                memory, list(self._memories.values())
            )
            
            if not should_admit:
                # Move to quarantine if not already
                if not memory.is_quarantined:
                    memory.is_quarantined = True
                    memory.quarantine_reason = reason
                    self._quarantine[memory.memory_id] = memory
                    self._persist_memory(memory)
                
                logger.info(f"Memory quarantined: {memory.memory_id} - {reason}")
                return False, reason, memory.memory_id
            
            # Admit memory
            self._memories[memory.memory_id] = memory
            self._persist_memory(memory)
            
            logger.info(f"Memory admitted: {memory.memory_id} (confidence: {memory.confidence:.2f})")
            return True, "Admitted", memory.memory_id
    
    def get_memory(self, memory_id: str) -> Optional[GovernedMemory]:
        """Get a memory by ID"""
        with self._lock:
            return self._memories.get(memory_id)
    
    def query_memories(self,
                       memory_type: Optional[MemoryType] = None,
                       source: Optional[MemorySource] = None,
                       min_confidence: Optional[float] = None,
                       include_expired: bool = False) -> List[GovernedMemory]:
        """
        Query memories with filters
        
        Args:
            memory_type: Filter by type
            source: Filter by source
            min_confidence: Minimum confidence
            include_expired: Include expired memories
            
        Returns:
            List of matching memories
        """
        with self._lock:
            results = []
            
            for memory in self._memories.values():
                # Skip expired unless requested
                if not include_expired and memory.is_expired():
                    continue
                
                # Apply filters
                if memory_type and memory.memory_type != memory_type:
                    continue
                if source and memory.source != source:
                    continue
                if min_confidence and memory.confidence < min_confidence:
                    continue
                
                results.append(memory)
            
            # Sort by timestamp (newest first)
            results.sort(key=lambda m: m.timestamp, reverse=True)
            return results
    
    def get_quarantined(self) -> List[GovernedMemory]:
        """Get all quarantined memories"""
        with self._lock:
            return list(self._quarantine.values())
    
    def release_from_quarantine(self, memory_id: str, override_reason: str) -> bool:
        """
        Release a memory from quarantine
        
        Args:
            memory_id: ID of memory to release
            override_reason: Reason for override
            
        Returns:
            True if released
        """
        with self._lock:
            if memory_id not in self._quarantine:
                return False
            
            memory = self._quarantine.pop(memory_id)
            memory.is_quarantined = False
            memory.quarantine_reason = None
            memory.metadata["quarantine_override"] = override_reason
            
            # Re-check admission
            should_admit, reason = self.admission_policy.should_admit(
                memory, list(self._memories.values())
            )
            
            if should_admit:
                self._memories[memory_id] = memory
                self._persist_memory(memory)
                logger.info(f"Released from quarantine: {memory_id}")
                return True
            else:
                # Put back in quarantine with new reason
                memory.is_quarantined = True
                memory.quarantine_reason = f"Override failed: {reason}"
                self._quarantine[memory_id] = memory
                return False
    
    def cleanup_expired(self, older_than_seconds: Optional[float] = None) -> int:
        """
        Remove expired memories from both active and quarantine

        Args:
            older_than_seconds: Custom TTL override

        Returns:
            Number of memories removed
        """
        with self._lock:
            removed = 0
            to_remove = []
            to_remove_quarantine = []
            
            cutoff_time = None
            if older_than_seconds is not None:
                cutoff_time = datetime.utcnow() - timedelta(seconds=older_than_seconds)
            
            # Check active memories
            for memory_id, memory in self._memories.items():
                if memory.is_expired():
                    to_remove.append(memory_id)
                elif cutoff_time and memory.timestamp < cutoff_time:
                    to_remove.append(memory_id)
            
            # Check quarantined memories
            for memory_id, memory in self._quarantine.items():
                if memory.is_expired():
                    to_remove_quarantine.append(memory_id)
                elif cutoff_time and memory.timestamp < cutoff_time:
                    to_remove_quarantine.append(memory_id)
            
            # Remove active memories
            for memory_id in to_remove:
                self._memories.pop(memory_id, None)
                self._delete_memory_file(memory_id)
                removed += 1
            
            # Remove quarantined memories
            for memory_id in to_remove_quarantine:
                self._quarantine.pop(memory_id, None)
                self._delete_memory_file(memory_id)
                removed += 1
            
            logger.info(f"Cleaned up {removed} expired memories")
            return removed
    
    def _delete_memory_file(self, memory_id: str):
        """Delete memory file by ID"""
        memory_file = self.storage_path / f"{memory_id}.json"
        try:
            if memory_file.exists():
                memory_file.unlink()
        except Exception as e:
            logger.warning(f"Failed to delete memory file {memory_file}: {e}")
    
    def _persist_memory(self, memory: GovernedMemory):
        """Persist memory to disk"""
        memory_file = self.storage_path / f"{memory.memory_id}.json"
        try:
            with open(memory_file, 'w') as f:
                json.dump(memory.to_dict(), f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to persist memory {memory.memory_id}: {e}")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get governance statistics"""
        with self._lock:
            total = len(self._memories)
            expired = sum(1 for m in self._memories.values() if m.is_expired())
            quarantined = len(self._quarantine)
            
            # Confidence distribution
            confidences = [m.confidence for m in self._memories.values()]
            avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0
            
            # Type distribution
            type_counts = {}
            for memory in self._memories.values():
                mem_type = memory.memory_type.value
                type_counts[mem_type] = type_counts.get(mem_type, 0) + 1
            
            return {
                "total_memories": total,
                "active_memories": total - expired,
                "expired_memories": expired,
                "quarantined_memories": quarantined,
                "average_confidence": avg_confidence,
                "type_distribution": type_counts,
                "storage_path": str(self.storage_path)
            }
