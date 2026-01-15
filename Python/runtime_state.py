# runtime_state.py
# Atomic runtime state management - prevents half-applied config during reloads
# All runtime components are owned by a single RuntimeState object
# Hot reloads swap the entire state atomically

from dataclasses import dataclass, field
import threading
from typing import Optional, Any, Dict
import logging

logger = logging.getLogger(__name__)


@dataclass
class RuntimeState:
    """
    Immutable snapshot of runtime configuration and component references.
    
    All components read from this. To change config, create a new RuntimeState
    and swap() it atomically. This prevents "engine A has new config, engine B
    still using old config" bugs.
    """
    # Core engines (None = not loaded/available)
    streaming_engine: Optional[Any] = None
    piper_engine: Optional[Any] = None
    xva_engine: Optional[Any] = None
    
    # Configuration snapshot (read-only after creation)
    config: Dict[str, Any] = field(default_factory=dict)
    
    # Learning layer components
    policy_adapter: Optional[Any] = None
    trainer: Optional[Any] = None
    reward_model: Optional[Any] = None
    learning_contract: Optional[Any] = None
    
    # Memory/retrieval
    memory_manager: Optional[Any] = None
    memory_governance: Optional[Any] = None
    intent_gate: Optional[Any] = None
    streaming_pipeline: Optional[Any] = None
    observability: Optional[Any] = None
    event_recorder: Optional[Any] = None
    state_machine: Optional[Any] = None
    world_model: Optional[Any] = None
    action_scorer: Optional[Any] = None
    npc_action_bandit: Optional[Any] = None
    hot_config: Optional[Any] = None
    
    def is_healthy(self) -> bool:
        """Returns True if minimum required components are loaded"""
        return (
            self.streaming_engine is not None and 
            self.streaming_engine.llm is not None
        )
    
    def get_tts_engine(self, engine_type: str = "piper"):
        """Get TTS engine by type"""
        if engine_type == "piper":
            return self.piper_engine
        elif engine_type == "xvasynth":
            return self.xva_engine
        return None


class Runtime:
    """
    Thread-safe singleton that owns the current RuntimeState.
    
    Usage:
        runtime = Runtime()
        state = runtime.get()  # Get current state (read-only)
        
        # To update, build new state and swap:
        new_state = RuntimeState(streaming_engine=new_engine, ...)
        runtime.swap(new_state)
    """
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._state = RuntimeState()
                    cls._instance._state_lock = threading.RLock()
        return cls._instance
    
    def get(self) -> RuntimeState:
        """Get current runtime state snapshot (thread-safe read)"""
        with self._state_lock:
            return self._state
    
    def swap(self, new_state: RuntimeState) -> RuntimeState:
        """
        Atomically swap runtime state. Returns old state for cleanup.
        
        Args:
            new_state: The new RuntimeState to install
            
        Returns:
            The previous RuntimeState (caller should cleanup if needed)
        """
        with self._state_lock:
            old_state = self._state
            self._state = new_state
            logger.info("[Runtime] State swapped atomically")
            return old_state
    
    def update(self, **kwargs) -> None:
        """
        Convenience method: create new state with specified updates.
        
        Usage:
            runtime.update(piper_engine=new_piper)
        """
        with self._state_lock:
            current = self._state
            # Create new dataclass with updated fields
            new_state = RuntimeState(
                streaming_engine=kwargs.get('streaming_engine', current.streaming_engine),
                piper_engine=kwargs.get('piper_engine', current.piper_engine),
                xva_engine=kwargs.get('xva_engine', current.xva_engine),
                config=kwargs.get('config', current.config),
                policy_adapter=kwargs.get('policy_adapter', current.policy_adapter),
                trainer=kwargs.get('trainer', current.trainer),
                reward_model=kwargs.get('reward_model', current.reward_model),
                learning_contract=kwargs.get('learning_contract', current.learning_contract),
                memory_manager=kwargs.get('memory_manager', current.memory_manager),
                memory_governance=kwargs.get('memory_governance', current.memory_governance),
                intent_gate=kwargs.get('intent_gate', current.intent_gate),
                streaming_pipeline=kwargs.get('streaming_pipeline', current.streaming_pipeline),
                observability=kwargs.get('observability', current.observability),
                event_recorder=kwargs.get('event_recorder', current.event_recorder),
                state_machine=kwargs.get('state_machine', current.state_machine),
                npc_action_bandit=kwargs.get('npc_action_bandit', current.npc_action_bandit),
                hot_config=kwargs.get('hot_config', current.hot_config),
            )
            self._state = new_state


# Global runtime instance
runtime = Runtime()
