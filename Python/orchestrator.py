#!/usr/bin/env python3
"""
RFSN GenAI Orchestrator v8.1 - Production Streaming Build
Complete system with Piper TTS, safe reset, and comprehensive error handling.
"""

import asyncio
import json
import logging
import time
import os
from pathlib import Path
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from datetime import datetime

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Import streaming modules
from streaming_engine import StreamingMantellaEngine, StreamingVoiceSystem, SentenceChunk, StreamingMetrics, RFSNState
from piper_tts import PiperTTSEngine, setup_piper_voice
from memory_manager import ConversationManager, list_backups

# Configuration
CONFIG_PATH = Path(__file__).parent.parent / "config.json"
MEMORY_DIR = Path(__file__).parent.parent / "memory"
MEMORY_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# API Models
class DialogueRequest(BaseModel):
    user_input: str
    npc_state: Dict[str, Any]
    enable_voice: bool = True


class SafeResetRequest(BaseModel):
    npc_name: str


class RestoreRequest(BaseModel):
    filename: str


class PerformanceSettings(BaseModel):
    temperature: Optional[float] = None
    max_queue_size: Optional[int] = None
    max_tokens: Optional[int] = None


# FastAPI App
app = FastAPI(
    title="RFSN GenAI Orchestrator v8.1",
    description="Production streaming system with Piper TTS and safe memory management",
    version="8.1.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global instances
config: Dict[str, Any] = {}
streaming_engine: Optional[StreamingMantellaEngine] = None
piper_engine: Optional[PiperTTSEngine] = None
conversation_managers: Dict[str, ConversationManager] = {}
active_ws: List[WebSocket] = []


@app.on_event("startup")
async def startup_event():
    """Initialize all engines on startup"""
    global streaming_engine, piper_engine, config
    
    logger.info("=" * 70)
    logger.info("RFSN ORCHESTRATOR v8.1 - STARTING UP")
    logger.info("=" * 70)
    
    # Load configuration
    if CONFIG_PATH.exists():
        config = json.loads(CONFIG_PATH.read_text())
    else:
        config = {
            "model_path": "Models/Mantella-Skyrim-Llama-3-8B-Q4_K_M.gguf",
            "piper_enabled": True,
            "memory_enabled": True,
            "max_queue_size": 3,
            "temperature": 0.7,
            "max_tokens": 80,
            "context_limit": 4
        }
        CONFIG_PATH.write_text(json.dumps(config, indent=2))
    
    # Setup Piper TTS
    if config.get("piper_enabled", True):
        try:
            model_path, config_path = setup_piper_voice()
            if model_path:
                piper_engine = PiperTTSEngine(model_path, config_path, speaker_id=0)
                logger.info("Piper TTS initialized")
        except Exception as e:
            logger.error(f"Piper failed: {e}. Disabling voice.")
            piper_engine = None
    
    # Initialize streaming LLM
    model_path = Path(config["model_path"])
    streaming_engine = StreamingMantellaEngine(str(model_path) if model_path.exists() else None)
    
    # Connect TTS to voice system
    if piper_engine and streaming_engine:
        streaming_engine.voice.set_tts_engine(piper_engine)
    
    logger.info("Startup complete!")


@app.on_event("shutdown")
async def shutdown_event():
    """Graceful shutdown"""
    logger.info("Shutting down engines...")
    
    if piper_engine:
        piper_engine.shutdown()
    if streaming_engine:
        streaming_engine.shutdown()
    
    logger.info("Shutdown complete")


@app.websocket("/ws/metrics")
async def websocket_metrics(websocket: WebSocket):
    """Real-time metrics streaming to dashboard"""
    await websocket.accept()
    active_ws.append(websocket)
    
    try:
        await websocket.send_json({"type": "connected", "message": "Metrics stream active"})
        while True:
            await asyncio.sleep(30)
    except WebSocketDisconnect:
        pass
    finally:
        if websocket in active_ws:
            active_ws.remove(websocket)


async def broadcast_metrics(metrics: StreamingMetrics):
    """Broadcast performance metrics to all connected dashboards"""
    for ws in list(active_ws):
        try:
            await ws.send_json({
                "type": "metrics",
                "first_token_ms": metrics.first_token_ms,
                "first_sentence_ms": metrics.first_sentence_ms,
                "total_generation_ms": metrics.total_generation_ms,
                "tts_queue_size": metrics.tts_queue_size,
                "dropped_sentences": metrics.dropped_sentences
            })
        except Exception:
            active_ws.remove(ws)


def _cleanup_tokens(text: str) -> str:
    """Remove special tokens that might slip through"""
    bad_tokens = ["&lt;|eot_id|&gt;", "&lt;|end|&gt;", "&lt;|"]
    for token in bad_tokens:
        text = text.replace(token, "")
    return text.strip()


@app.post("/api/dialogue/stream")
async def stream_dialogue(request: DialogueRequest):
    """
    Main streaming endpoint:
    - Generates tokens in real-time
    - Detects sentences smartly
    - Queues to Piper TTS with backpressure
    - Saves to memory on completion
    """
    if not streaming_engine:
        raise HTTPException(status_code=503, detail="Streaming engine not ready")
    
    # Build RFSN state
    state = RFSNState(**request.npc_state)
    
    # Get/create memory manager
    npc_name = state.npc_name
    if npc_name not in conversation_managers:
        conversation_managers[npc_name] = ConversationManager(npc_name, str(MEMORY_DIR))
    memory = conversation_managers[npc_name]
    
    # Build compact prompt
    history = memory.get_context_window(limit=config.get("context_limit", 4)) if config.get("memory_enabled") else ""
    system_prompt = f"You are {state.npc_name}. {state.get_attitude_instruction()} Keep it short (1-2 sentences)."
    full_prompt = f"System: {system_prompt}\n{history}\nPlayer: {request.user_input}\n{state.npc_name}:"
    
    # Stream response
    async def stream_generator():
        full_response = ""
        first_chunk_sent = False
        
        for chunk in streaming_engine.generate_streaming(full_prompt):
            clean_text = _cleanup_tokens(chunk.text)
            
            if not first_chunk_sent:
                first_chunk_sent = True
                logger.info(f"First token: {chunk.latency_ms:.0f}ms")
            
            yield f"data: {json.dumps({'sentence': clean_text, 'is_final': chunk.is_final, 'latency_ms': chunk.latency_ms})}\n\n"
            full_response += clean_text
            
            if chunk.is_final and config.get("memory_enabled"):
                memory.add_turn(request.user_input, full_response)
                logger.info(f"Saved {len(full_response)} chars to {npc_name} memory")
        
        await broadcast_metrics(streaming_engine.voice.metrics)
    
    return StreamingResponse(stream_generator(), media_type="text/event-stream")


@app.post("/api/memory/{npc_name}/safe_reset")
async def safe_reset_memory(npc_name: str):
    """Safe reset with automatic backup"""
    if npc_name not in conversation_managers:
        conversation_managers[npc_name] = ConversationManager(npc_name, str(MEMORY_DIR))
    
    manager = conversation_managers[npc_name]
    
    if len(manager) == 0:
        return {"status": "nothing_to_backup", "message": "No conversation history to backup"}
    
    backup_path = manager.safe_reset()
    
    if backup_path:
        backup_data = json.loads(backup_path.read_text())
        return {
            "status": "reset_with_backup",
            "backup_path": str(backup_path),
            "messages_archived": len(backup_data),
            "file_size_bytes": backup_path.stat().st_size,
            "timestamp": backup_path.stat().st_mtime
        }
    
    return {"status": "error", "message": "Failed to create backup"}


@app.get("/api/memory/{npc_name}/stats")
async def get_memory_stats(npc_name: str):
    """Get detailed memory statistics"""
    if npc_name not in conversation_managers:
        conversation_managers[npc_name] = ConversationManager(npc_name, str(MEMORY_DIR))
    
    return conversation_managers[npc_name].get_stats()


@app.get("/api/memory/backups")
async def get_backups():
    """List all available memory backups"""
    backups = list_backups(str(MEMORY_DIR))
    return {"backups": backups, "total_backups": len(backups)}


@app.post("/api/memory/restore")
async def restore_backup(request: RestoreRequest):
    """Restore NPC memory from backup file"""
    backup_path = MEMORY_DIR / request.filename
    
    if not backup_path.exists():
        raise HTTPException(status_code=404, detail=f"Backup not found: {request.filename}")
    
    # Parse NPC name from filename
    npc_name = request.filename.split("_backup_")[0]
    
    if npc_name not in conversation_managers:
        conversation_managers[npc_name] = ConversationManager(npc_name, str(MEMORY_DIR))
    
    try:
        conversation_managers[npc_name].load_from_backup(backup_path)
        return {
            "status": "restored",
            "npc_name": npc_name,
            "messages_restored": len(conversation_managers[npc_name]),
            "backup_filename": request.filename
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Restore failed: {str(e)}")


@app.delete("/api/memory/{npc_name}")
async def clear_memory(npc_name: str):
    """Clear memory without backup (destructive)"""
    if npc_name not in conversation_managers:
        conversation_managers[npc_name] = ConversationManager(npc_name, str(MEMORY_DIR))
    
    conversation_managers[npc_name].clear()
    return {"status": "cleared", "npc_name": npc_name}


@app.get("/api/status")
async def get_status():
    """System health check"""
    return {
        "status": "healthy",
        "version": "8.1",
        "components": {
            "streaming_llm": streaming_engine is not None,
            "piper_tts": piper_engine is not None,
            "memory_system": True,
            "active_websockets": len(active_ws)
        },
        "performance": {
            "target_latency_ms": 1500,
            "backpressure_queue_size": config.get("max_queue_size", 3)
        }
    }


@app.post("/api/tune-performance")
async def tune_performance(settings: PerformanceSettings):
    """Adjust performance settings at runtime"""
    global config
    
    if settings.temperature is not None:
        config["temperature"] = settings.temperature
    if settings.max_queue_size is not None:
        config["max_queue_size"] = settings.max_queue_size
    if settings.max_tokens is not None:
        config["max_tokens"] = settings.max_tokens
    
    CONFIG_PATH.write_text(json.dumps(config, indent=2))
    
    return {"status": "updated", "new_settings": config}


if __name__ == "__main__":
    import uvicorn
    
    print("=" * 70)
    print("RFSN ORCHESTRATOR v8.1 - PRODUCTION STREAMING MODE")
    print("Features: Smart boundaries, backpressure, Piper TTS, safe reset")
    print("Target Latency: <1.5s")
    print("=" * 70)
    
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
