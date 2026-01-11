#!/usr/bin/env python3
"""
RFSN Model Manager v8.2
Download, verify, and manage LLM and TTS models with retry logic.
"""

import hashlib
import json
import logging
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Optional, Dict, Any, Callable
from dataclasses import dataclass
from urllib.parse import urlparse

try:
    import requests
    from tqdm import tqdm
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


@dataclass
class ModelInfo:
    """Model metadata"""
    name: str
    url: str
    size_bytes: int
    sha256: str
    description: str
    category: str  # "llm" or "tts"


# Known models with checksums
KNOWN_MODELS: Dict[str, ModelInfo] = {
    "mantella-skyrim-llama3-8b-q4": ModelInfo(
        name="Mantella-Skyrim-Llama-3-8B-Q4_K_M.gguf",
        url="https://huggingface.co/art-from-the-machine/Mantella-Skyrim-Llama-3-8B-GGUF/resolve/main/Mantella-Skyrim-Llama-3-8B-Q4_K_M.gguf",
        size_bytes=4_920_000_000,  # ~4.9GB
        sha256="",  # Will be computed on first download
        description="Mantella Skyrim fine-tuned Llama 3 8B (Q4_K_M quantization)",
        category="llm"
    ),
    "piper-lessac-medium": ModelInfo(
        name="en_US-lessac-medium.onnx",
        url="https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx",
        size_bytes=130_000_000,  # ~130MB
        sha256="",  # Will be computed on first download
        description="Piper TTS English voice (lessac, medium quality)",
        category="tts"
    ),
    "piper-lessac-medium-config": ModelInfo(
        name="en_US-lessac-medium.onnx.json",
        url="https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json",
        size_bytes=5_000,  # ~5KB
        sha256="",
        description="Piper TTS config for lessac voice",
        category="tts"
    ),
}


class DownloadError(Exception):
    """Download failed after retries"""
    pass


class ChecksumError(Exception):
    """Checksum verification failed"""
    pass


class ModelManager:
    """
    Manages model downloads with:
    - Retry logic with exponential backoff
    - Checksum verification
    - Progress reporting
    - Resume support for partial downloads
    """
    
    DEFAULT_RETRIES = 3
    DEFAULT_BACKOFF = 2.0
    CHUNK_SIZE = 8192
    
    def __init__(self, models_dir: str = "Models"):
        self.models_dir = Path(models_dir)
        self.models_dir.mkdir(parents=True, exist_ok=True)
        
        self.llm_dir = self.models_dir
        self.tts_dir = self.models_dir / "piper"
        self.tts_dir.mkdir(parents=True, exist_ok=True)
        
        # Load cached checksums
        self.checksum_file = self.models_dir / ".checksums.json"
        self.checksums = self._load_checksums()
    
    def _load_checksums(self) -> Dict[str, str]:
        """Load cached checksums from disk"""
        if self.checksum_file.exists():
            try:
                return json.loads(self.checksum_file.read_text())
            except Exception:
                pass
        return {}
    
    def _save_checksums(self):
        """Save checksums to disk"""
        self.checksum_file.write_text(json.dumps(self.checksums, indent=2))
    
    def _compute_sha256(self, filepath: Path, progress_callback: Callable = None) -> str:
        """Compute SHA256 hash of a file"""
        sha256 = hashlib.sha256()
        total = filepath.stat().st_size
        processed = 0
        
        with open(filepath, 'rb') as f:
            while chunk := f.read(self.CHUNK_SIZE * 128):  # Larger chunks for hashing
                sha256.update(chunk)
                processed += len(chunk)
                if progress_callback:
                    progress_callback(processed, total)
        
        return sha256.hexdigest()
    
    def _download_with_retry(
        self, 
        url: str, 
        dest: Path, 
        expected_size: int = 0,
        retries: int = DEFAULT_RETRIES,
        backoff: float = DEFAULT_BACKOFF
    ) -> bool:
        """
        Download file with retry logic and resume support.
        """
        if not HAS_REQUESTS:
            raise ImportError("requests and tqdm required: pip install requests tqdm")
        
        for attempt in range(retries):
            try:
                # Check for partial download
                resume_pos = 0
                if dest.exists():
                    resume_pos = dest.stat().st_size
                    if expected_size and resume_pos >= expected_size:
                        logger.info(f"File already complete: {dest.name}")
                        return True
                
                headers = {}
                if resume_pos > 0:
                    headers['Range'] = f'bytes={resume_pos}-'
                    logger.info(f"Resuming download from {resume_pos / 1024 / 1024:.1f} MB")
                
                response = requests.get(url, stream=True, headers=headers, timeout=30)
                response.raise_for_status()
                
                # Get total size
                total = int(response.headers.get('content-length', 0)) + resume_pos
                if expected_size and total != expected_size:
                    logger.warning(f"Size mismatch: expected {expected_size}, got {total}")
                
                # Open in append mode if resuming
                mode = 'ab' if resume_pos > 0 else 'wb'
                
                with open(dest, mode) as f:
                    with tqdm(
                        total=total,
                        initial=resume_pos,
                        unit='B',
                        unit_scale=True,
                        desc=dest.name,
                        ncols=80
                    ) as pbar:
                        for chunk in response.iter_content(chunk_size=self.CHUNK_SIZE):
                            f.write(chunk)
                            pbar.update(len(chunk))
                
                logger.info(f"Download complete: {dest.name}")
                return True
                
            except requests.RequestException as e:
                wait_time = backoff * (2 ** attempt)
                logger.warning(f"Download failed (attempt {attempt + 1}/{retries}): {e}")
                
                if attempt < retries - 1:
                    logger.info(f"Retrying in {wait_time:.1f}s...")
                    time.sleep(wait_time)
                else:
                    raise DownloadError(f"Failed after {retries} attempts: {e}")
        
        return False
    
    def download_model(
        self, 
        model_key: str, 
        verify: bool = True,
        force: bool = False
    ) -> Path:
        """
        Download a model by key.
        
        Args:
            model_key: Key from KNOWN_MODELS
            verify: Verify checksum after download
            force: Re-download even if exists
        
        Returns:
            Path to downloaded model
        """
        if model_key not in KNOWN_MODELS:
            available = ", ".join(KNOWN_MODELS.keys())
            raise ValueError(f"Unknown model: {model_key}. Available: {available}")
        
        model = KNOWN_MODELS[model_key]
        
        # Determine destination
        if model.category == "llm":
            dest = self.llm_dir / model.name
        else:
            dest = self.tts_dir / model.name
        
        # Check if already exists
        if dest.exists() and not force:
            if verify and model_key in self.checksums:
                logger.info(f"Verifying existing model: {model.name}")
                actual_hash = self._compute_sha256(dest)
                if actual_hash == self.checksums[model_key]:
                    logger.info(f"Model verified: {model.name}")
                    return dest
                else:
                    logger.warning(f"Checksum mismatch, re-downloading: {model.name}")
            else:
                logger.info(f"Model exists: {model.name}")
                return dest
        
        # Download
        logger.info(f"Downloading: {model.description}")
        self._download_with_retry(model.url, dest, model.size_bytes)
        
        # Verify and cache checksum
        if verify:
            logger.info(f"Computing checksum for: {model.name}")
            actual_hash = self._compute_sha256(dest)
            
            if model.sha256 and actual_hash != model.sha256:
                raise ChecksumError(f"Checksum mismatch for {model.name}")
            
            self.checksums[model_key] = actual_hash
            self._save_checksums()
            logger.info(f"Checksum cached: {actual_hash[:16]}...")
        
        return dest
    
    def download_llm(self, model_key: str = "mantella-skyrim-llama3-8b-q4") -> Path:
        """Download the default LLM model"""
        return self.download_model(model_key)
    
    def download_tts(self, voice: str = "piper-lessac-medium") -> tuple:
        """Download TTS voice model and config"""
        model_path = self.download_model(voice)
        config_path = self.download_model(f"{voice}-config")
        return model_path, config_path
    
    def list_models(self) -> Dict[str, Dict[str, Any]]:
        """List all known models and their status"""
        result = {}
        
        for key, model in KNOWN_MODELS.items():
            if model.category == "llm":
                path = self.llm_dir / model.name
            else:
                path = self.tts_dir / model.name
            
            result[key] = {
                "name": model.name,
                "description": model.description,
                "category": model.category,
                "size_mb": model.size_bytes / 1024 / 1024,
                "exists": path.exists(),
                "path": str(path) if path.exists() else None,
                "verified": key in self.checksums
            }
        
        return result
    
    def verify_all(self) -> Dict[str, bool]:
        """Verify all downloaded models"""
        results = {}
        
        for key, model in KNOWN_MODELS.items():
            if model.category == "llm":
                path = self.llm_dir / model.name
            else:
                path = self.tts_dir / model.name
            
            if not path.exists():
                results[key] = False
                continue
            
            try:
                actual_hash = self._compute_sha256(path)
                
                if key in self.checksums:
                    results[key] = actual_hash == self.checksums[key]
                else:
                    # First time verification, cache it
                    self.checksums[key] = actual_hash
                    results[key] = True
            except Exception as e:
                logger.error(f"Verification failed for {key}: {e}")
                results[key] = False
        
        self._save_checksums()
        return results
    
    def get_model_path(self, model_key: str) -> Optional[Path]:
        """Get path to a model if it exists"""
        if model_key not in KNOWN_MODELS:
            return None
        
        model = KNOWN_MODELS[model_key]
        if model.category == "llm":
            path = self.llm_dir / model.name
        else:
            path = self.tts_dir / model.name
        
        return path if path.exists() else None


def setup_models(download_llm: bool = True, download_tts: bool = True) -> Dict[str, Path]:
    """
    One-call setup for all required models.
    
    Returns dict with paths to downloaded models.
    """
    manager = ModelManager()
    paths = {}
    
    if download_tts:
        logger.info("Setting up TTS voice...")
        model_path, config_path = manager.download_tts()
        paths["tts_model"] = model_path
        paths["tts_config"] = config_path
    
    if download_llm:
        logger.info("Setting up LLM model...")
        try:
            paths["llm"] = manager.download_llm()
        except DownloadError as e:
            logger.error(f"LLM download failed: {e}")
            logger.info("You can manually download and place the model in Models/")
    
    return paths


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="RFSN Model Manager")
    parser.add_argument("command", choices=["list", "download", "verify", "setup"],
                       help="Command to run")
    parser.add_argument("--model", help="Model key to download")
    parser.add_argument("--force", action="store_true", help="Force re-download")
    parser.add_argument("--no-verify", action="store_true", help="Skip verification")
    
    args = parser.parse_args()
    
    manager = ModelManager()
    
    if args.command == "list":
        print("\nAvailable Models:")
        print("-" * 60)
        for key, info in manager.list_models().items():
            status = "✅" if info["exists"] else "❌"
            verified = " (verified)" if info["verified"] else ""
            print(f"{status} {key}: {info['description']}{verified}")
            if info["exists"]:
                print(f"   Path: {info['path']}")
        print()
    
    elif args.command == "download":
        if not args.model:
            print("Error: --model required")
            sys.exit(1)
        path = manager.download_model(args.model, verify=not args.no_verify, force=args.force)
        print(f"Downloaded: {path}")
    
    elif args.command == "verify":
        print("\nVerifying models...")
        results = manager.verify_all()
        for key, valid in results.items():
            status = "✅" if valid else "❌"
            print(f"{status} {key}")
    
    elif args.command == "setup":
        paths = setup_models()
        print("\nSetup complete:")
        for name, path in paths.items():
            print(f"  {name}: {path}")
