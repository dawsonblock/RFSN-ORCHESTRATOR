#!/usr/bin/env python3
"""
RFSN Hot Config Reload v8.2
Watch config file and apply changes without restart.
"""

import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class ConfigChange:
    """Represents a config change event"""
    key: str
    old_value: Any
    new_value: Any
    timestamp: datetime = field(default_factory=datetime.utcnow)


class ConfigWatcher:
    """
    Watch config files for changes and trigger callbacks.
    
    Features:
    - File modification detection
    - Config validation before applying
    - Callback system for change notifications
    - Rollback on error
    """
    
    def __init__(
        self,
        config_path: str = "config.json",
        poll_interval: float = 5.0
    ):
        self.config_path = Path(config_path)
        self.poll_interval = poll_interval
        
        self._current_config: Dict[str, Any] = {}
        self._last_mtime: float = 0
        self._callbacks: Dict[str, List[Callable]] = {}
        self._validators: Dict[str, Callable] = {}
        
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        
        # Load initial config
        self._load_config()
    
    def _load_config(self) -> bool:
        """Load config from file"""
        if not self.config_path.exists():
            logger.warning(f"Config file not found: {self.config_path}")
            return False
        
        try:
            with open(self.config_path, 'r') as f:
                new_config = json.load(f)
            
            self._last_mtime = self.config_path.stat().st_mtime
            self._current_config = new_config
            logger.info(f"Config loaded: {self.config_path}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to load config: {e}")
            return False
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get a config value"""
        with self._lock:
            return self._current_config.get(key, default)
    
    def get_all(self) -> Dict[str, Any]:
        """Get entire config"""
        with self._lock:
            return self._current_config.copy()
    
    def on_change(self, key: str, callback: Callable[[ConfigChange], None]):
        """
        Register callback for config key changes.
        
        Args:
            key: Config key to watch (use "*" for all changes)
            callback: Function to call with ConfigChange
        """
        if key not in self._callbacks:
            self._callbacks[key] = []
        self._callbacks[key].append(callback)
    
    def add_validator(self, key: str, validator: Callable[[Any], bool]):
        """
        Add a validator for a config key.
        
        Args:
            key: Config key to validate
            validator: Function that returns True if value is valid
        """
        self._validators[key] = validator
    
    def _validate_config(self, new_config: Dict[str, Any]) -> List[str]:
        """Validate new config, return list of errors"""
        errors = []
        
        for key, validator in self._validators.items():
            if key in new_config:
                try:
                    if not validator(new_config[key]):
                        errors.append(f"Validation failed for '{key}'")
                except Exception as e:
                    errors.append(f"Validator error for '{key}': {e}")
        
        return errors
    
    def _notify_changes(self, old_config: Dict[str, Any], new_config: Dict[str, Any]):
        """Notify callbacks of changes"""
        all_keys = set(old_config.keys()) | set(new_config.keys())
        
        for key in all_keys:
            old_val = old_config.get(key)
            new_val = new_config.get(key)
            
            if old_val != new_val:
                change = ConfigChange(key=key, old_value=old_val, new_value=new_val)
                logger.info(f"Config changed: {key} = {new_val}")
                
                # Call specific callbacks
                for callback in self._callbacks.get(key, []):
                    try:
                        callback(change)
                    except Exception as e:
                        logger.error(f"Callback error for {key}: {e}")
                
                # Call wildcard callbacks
                for callback in self._callbacks.get("*", []):
                    try:
                        callback(change)
                    except Exception as e:
                        logger.error(f"Wildcard callback error: {e}")
    
    def _check_for_changes(self):
        """Check if config file has changed"""
        if not self.config_path.exists():
            return
        
        try:
            current_mtime = self.config_path.stat().st_mtime
            
            if current_mtime > self._last_mtime:
                logger.info("Config file modified, reloading...")
                
                # Load new config
                with open(self.config_path, 'r') as f:
                    new_config = json.load(f)
                
                # Validate
                errors = self._validate_config(new_config)
                if errors:
                    logger.error(f"Config validation failed: {errors}")
                    return
                
                # Apply changes
                with self._lock:
                    old_config = self._current_config.copy()
                    self._current_config = new_config
                    self._last_mtime = current_mtime
                
                # Notify
                self._notify_changes(old_config, new_config)
                
        except Exception as e:
            logger.error(f"Error checking config: {e}")
    
    def _watch_loop(self):
        """Background thread watching for changes"""
        logger.info(f"Config watcher started: {self.config_path}")
        
        while self._running:
            self._check_for_changes()
            time.sleep(self.poll_interval)
        
        logger.info("Config watcher stopped")
    
    def start(self):
        """Start watching for config changes"""
        if self._running:
            return
        
        self._running = True
        self._thread = threading.Thread(target=self._watch_loop, daemon=True)
        self._thread.start()
    
    def stop(self):
        """Stop watching for config changes"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=self.poll_interval * 2)
    
    def reload(self) -> bool:
        """Force reload config"""
        with self._lock:
            old_config = self._current_config.copy()
        
        if self._load_config():
            self._notify_changes(old_config, self._current_config)
            return True
        return False


# =============================================================================
# GLOBAL CONFIG INSTANCE
# =============================================================================

_config: Optional[ConfigWatcher] = None


def init_config(config_path: str = "config.json", watch: bool = True) -> ConfigWatcher:
    """
    Initialize global config instance.
    
    Args:
        config_path: Path to config file
        watch: Enable file watching
    
    Returns:
        ConfigWatcher instance
    """
    global _config
    
    _config = ConfigWatcher(config_path)
    
    # Add default validators
    _config.add_validator("max_tokens", lambda v: isinstance(v, int) and 0 < v < 10000)
    _config.add_validator("temperature", lambda v: isinstance(v, (int, float)) and 0 <= v <= 2)
    _config.add_validator("piper_enabled", lambda v: isinstance(v, bool))
    
    if watch:
        _config.start()
    
    return _config


def get_config() -> ConfigWatcher:
    """Get global config instance"""
    global _config
    
    if _config is None:
        _config = init_config()
    
    return _config


def get(key: str, default: Any = None) -> Any:
    """Shorthand for getting config value"""
    return get_config().get(key, default)


if __name__ == "__main__":
    # Quick test
    import tempfile
    
    print("Testing Hot Config Reload...")
    
    # Create temp config
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump({"test_key": "initial_value", "number": 42}, f)
        config_path = f.name
    
    # Initialize watcher
    watcher = ConfigWatcher(config_path, poll_interval=1.0)
    
    # Add change callback
    changes = []
    watcher.on_change("*", lambda c: changes.append(c))
    
    # Start watching
    watcher.start()
    
    print(f"Initial config: {watcher.get_all()}")
    
    # Modify config
    time.sleep(2)
    with open(config_path, 'w') as f:
        json.dump({"test_key": "updated_value", "number": 99}, f)
    
    # Wait for detection
    time.sleep(2)
    
    print(f"Updated config: {watcher.get_all()}")
    print(f"Changes detected: {len(changes)}")
    
    for change in changes:
        print(f"  {change.key}: {change.old_value} -> {change.new_value}")
    
    # Cleanup
    watcher.stop()
    os.unlink(config_path)
    
    print("\nTest complete!")
