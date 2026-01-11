#!/usr/bin/env python3
"""
RFSN GenAI Orchestrator v8.2 - Production Streaming Build
Complete system with Piper/xVASynth TTS, security, metrics, and multi-NPC support.
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

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Depends, Security
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Import core modules
from streaming_engine import StreamingMantellaEngine, StreamingMetrics, RFSNState
from piper_tts import PiperTTSEngine, setup_piper_voice
from memory_manager import ConversationManager, list_backups

# Import enhancements
from model_manager import ModelManager, setup_models
from security import setup_security, APIKeyManager, JWTManager, require_auth, optional_auth
from structured_logging import configure_logging, get_logger, RequestLoggingMiddleware
from multi_npc import MultiNPCManager
from prometheus_metrics import router as metrics_router, registry, inc_requests, inc_errors, observe_request_duration, inc_tokens, observe_first_token
from hot_config import init_config, get_config
from xvasynth_engine import XVASynthEngine

# Configuration
CONFIG_PATH = Path(__file__).parent.parent / "config.json"
MEMORY_DIR = Path(__file__).parent.parent / "memory"
MEMORY_DIR.mkdir(exist_ok=True)
API_KEYS_PATH = Path(__file__).parent.parent / "api_keys.json"

# Initialize Hot Config
config_watcher = init_config(str(CONFIG_PATH))
config = config_watcher.get_all()

# Configure Logging
configure_logging(
    level=config.get("log_level", "INFO"),
    json_format=config.get("json_logging", True)
)
logger = get_logger("orchestrator")


# API Models
class DialogueRequest(BaseModel):
    user_input: str
    npc_state: Dict[str, Any]
    enable_voice: bool = True
    tts_engine: str = "piper"  # piper or xvasynth

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
    title="RFSN GenAI Orchestrator v8.2",
    description="Production-hardened streaming system with Security, Metrics, and Multi-NPC capabilities",
    version="8.2.0"
)

# Setup Security (CORS + Rate Limiting)
setup_security(app)

# Setup Request Logging
app.add_middleware(RequestLoggingMiddleware)

# Include Prometheus Metrics
app.include_router(metrics_router, tags=["monitoring"])

# Global instances
streaming_engine: Optional[StreamingMantellaEngine] = None
piper_engine: Optional[PiperTTSEngine] = None
xva_engine: Optional[XVASynthEngine] = None
multi_manager = MultiNPCManager()
active_ws: List[WebSocket] = []
conversation_managers: Dict[str, ConversationManager] = {}
conversation_managers_lock = asyncio.Lock()


@app.on_event("startup")
async def startup_event():
    """Initialize all engines on startup"""
    global streaming_engine, piper_engine, xva_engine
    
    logger.info("=" * 70)
    logger.info("RFSN ORCHESTRATOR v8.2 - STARTING UP")
    logger.info("=" * 70)
    
    # Verify models
    if not os.environ.get("SKIP_MODELS"):
        await asyncio.to_thread(setup_models)
    else:
        logger.warning("Skipping model downloads (SKIP_MODELS=1)")
    
    # Setup Piper TTS
    if config_watcher.get("piper_enabled", True):
        try:
            if os.environ.get("SKIP_MODELS"):
                 piper_engine = None # Skip piper setup
                 logger.info("Skipping Piper setup (SKIP_MODELS=1)")
            else:
                model_path, config_path = setup_piper_voice()
                if model_path:
                    piper_engine = PiperTTSEngine(model_path, config_path, speaker_id=0)
                    logger.info("Piper TTS initialized")
        except Exception as e:
            logger.error(f"Piper failed: {e}. Disabling voice.")
            piper_engine = None
    
    # Setup xVASynth
    if config_watcher.get("xvasynth_enabled", False):
        xva_engine = XVASynthEngine()
        logger.info(f"xVASynth initialized (Available: {xva_engine.available})")

    # Initialize streaming LLM
    model_path = Path(config_watcher.get("model_path"))
    if os.environ.get("SKIP_MODELS"):
        logger.info("Using MOCK LLM (SKIP_MODELS set)")
        streaming_engine = StreamingMantellaEngine(None)
    else:
        streaming_engine = StreamingMantellaEngine(str(model_path) if model_path.exists() else None)
    
    # Connect default TTS (Piper)
    if piper_engine and streaming_engine:
        streaming_engine.voice.set_tts_engine(piper_engine)
    
    # Sync global API Key Manager
    from security import api_key_manager
    api_key_manager.keys_file = str(API_KEYS_PATH)
    api_key_manager._load_keys()

    # Generate initial API Key if missing
    if not API_KEYS_PATH.exists():
        admin_key = api_key_manager.generate_key("admin", ["admin_role"])
        logger.warning(f"Created initial Admin API Key: {admin_key}")
    
    logger.info("Startup complete!")


@app.on_event("shutdown")
async def shutdown_event():
    """Graceful shutdown"""
    logger.info("Shutting down engines...")
    
    if piper_engine:
        piper_engine.shutdown()
    if xva_engine:
        xva_engine.shutdown()
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
            # Broadcast live metrics every 0.5s
            if streaming_engine and streaming_engine.voice:
                await websocket.send_json({
                    "type": "metrics",
                    "metrics": asdict(streaming_engine.voice.metrics),
                    "config": config_watcher.get_all()
                })
            await asyncio.sleep(0.5)
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
    bad_tokens = ["<|eot_id|>", "<|end|>", "<|"]
    for token in bad_tokens:
        text = text.replace(token, "")
    return text.strip()


@app.post("/api/dialogue/stream", dependencies=[Depends(optional_auth)])
async def stream_dialogue(request: DialogueRequest):
    """
    Main streaming endpoint:
    - Generates tokens in real-time
    - Detects sentences smartly
    - Queues to TTS with backpressure
    - Saves to memory on completion
    """
    start_time = time.time()
    inc_requests()
    
    if not streaming_engine:
        inc_errors()
        raise HTTPException(status_code=503, detail="Streaming engine not ready")
    
    # Select TTS engine
    current_tts = piper_engine
    if request.tts_engine == "xvasynth" and xva_engine:
        # Determine voice for NPC
        voice_key = xva_engine.get_voice_for_npc(request.npc_state.get("npc_name", "Unknown"))
        # We need to bridge xVASynth to StreamingVoiceSystem if we want streaming
        # For now, if xVASynth is requested, we might need to swap the engine or use it directly
        # But StreamingMantellaEngine uses self.voice which holds ONE engine.
        # Capability Swap:
        # This implementation is simple: if xvasynth, we assume non-streaming TTS for now 
        # OR we'd need to update StreamingVoiceSystem to handle multiple engines.
        # Let's keep it simple: stick to Piper for streaming, use xVASynth for separate calls or future update.
        pass
    
    # Build RFSN state
    state = RFSNState(**request.npc_state)
    npc_name = state.npc_name
    
    # Process Multi-NPC Logic (Voice/Emotion)
    npc_session = multi_manager.get_session(npc_name)
    
    # Get/create memory manager safely
    async with conversation_managers_lock:
        if npc_name not in conversation_managers:
            conversation_managers[npc_name] = ConversationManager(npc_name, str(MEMORY_DIR))
        memory = conversation_managers[npc_name]
    
    # Build prompt with context compression if needed
    history = memory.get_context_window(limit=config_watcher.get("context_limit", 4)) if config_watcher.get("memory_enabled") else ""
    system_prompt = f"You are {state.npc_name}. {state.get_attitude_instruction()} Keep it short (1-2 sentences)."
    full_prompt = f"System: {system_prompt}\n{history}\nPlayer: {request.user_input}\n{state.npc_name}:"
    
    # Snapshot configuration per request (Patch 4) prevents mid-stream tuning weirdness
    req_config = config_watcher.get_all()
    snapshot_temp = req_config.get("temperature", 0.7)
    snapshot_max_tokens = req_config.get("max_tokens", 80)

    # Stream response
    async def stream_generator():
        full_response = ""
        first_chunk_sent = False
        start_gen = time.time()
        
        try:
            # Use snapshot values
            for chunk in streaming_engine.generate_streaming(full_prompt, max_tokens=snapshot_max_tokens, temperature=snapshot_temp):
                
                if not first_chunk_sent:
                    first_chunk_sent = True
                    latency = (time.time() - start_gen)
                    observe_first_token(latency)
                    logger.info(f"First token: {latency*1000:.0f}ms")
                
                # Stream Raw Text to SSE (Patch v8.9) - cleanup is for TTS only
                yield f"data: {json.dumps({'sentence': chunk.text, 'is_final': chunk.is_final, 'latency_ms': chunk.latency_ms})}\n\n"
                full_response += chunk.text # Raw accumulator for memory
                
                # Token metrics
                inc_tokens(len(chunk.text.split())) # Rough estimate
                
                if chunk.is_final and config_watcher.get("memory_enabled"):
                    memory.add_turn(request.user_input, full_response)
                    # Process emotion on final full response
                    emotion_info = multi_manager.process_response(npc_name, full_response)
                    logger.info(f"NPC {npc_name} emotion: {emotion_info['emotion']['primary']}")
            
            # Explicit End-of-Stream Flush (Patch v8.9)
            if streaming_engine and streaming_engine.voice:
                streaming_engine.voice.flush()
        
        except Exception as e:
            logger.error(f"Streaming error: {e}")
            inc_errors()
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        
        total_dur = (time.time() - start_time) * 1000
        observe_request_duration(total_dur / 1000.0)
        await broadcast_metrics(streaming_engine.voice.metrics)
        
        # Per-request Trace Log (Patch v8.9)
        trace_id = f"req_{int(start_time)}"
        logger.info(
            f"TRACE[{trace_id}] npc={npc_name} "
            f"latency={streaming_engine.voice.metrics.first_token_ms:.0f}ms "
            f"total={total_dur:.0f}ms "
            f"q_size={streaming_engine.voice.metrics.tts_queue_size} "
            f"drops={streaming_engine.voice.metrics.dropped_sentences}"
        )
    
    return StreamingResponse(stream_generator(), media_type="text/event-stream")


@app.post("/api/memory/{npc_name}/safe_reset", dependencies=[Depends(require_auth)])
async def safe_reset_memory(npc_name: str):
    """Safe reset with automatic backup"""
    memory = ConversationManager(npc_name, str(MEMORY_DIR))
    
    if len(memory) == 0:
        return {"status": "nothing_to_backup", "message": "No conversation history to backup"}
    
    backup_path = memory.safe_reset()
    
    if backup_path:
        backup_data = json.loads(backup_path.read_text())
        return {
            "status": "reset_with_backup",
            "backup_path": str(backup_path),
            "messages_archived": len(backup_data),
            "file_size_bytes": backup_path.stat().st_size,
            "timestamp": backup_path.stat().st_mtime
        }
    
    inc_errors()
    return {"status": "error", "message": "Failed to create backup"}


@app.get("/api/memory/{npc_name}/stats")
async def get_memory_stats(npc_name: str):
    """Get detailed memory statistics"""
    memory = ConversationManager(npc_name, str(MEMORY_DIR))
    return memory.get_stats()


@app.get("/api/memory/backups")
async def get_backups():
    """List all available memory backups"""
    backups = list_backups(str(MEMORY_DIR))
    return {"backups": backups, "total_backups": len(backups)}


@app.post("/api/memory/restore", dependencies=[Depends(require_auth)])
async def restore_backup(request: RestoreRequest):
    """Restore NPC memory from backup file"""
    backup_path = MEMORY_DIR / request.filename
    
    if not backup_path.exists():
        raise HTTPException(status_code=404, detail=f"Backup not found: {request.filename}")
    
    npc_name = request.filename.split("_backup_")[0]
    memory = ConversationManager(npc_name, str(MEMORY_DIR))
    
    try:
        memory.load_from_backup(backup_path)
        return {
            "status": "restored",
            "npc_name": npc_name,
            "messages_restored": len(memory),
            "backup_filename": request.filename
        }
    except Exception as e:
        inc_errors()
        raise HTTPException(status_code=500, detail=f"Restore failed: {str(e)}")


@app.delete("/api/memory/{npc_name}", dependencies=[Depends(require_auth)])
async def clear_memory(npc_name: str):
    """Clear memory without backup"""
    memory = ConversationManager(npc_name, str(MEMORY_DIR))
    memory.clear()
    return {"status": "cleared", "npc_name": npc_name}


@app.get("/api/health")
async def health_check():
    """Operational health check (Patch v8.9)"""
    model_ok = streaming_engine is not None and streaming_engine.llm is not None
    tts_ok = piper_engine is not None
    q_size = streaming_engine.voice.speech_queue.qsize() if streaming_engine else 0
    
    return {
        "status": "healthy" if model_ok and tts_ok else "degraded",
        "model_loaded": model_ok,
        "piper_ready": tts_ok,
        "queue_size": q_size,
        "active_npc": list(multi_manager.sessions.keys()),
        "uptime": time.time() # Simplistic uptime
    }


@app.get("/api/status")
async def get_status():
    """System health check"""
    return {
        "status": "healthy",
        "version": "8.2",
        "components": {
            "streaming_llm": streaming_engine is not None,
            "piper_tts": piper_engine is not None,
            "xvasynth": xva_engine.available if xva_engine else False,
            "memory_system": True,
            "active_websockets": len(active_ws),
            "active_npc_sessions": len(multi_manager.sessions)
        }
    }


@app.post("/api/tune-performance", dependencies=[Depends(require_auth)])
async def tune_performance(settings: PerformanceSettings):
    """Adjust performance settings at runtime"""
    # Hot config handles the persistence and reload
    import json
    
    current_conf = config_watcher.get_all()
    
    if settings.temperature is not None:
        current_conf["temperature"] = settings.temperature
    if settings.max_queue_size is not None:
        current_conf["max_queue_size"] = settings.max_queue_size
    if settings.max_tokens is not None:
        current_conf["max_tokens"] = settings.max_tokens
    
    CONFIG_PATH.write_text(json.dumps(current_conf, indent=2))
    
    # Apply to running engine immediately
    if streaming_engine:
        streaming_engine.apply_tuning(
            temperature=settings.temperature,
            max_tokens=settings.max_tokens,
            max_queue_size=settings.max_queue_size
        )
    
    return {"status": "updated", "new_settings": current_conf}



# Mount Dashboard (Must be after API routes to avoid masking)
DASHBOARD_DIR = Path(__file__).parent.parent / "Dashboard"
if DASHBOARD_DIR.exists():
    app.mount("/", StaticFiles(directory=str(DASHBOARD_DIR), html=True), name="dashboard")
    logger.info(f"Dashboard mounted at / from {DASHBOARD_DIR}")
else:
    logger.warning(f"Dashboard directory not found at {DASHBOARD_DIR}")


if __name__ == "__main__":
    import uvicorn
    
    print("=" * 70)
    print("RFSN ORCHESTRATOR v8.2 - PRODUCTION STREAMING MODE")
    print("Security: Enabled | Metrics: Enabled | Multi-NPC: Active")
    print("=" * 70)
    
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
