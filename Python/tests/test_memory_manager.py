#!/usr/bin/env python3
"""
Test Suite: Memory Manager
Tests for safe reset, backup, and restore functionality
"""

import pytest
import json
import shutil
from pathlib import Path
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from memory_manager import ConversationManager, ConversationTurn, list_backups


@pytest.fixture
def temp_memory_dir(tmp_path):
    """Create a temporary memory directory"""
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    yield memory_dir
    # Cleanup
    shutil.rmtree(memory_dir, ignore_errors=True)


@pytest.fixture
def manager(temp_memory_dir):
    """Create a conversation manager with temp directory"""
    return ConversationManager("TestNPC", str(temp_memory_dir))


class TestConversationTurn:
    """Test ConversationTurn dataclass"""
    
    def test_create_turn(self):
        turn = ConversationTurn(
            user_input="Hello",
            npc_response="Greetings, traveler",
            timestamp="2024-01-01T00:00:00"
        )
        assert turn.user_input == "Hello"
        assert turn.npc_response == "Greetings, traveler"
        assert turn.metadata == {}
    
    def test_to_dict(self):
        turn = ConversationTurn(
            user_input="Hello",
            npc_response="Greetings",
            timestamp="2024-01-01T00:00:00"
        )
        d = turn.to_dict()
        assert d["user_input"] == "Hello"
        assert d["npc_response"] == "Greetings"
    
    def test_from_dict(self):
        data = {
            "user_input": "Hello",
            "npc_response": "Greetings",
            "timestamp": "2024-01-01T00:00:00",
            "metadata": {"key": "value"}
        }
        turn = ConversationTurn.from_dict(data)
        assert turn.user_input == "Hello"
        assert turn.metadata["key"] == "value"


class TestConversationManager:
    """Test ConversationManager"""
    
    def test_add_turn(self, manager):
        """Should add a turn and persist it"""
        manager.add_turn("Hello", "Greetings")
        
        assert len(manager) == 1
        assert manager.history[0].user_input == "Hello"
    
    def test_get_context_window(self, manager):
        """Should return formatted context"""
        manager.add_turn("Hello", "Greetings")
        manager.add_turn("How are you?", "I am well")
        
        context = manager.get_context_window(limit=2)
        
        assert "Player: Hello" in context
        assert "TestNPC: Greetings" in context
    
    def test_context_window_limit(self, manager):
        """Should respect context limit"""
        for i in range(10):
            manager.add_turn(f"Message {i}", f"Response {i}")
        
        context = manager.get_context_window(limit=2)
        
        # Should only contain last 2 turns
        assert "Message 8" in context
        assert "Message 9" in context
        assert "Message 0" not in context
    
    def test_safe_reset_creates_backup(self, manager, temp_memory_dir):
        """Should create backup before reset"""
        manager.add_turn("Hello", "World")
        
        backup_path = manager.safe_reset()
        
        assert backup_path is not None
        assert backup_path.exists()
        assert len(manager) == 0  # Memory cleared
        
        # Verify backup content
        backup_data = json.loads(backup_path.read_text())
        assert len(backup_data) == 1
        assert backup_data[0]["user_input"] == "Hello"
    
    def test_safe_reset_empty_memory(self, manager):
        """Should return None if nothing to backup"""
        backup_path = manager.safe_reset()
        assert backup_path is None
    
    def test_load_from_backup(self, manager, temp_memory_dir):
        """Should restore from backup"""
        manager.add_turn("Hello", "World")
        manager.add_turn("Goodbye", "Farewell")
        
        backup_path = manager.safe_reset()
        assert len(manager) == 0
        
        manager.load_from_backup(backup_path)
        assert len(manager) == 2
    
    def test_clear(self, manager):
        """Should clear without backup"""
        manager.add_turn("Hello", "World")
        manager.clear()
        
        assert len(manager) == 0
    
    def test_get_stats(self, manager):
        """Should return statistics"""
        manager.add_turn("Hello", "World")
        
        stats = manager.get_stats()
        
        assert stats["npc_name"] == "TestNPC"
        assert stats["total_turns"] == 1
        assert stats["total_user_chars"] == 5  # "Hello"
        assert stats["total_npc_chars"] == 5  # "World"
    
    def test_search(self, manager):
        """Should search conversation history"""
        manager.add_turn("Where is the Jarl?", "In Dragonsreach")
        manager.add_turn("What about the market?", "Down the street")
        
        results = manager.search("Jarl")
        
        assert len(results) == 1
        assert "Jarl" in results[0].user_input
    
    def test_get_recent(self, manager):
        """Should get recent turns"""
        for i in range(5):
            manager.add_turn(f"Q{i}", f"A{i}")
        
        recent = manager.get_recent(count=2)
        
        assert len(recent) == 2
        assert recent[0].user_input == "Q3"
        assert recent[1].user_input == "Q4"
    
    def test_persistence(self, temp_memory_dir):
        """Should persist across instances"""
        manager1 = ConversationManager("PersistTest", str(temp_memory_dir))
        manager1.add_turn("Hello", "World")
        
        # Create new instance
        manager2 = ConversationManager("PersistTest", str(temp_memory_dir))
        
        assert len(manager2) == 1
        assert manager2.history[0].user_input == "Hello"


class TestListBackups:
    """Test list_backups function"""
    
    def test_list_backups(self, temp_memory_dir):
        """Should list backup files"""
        # Create some backups manually
        backup1 = temp_memory_dir / "NPC1_backup_20240101_000000.json"
        backup2 = temp_memory_dir / "NPC2_backup_20240102_000000.json"
        
        backup1.write_text('[{"user_input": "a", "npc_response": "b", "timestamp": "t", "metadata": {}}]')
        backup2.write_text('[{"user_input": "c", "npc_response": "d", "timestamp": "t", "metadata": {}}]')
        
        backups = list_backups(str(temp_memory_dir))
        
        assert len(backups) == 2
    
    def test_list_backups_by_npc(self, temp_memory_dir):
        """Should filter by NPC name"""
        backup1 = temp_memory_dir / "NPC1_backup_20240101_000000.json"
        backup2 = temp_memory_dir / "NPC2_backup_20240102_000000.json"
        
        backup1.write_text('[{"user_input": "a", "npc_response": "b", "timestamp": "t", "metadata": {}}]')
        backup2.write_text('[{"user_input": "c", "npc_response": "d", "timestamp": "t", "metadata": {}}]')
        
        backups = list_backups(str(temp_memory_dir), npc_name="NPC1")
        
        assert len(backups) == 1
        assert backups[0]["npc_name"] == "NPC1"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
