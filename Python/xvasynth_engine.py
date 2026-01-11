#!/usr/bin/env python3
"""
RFSN xVASynth Support v8.2
Alternative TTS engine using xVASynth for Skyrim voice models.
"""

import json
import logging
import os
import queue
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

import requests

logger = logging.getLogger(__name__)


@dataclass
class XVASynthVoice:
    """xVASynth voice model info"""
    name: str
    game: str
    model_path: str
    speaker_id: int = 0
    language: str = "en"


class XVASynthEngine:
    """
    xVASynth TTS engine for Skyrim voice synthesis.
    
    Requires xVASynth to be running as a local server.
    Default xVASynth server: http://127.0.0.1:8008
    
    Features:
    - High-quality Skyrim voice models
    - XTTS support for voice cloning
    - Batch synthesis
    - Thread-safe queue-based playback
    """
    
    DEFAULT_HOST = "127.0.0.1"
    DEFAULT_PORT = 8008
    
    # Common Skyrim voice models
    SKYRIM_VOICES = {
        "malecommoner": XVASynthVoice("MaleCommoner", "skyrim", "skyrimse/malecommoner"),
        "femaleyoungeager": XVASynthVoice("FemaleYoungEager", "skyrim", "skyrimse/femaleyoungeager"),
        "malenord": XVASynthVoice("MaleNord", "skyrim", "skyrimse/malenord"),
        "femalenord": XVASynthVoice("FemaleNord", "skyrim", "skyrimse/femalenord"),
        "malecommander": XVASynthVoice("MaleCommander", "skyrim", "skyrimse/malecommander"),
        "femalecommander": XVASynthVoice("FemaleCommander", "skyrim", "skyrimse/femalecommander"),
        "malebrute": XVASynthVoice("MaleBrute", "skyrim", "skyrimse/malebrute"),
        "femaledarkelf": XVASynthVoice("FemaleDarkElf", "skyrim", "skyrimse/femaledarkelf"),
        "maleoldkindly": XVASynthVoice("MaleOldKindly", "skyrim", "skyrimse/maleoldkindly"),
        "femaleoldkindly": XVASynthVoice("FemaleOldKindly", "skyrim", "skyrimse/femaleoldkindly"),
    }
    
    # NPC to voice mapping
    NPC_VOICE_MAP = {
        "Lydia": "femalenord",
        "Jarl Balgruuf": "malenord",
        "Ulfric Stormcloak": "malecommander",
        "General Tullius": "malecommander",
        "Serana": "femaleyoungeager",
        "Farengar": "malecommoner",
        "Aela": "femalenord",
        "Mjoll": "femalenord",
        "Vilkas": "malenord",
        "Farkas": "malebrute",
    }
    
    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        output_dir: str = "tts_output",
        queue_size: int = 3
    ):
        self.base_url = f"http://{host}:{port}"
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.audio_queue = queue.Queue(maxsize=queue_size)
        self._shutdown = False
        self._dropped_count = 0
        self._current_voice: Optional[str] = None
        self._lock = threading.Lock()
        
        # Check server availability
        self.available = self._check_server()
        
        if self.available:
            logger.info(f"xVASynth server connected: {self.base_url}")
        else:
            logger.warning("xVASynth server not available, running in mock mode")
        
        # Start playback worker
        self.worker = threading.Thread(target=self._playback_worker, daemon=True)
        self.worker.start()
    
    def _check_server(self) -> bool:
        """Check if xVASynth server is running"""
        try:
            response = requests.get(f"{self.base_url}/", timeout=2)
            return response.status_code == 200
        except requests.RequestException:
            return False
    
    def get_available_voices(self) -> List[Dict[str, Any]]:
        """Get list of available voices from xVASynth"""
        if not self.available:
            return list(self.SKYRIM_VOICES.values())
        
        try:
            response = requests.get(f"{self.base_url}/getAvailableVoices", timeout=5)
            if response.status_code == 200:
                return response.json()
        except requests.RequestException as e:
            logger.error(f"Failed to get voices: {e}")
        
        return []
    
    def load_voice(self, voice_key: str) -> bool:
        """Load a voice model into xVASynth"""
        if not self.available:
            self._current_voice = voice_key
            return True
        
        if voice_key not in self.SKYRIM_VOICES:
            logger.warning(f"Unknown voice: {voice_key}")
            return False
        
        voice = self.SKYRIM_VOICES[voice_key]
        
        try:
            response = requests.post(
                f"{self.base_url}/loadModel",
                json={
                    "game": voice.game,
                    "model": voice.model_path,
                    "language": voice.language
                },
                timeout=30
            )
            
            if response.status_code == 200:
                self._current_voice = voice_key
                logger.info(f"Loaded voice: {voice.name}")
                return True
            else:
                logger.error(f"Failed to load voice: {response.text}")
                return False
                
        except requests.RequestException as e:
            logger.error(f"Failed to load voice: {e}")
            return False
    
    def get_voice_for_npc(self, npc_name: str) -> str:
        """Get voice key for an NPC"""
        # Check exact match
        if npc_name in self.NPC_VOICE_MAP:
            return self.NPC_VOICE_MAP[npc_name]
        
        # Check partial match
        for name, voice in self.NPC_VOICE_MAP.items():
            if name.lower() in npc_name.lower():
                return voice
        
        # Default to generic voice
        return "malecommoner"
    
    def synthesize(
        self,
        text: str,
        voice_key: Optional[str] = None,
        output_file: Optional[str] = None
    ) -> Optional[Path]:
        """
        Synthesize text to speech.
        
        Args:
            text: Text to synthesize
            voice_key: Voice to use (loads if needed)
            output_file: Output filename (auto-generated if None)
        
        Returns:
            Path to generated audio file, or None on failure
        """
        if not text or not text.strip():
            return None
        
        # Load voice if specified and different
        if voice_key and voice_key != self._current_voice:
            self.load_voice(voice_key)
        
        # Generate output filename
        if not output_file:
            timestamp = int(time.time() * 1000)
            output_file = f"tts_{timestamp}.wav"
        
        output_path = self.output_dir / output_file
        
        if not self.available:
            # Mock mode - create empty file
            logger.debug(f"Mock synthesis: {text[:50]}...")
            output_path.touch()
            return output_path
        
        try:
            response = requests.post(
                f"{self.base_url}/synthesize",
                json={
                    "input": text,
                    "output": str(output_path),
                    "useSR": False,  # Disable super-resolution for speed
                    "useCleanup": True
                },
                timeout=30
            )
            
            if response.status_code == 200:
                logger.debug(f"Synthesized: {text[:50]}...")
                return output_path
            else:
                logger.error(f"Synthesis failed: {response.text}")
                return None
                
        except requests.RequestException as e:
            logger.error(f"Synthesis request failed: {e}")
            return None
    
    def synthesize_batch(
        self,
        texts: List[str],
        voice_key: Optional[str] = None
    ) -> List[Optional[Path]]:
        """Synthesize multiple texts"""
        results = []
        
        for text in texts:
            result = self.synthesize(text, voice_key)
            results.append(result)
        
        return results
    
    def speak(self, text: str, voice_key: Optional[str] = None) -> bool:
        """
        Synthesize and queue for playback.
        
        Returns:
            True if queued, False if dropped
        """
        audio_path = self.synthesize(text, voice_key)
        
        if not audio_path or not audio_path.exists():
            return False
        
        try:
            self.audio_queue.put_nowait(audio_path)
            return True
        except queue.Full:
            # Drop oldest if queue is full
            try:
                self.audio_queue.get_nowait()
                self._dropped_count += 1
            except queue.Empty:
                pass
            
            try:
                self.audio_queue.put_nowait(audio_path)
                return True
            except queue.Full:
                self._dropped_count += 1
                return False
    
    def _playback_worker(self):
        """Background worker for audio playback"""
        logger.info("xVASynth playback worker started")
        
        while not self._shutdown:
            try:
                audio_path = self.audio_queue.get(timeout=0.5)
                
                if audio_path and audio_path.exists():
                    self._play_audio(audio_path)
                    
                    # Cleanup after playback
                    try:
                        audio_path.unlink()
                    except OSError:
                        pass
                        
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Playback error: {e}")
        
        logger.info("xVASynth playback worker stopped")
    
    def _play_audio(self, audio_path: Path):
        """Play audio file using system command"""
        if not audio_path.exists():
            return
        
        try:
            # macOS
            if os.name == 'posix' and os.path.exists('/usr/bin/afplay'):
                subprocess.run(['afplay', str(audio_path)], check=True, timeout=30)
            # Linux
            elif os.name == 'posix':
                subprocess.run(['aplay', str(audio_path)], check=True, timeout=30)
            # Windows
            elif os.name == 'nt':
                import winsound
                winsound.PlaySound(str(audio_path), winsound.SND_FILENAME)
                
        except subprocess.TimeoutExpired:
            logger.warning("Audio playback timed out")
        except Exception as e:
            logger.error(f"Audio playback failed: {e}")
    
    def get_dropped_count(self) -> int:
        """Get count of dropped audio files"""
        return self._dropped_count
    
    def get_queue_size(self) -> int:
        """Get current queue size"""
        return self.audio_queue.qsize()
    
    def shutdown(self):
        """Shutdown the engine"""
        self._shutdown = True
        
        # Clear queue
        while not self.audio_queue.empty():
            try:
                audio_path = self.audio_queue.get_nowait()
                try:
                    audio_path.unlink()
                except OSError:
                    pass
            except queue.Empty:
                break
        
        logger.info("xVASynth engine shutdown")


class TTSEngineManager:
    """
    Manages multiple TTS engines with hot-swapping.
    """
    
    def __init__(self):
        self.engines: Dict[str, Any] = {}
        self.active_engine: Optional[str] = None
        self._lock = threading.Lock()
    
    def register_engine(self, name: str, engine):
        """Register a TTS engine"""
        with self._lock:
            self.engines[name] = engine
            
            if self.active_engine is None:
                self.active_engine = name
    
    def set_active(self, name: str) -> bool:
        """Set the active TTS engine"""
        with self._lock:
            if name in self.engines:
                self.active_engine = name
                logger.info(f"Active TTS engine: {name}")
                return True
            return False
    
    def get_active(self):
        """Get the active engine"""
        with self._lock:
            if self.active_engine and self.active_engine in self.engines:
                return self.engines[self.active_engine]
            return None
    
    def speak(self, text: str, **kwargs) -> bool:
        """Speak using active engine"""
        engine = self.get_active()
        if engine:
            return engine.speak(text, **kwargs)
        return False
    
    def list_engines(self) -> List[Dict[str, Any]]:
        """List registered engines"""
        with self._lock:
            return [
                {
                    "name": name,
                    "active": name == self.active_engine,
                    "available": getattr(engine, 'available', True)
                }
                for name, engine in self.engines.items()
            ]


if __name__ == "__main__":
    # Quick test
    print("Testing xVASynth Engine...")
    
    engine = XVASynthEngine()
    
    print(f"Server available: {engine.available}")
    print(f"Known voices: {len(engine.SKYRIM_VOICES)}")
    
    # Test NPC voice mapping
    for npc in ["Lydia", "Jarl Balgruuf", "Random Guard"]:
        voice = engine.get_voice_for_npc(npc)
        print(f"  {npc} -> {voice}")
    
    # Test synthesis (mock if server not available)
    result = engine.synthesize("Greetings, traveler. What brings you to Whiterun?")
    print(f"Synthesis result: {result}")
    
    engine.shutdown()
    print("Test complete!")
