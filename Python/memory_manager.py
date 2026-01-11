#!/usr/bin/env python3
"""
RFSN Memory Manager v8.1 - Production Ready
Persistent conversation memory with safe reset and backup functionality.
"""

import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict
from utils.sanitize import safe_filename_token

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class ConversationTurn:
    """Single turn in a conversation"""
    user_input: str
    npc_response: str
    timestamp: str
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}
    
    def to_dict(self) -> dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: dict) -> 'ConversationTurn':
        return cls(**data)


class ConversationManager:
    """
    Manages persistent conversation memory for an NPC.
    
    Features:
    - Auto-save to disk
    - Safe reset with automatic backup
    - Restore from backup
    - Context window limiting for LLM prompts
    - Stats and analytics
    """
    
    def __init__(self, npc_name: str, memory_dir: str = "memory"):
        self.npc_name = npc_name
        self._file_token = safe_filename_token(npc_name)
        self.memory_dir = Path(memory_dir)
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        
        self.memory_file = self.memory_dir / f"{self._file_token}.json"
        self.history: List[ConversationTurn] = []
        
        self._lock = threading.Lock()
        
        # Load existing memory
        self._load()
        
        logger.info(f"[Memory] Loaded {len(self.history)} turns for {npc_name}")
    
    def _load(self):
        """Load conversation history from disk"""
        if self.memory_file.exists():
            try:
                with open(self.memory_file, 'r') as f:
                    data = json.load(f)
                    self.history = [ConversationTurn.from_dict(t) for t in data]
            except Exception as e:
                logger.error(f"[Memory] Failed to load {self.memory_file}: {e}")
                self.history = []
    
    def _save(self):
        """Save conversation history to disk"""
        try:
            with open(self.memory_file, 'w') as f:
                json.dump([t.to_dict() for t in self.history], f, indent=2)
        except Exception as e:
            logger.error(f"[Memory] Failed to save {self.memory_file}: {e}")
    
    def add_turn(self, user_input: str, npc_response: str, metadata: Dict[str, Any] = None):
        """Add a conversation turn and auto-save"""
        with self._lock:
            turn = ConversationTurn(
                user_input=user_input,
                npc_response=npc_response,
                timestamp=datetime.utcnow().isoformat(),
                metadata=metadata or {}
            )
            self.history.append(turn)
            self._save()
            
            logger.debug(f"[Memory] Added turn {len(self.history)} for {self.npc_name}")
    
    def get_context_window(self, limit: int = 4) -> str:
        """
        Get recent conversation history formatted for LLM context.
        
        Args:
            limit: Maximum number of recent turns to include
        
        Returns:
            Formatted string of recent conversation
        """
        with self._lock:
            recent = self.history[-limit:] if self.history else []
        
        if not recent:
            return ""
        
        context_parts = []
        for turn in recent:
            context_parts.append(f"Player: {turn.user_input}")
            context_parts.append(f"{self.npc_name}: {turn.npc_response}")
        
        return "\n".join(context_parts)
    
    def safe_reset(self) -> Optional[Path]:
        """
        Reset memory with automatic backup.
        
        Returns:
            Path to backup file, or None if nothing to backup
        """
        with self._lock:
            if not self.history:
                logger.info(f"[Memory] Nothing to backup for {self.npc_name}")
                return None
            
            # Create timestamped backup
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            backup_path = self.memory_dir / f"{self._file_token}_backup_{timestamp}.json"
            
            try:
                with open(backup_path, 'w') as f:
                    json.dump([t.to_dict() for t in self.history], f, indent=2)
                
                logger.info(f"[Memory] Backup created: {backup_path}")
                
                # Clear current memory
                self.history = []
                self._save()
                
                return backup_path
                
            except Exception as e:
                logger.error(f"[Memory] Backup failed: {e}")
                return None
    
    def load_from_backup(self, backup_path: Path):
        """Restore memory from a backup file"""
        with self._lock:
            try:
                with open(backup_path, 'r') as f:
                    data = json.load(f)
                    self.history = [ConversationTurn.from_dict(t) for t in data]
                self._save()
                
                logger.info(f"[Memory] Restored {len(self.history)} turns from {backup_path}")
                
            except Exception as e:
                logger.error(f"[Memory] Restore failed: {e}")
                raise
    
    def clear(self):
        """Clear memory without backup (destructive)"""
        with self._lock:
            self.history = []
            self._save()
            logger.info(f"[Memory] Cleared memory for {self.npc_name}")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get memory statistics"""
        with self._lock:
            if not self.history:
                return {
                    "npc_name": self.npc_name,
                    "total_turns": 0,
                    "first_interaction": None,
                    "last_interaction": None,
                    "total_user_chars": 0,
                    "total_npc_chars": 0,
                    "avg_response_length": 0
                }
            
            total_user = sum(len(t.user_input) for t in self.history)
            total_npc = sum(len(t.npc_response) for t in self.history)
            
            return {
                "npc_name": self.npc_name,
                "total_turns": len(self.history),
                "first_interaction": self.history[0].timestamp,
                "last_interaction": self.history[-1].timestamp,
                "total_user_chars": total_user,
                "total_npc_chars": total_npc,
                "avg_response_length": total_npc // len(self.history) if self.history else 0,
                "memory_file": str(self.memory_file),
                "file_size_bytes": self.memory_file.stat().st_size if self.memory_file.exists() else 0
            }
    
    def search(self, query: str, limit: int = 5) -> List[ConversationTurn]:
        """Simple keyword search through conversation history"""
        with self._lock:
            query_lower = query.lower()
            matches = []
            
            for turn in reversed(self.history):
                if query_lower in turn.user_input.lower() or query_lower in turn.npc_response.lower():
                    matches.append(turn)
                    if len(matches) >= limit:
                        break
            
            return matches
    
    def get_recent(self, count: int = 10) -> List[ConversationTurn]:
        """Get the most recent conversation turns"""
        with self._lock:
            return self.history[-count:] if self.history else []
    
    def __len__(self) -> int:
        return len(self.history)


def list_backups(memory_dir: str = "memory", npc_name: str = None) -> List[Dict[str, Any]]:
    """List all available backup files"""
    memory_path = Path(memory_dir)
    
    if npc_name:
        pattern = f"{npc_name}_backup_*.json"
    else:
        pattern = "*_backup_*.json"
    
    backups = []
    for backup_file in memory_path.glob(pattern):
        try:
            with open(backup_file, 'r') as f:
                data = json.load(f)
            
            # Parse NPC name from filename
            name_parts = backup_file.stem.split("_backup_")
            npc = name_parts[0] if name_parts else "unknown"
            
            backups.append({
                "filename": backup_file.name,
                "npc_name": npc,
                "path": str(backup_file),
                "timestamp": backup_file.stat().st_mtime,
                "size_bytes": backup_file.stat().st_size,
                "message_count": len(data)
            })
        except Exception as e:
            logger.warning(f"Failed to read backup {backup_file}: {e}")
    
    return sorted(backups, key=lambda x: x["timestamp"], reverse=True)


if __name__ == "__main__":
    # Quick test
    print("Testing Memory Manager...")
    
    manager = ConversationManager("TestNPC", memory_dir="test_memory")
    
    # Add some turns
    manager.add_turn("Hello there!", "Greetings, traveler. What brings you to Whiterun?")
    manager.add_turn("I'm looking for work.", "Speak to the Jarl. He might have tasks for you.")
    
    print(f"Stats: {manager.get_stats()}")
    print(f"Context: {manager.get_context_window()}")
    
    # Safe reset
    backup = manager.safe_reset()
    print(f"Backup created: {backup}")
    print(f"After reset: {len(manager)} turns")
    
    # Restore
    if backup:
        manager.load_from_backup(backup)
        print(f"After restore: {len(manager)} turns")
    
    # Cleanup
    import shutil
    shutil.rmtree("test_memory", ignore_errors=True)
    
    print("Test complete!")
