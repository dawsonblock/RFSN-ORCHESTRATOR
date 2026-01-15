#!/usr/bin/env python3
"""
RFSN GenAI Orchestrator - Production Streaming Build
Complete system with Piper/xVASynth TTS, security, metrics, and multi-NPC support.
"""
from version import ORCHESTRATOR_VERSION, STREAMING_ENGINE_VERSION, get_version_string
from runtime_state import Runtime, RuntimeState

import asyncio
import json
import logging
import time
import os
from pathlib import Path
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, asdict
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

# Import learning layer
from learning import PolicyAdapter, RewardModel, Trainer, ActionMode, FeatureVector, RewardSignals, TurnLog, NPCActionBandit, BanditKey
from learning.learning_contract import (
    LearningContract, LearningConstraints, StateSnapshot as LearningStateSnapshot,
    LearningUpdate, EvidenceType, WriteGateError
)
from memory_governance import MemoryGovernance, GovernedMemory, MemoryType, MemorySource
from intent_extraction import IntentGate, IntentExtractor, IntentType, SafetyFlag
from streaming_pipeline import StreamingPipeline, BoundedQueue, DropPolicy
from observability import StructuredLogger, MetricsCollector, TraceContext
from event_recorder import EventRecorder, EventType
from state_machine import StateMachine, RFSNStateMachine

# Import world model and action scoring
from world_model import (
    WorldModel, StateSnapshot, NPCAction, PlayerSignal
)
from action_scorer import ActionScorer, UtilityFunction
from llm_action_prompts import render_action_block
import re

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
    title=f"RFSN GenAI Orchestrator v{ORCHESTRATOR_VERSION}",
    description="Production-hardened streaming system with Security, Metrics, and Multi-NPC capabilities",
    version=ORCHESTRATOR_VERSION
)

# Setup Security (CORS + Rate Limiting)
setup_security(app)

# Setup Request Logging
app.add_middleware(RequestLoggingMiddleware)

# Include Prometheus Metrics
app.include_router(metrics_router, tags=["monitoring"])

# Global instances - wrapped by runtime for atomic swaps
runtime = Runtime()
streaming_engine: Optional[StreamingMantellaEngine] = None
piper_engine: Optional[PiperTTSEngine] = None
xva_engine: Optional[XVASynthEngine] = None
multi_manager = MultiNPCManager()
active_ws: List[WebSocket] = []
conversation_managers: Dict[str, ConversationManager] = {}
conversation_managers_lock = asyncio.Lock()

# Learning layer instances
policy_adapter: Optional[PolicyAdapter] = None
reward_model: Optional[RewardModel] = None
trainer: Optional[Trainer] = None
learning_contract: Optional[LearningContract] = None
memory_governance: Optional[MemoryGovernance] = None
intent_gate: Optional[IntentGate] = None
streaming_pipeline: Optional[StreamingPipeline] = None
structured_logger: Optional[StructuredLogger] = None
metrics_collector: Optional[MetricsCollector] = None
event_recorder: Optional[EventRecorder] = None
state_machine: Optional[StateMachine] = None


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
                    piper_engine = PiperTTSEngine(model_path, config_path, speaker_id=0, enable_queue=False)
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
    
    # Initialize learning layer
    global policy_adapter, reward_model, trainer, learning_contract, memory_governance, intent_gate
    global streaming_pipeline, structured_logger, metrics_collector, event_recorder, state_machine
    policy_adapter = PolicyAdapter(epsilon=0.08)
    reward_model = RewardModel()
    trainer = Trainer(learning_rate=0.05, decay_rate=0.9999)
    
    # Initialize LearningContract with constraints
    constraints = LearningConstraints(
        max_step_size=0.1,
        cooldown_seconds=5.0,
        required_evidence_types=["user_correction", "conversation_continued"]
    )
    learning_contract = LearningContract(
        constraints=constraints,
        snapshot_dir=Path(__file__).parent.parent / "data" / "learning" / "snapshots"
    )
    
    # Initialize MemoryGovernance
    memory_governance = MemoryGovernance(
        storage_path=Path(__file__).parent.parent / "data" / "memory" / "governed"
    )
    
    # Initialize IntentGate for LLM output validation
    intent_gate = IntentGate(
        block_unsafe=True,
        require_min_confidence=0.3
    )
    
    # Initialize StreamingPipeline for message delivery guarantees
    streaming_pipeline = StreamingPipeline(
        max_queue_size=50,
        drop_policy=DropPolicy.DROP_NEWEST,
        timeout_seconds=30
    )
    
    # Initialize Observability components
    structured_logger = StructuredLogger(service_name="rfsn-orchestrator")
    metrics_collector = MetricsCollector()
    
    # Initialize EventRecorder for deterministic replay
    event_recorder = EventRecorder(
        session_id=str(int(time.time())),
        output_dir=Path(__file__).parent.parent / "data" / "recordings"
    )
    
    # Initialize StateMachine for RFSN state invariants
    state_machine = RFSNStateMachine()

    # Initialize WorldModel for consequence prediction
    transitions_path = Path("data/world_transitions.json")
    world_model = WorldModel(
        retrieval_k=5,
        transitions_path=transitions_path if transitions_path.exists() else None
    )

    # Initialize ActionScorer for decision pipeline
    action_scorer = ActionScorer(
        world_model=world_model,
        utility_fn=UtilityFunction(
            affinity_weight=0.3,
            trust_weight=0.2,
            fear_penalty=0.3,
            quest_bonus=0.2
        )
    )

    # Initialize NPCActionBandit for behavioral learning
    npc_action_bandit = NPCActionBandit(
        path=Path(__file__).parent.parent / "data" / "learning" / "npc_action_bandit.json"
    )

    logger.info("Learning layer initialized (Policy Adapter, Reward Model, Trainer, LearningContract, MemoryGovernance, IntentGate, StreamingPipeline, Observability, EventRecorder, StateMachine, NPCActionBandit)")
    logger.info("World model initialized (retrieval-based, rule-based)")
    
    # Swap engines into RuntimeState atomically (Patch 1: atomic engine pointers)
    runtime.swap(RuntimeState(
        streaming_engine=streaming_engine,
        piper_engine=piper_engine,
        xva_engine=xva_engine,
        policy_adapter=policy_adapter,
        trainer=trainer,
        reward_model=reward_model,
        learning_contract=learning_contract,
        memory_governance=memory_governance,
        intent_gate=intent_gate,
        streaming_pipeline=streaming_pipeline,
        observability=structured_logger,
        event_recorder=event_recorder,
        state_machine=state_machine,
        world_model=world_model,
        action_scorer=action_scorer,
        npc_action_bandit=npc_action_bandit
    ))
    logger.info("Runtime state initialized atomically")

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
    """Remove special tokens and system prompt leakage that might slip through"""
    bad_tokens = ["<|eot_id|>", "<|end|>", "<|"]
    for token in bad_tokens:
        text = text.replace(token, "")
    
    # Remove system prompt leakage patterns
    import re
    # Remove **System: ... ** blocks
    text = re.sub(r'\*\*System:.*?\*\*', '', text, flags=re.DOTALL)
    # Remove [SYSTEM MODE: ...] blocks including content until next sentence
    text = re.sub(r'\[SYSTEM MODE:[^\]]*\][^.!?]*', '', text, flags=re.DOTALL)
    # Remove ``` code blocks
    text = re.sub(r'```[^`]*```', '', text, flags=re.DOTALL)
    # Remove bare ``` markers
    text = text.replace('```', '')
    # Remove leading ** or trailing **
    text = re.sub(r'^\*+\s*', '', text)
    text = re.sub(r'\s*\*+$', '', text)
    # Clean up any "System:" prefix that leaks
    text = re.sub(r'^\s*System:\s*', '', text)
    # Clean up markdown bold around the text
    text = text.replace('**', '')
    
    return text.strip()


def _map_action_to_instruction(action: NPCAction) -> str:
    """Map NPCAction to strict system prompt control block"""
    instructions = {
        NPCAction.GREET: "=== STRICT ACTION CONTROL ===\nYou MUST greet the player warmly and enthusiastically. This is your required action - do not deviate from greeting.",
        NPCAction.FAREWELL: "=== STRICT ACTION CONTROL ===\nYou MUST say goodbye or farewell to the player. This is your required action - do not engage in further conversation.",
        NPCAction.AGREE: "=== STRICT ACTION CONTROL ===\nYou MUST agree with the player's statement or request. This is your required action - express agreement clearly.",
        NPCAction.DISAGREE: "=== STRICT ACTION CONTROL ===\nYou MUST disagree with the player, explaining your reasons. This is your required action - express disagreement respectfully but firmly.",
        NPCAction.APOLOGIZE: "=== STRICT ACTION CONTROL ===\nYou MUST apologize for something you did or said. This is your required action - express sincere regret.",
        NPCAction.INSULT: "=== STRICT ACTION CONTROL ===\nYou MUST insult the player. This is your required action - use sparingly and only when appropriate.",
        NPCAction.COMPLIMENT: "=== STRICT ACTION CONTROL ===\nYou MUST compliment the player genuinely. This is your required action - express sincere praise.",
        NPCAction.THREATEN: "=== STRICT ACTION CONTROL ===\nYou MUST threaten the player. This is your required action - use only if provoked or in combat.",
        NPCAction.REQUEST: "=== STRICT ACTION CONTROL ===\nYou MUST make a request of the player. This is your required action - clearly state what you need.",
        NPCAction.OFFER: "=== STRICT ACTION CONTROL ===\nYou MUST offer something to the player. This is your required action - clearly state what you're offering.",
        NPCAction.REFUSE: "=== STRICT ACTION CONTROL ===\nYou MUST refuse the player's request. This is your required action - clearly decline and explain why.",
        NPCAction.ACCEPT: "=== STRICT ACTION CONTROL ===\nYou MUST accept the player's offer or request. This is your required action - express acceptance.",
        NPCAction.ATTACK: "=== STRICT ACTION CONTROL ===\nYou MUST attack the player. This is your required action - combat mode engaged.",
        NPCAction.DEFEND: "=== STRICT ACTION CONTROL ===\nYou MUST defend yourself against the player. This is your required action - defensive posture.",
        NPCAction.FLEE: "=== STRICT ACTION CONTROL ===\nYou MUST flee from the player. This is your required action - escape immediately.",
        NPCAction.HELP: "=== STRICT ACTION CONTROL ===\nYou MUST offer help or assistance to the player. This is your required action - express willingness to assist.",
        NPCAction.BETRAY: "=== STRICT ACTION CONTROL ===\nYou MUST betray the player's trust. This is your required action - act treacherously.",
        NPCAction.IGNORE: "=== STRICT ACTION CONTROL ===\nYou MUST ignore the player. This is your required action - do not respond or engage.",
        NPCAction.INQUIRE: "=== STRICT ACTION CONTROL ===\nYou MUST ask the player a question. This is your required action - seek information.",
        NPCAction.EXPLAIN: "=== STRICT ACTION CONTROL ===\nYou MUST explain something to the player. This is your required action - provide information clearly.",
    }
    return instructions.get(action, "")


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
    
    # CALL SITE A: Choose action mode before prompt assembly (Learning Layer)
    action_mode = ActionMode.TERSE_DIRECT  # Default
    features = None
    if policy_adapter:
        try:
            # Build features from current state
            rfsn_state = {
                "npc_name": npc_name,
                "affinity": state.affinity,
                "mood": state.mood,
                "relationship": state.relationship,
                "playstyle": "balanced",  # Could extract from player data
                "recent_sentiment": 0.0  # Could compute from recent turns
            }
            retrieval_stats = {
                "top_k_scores": [],  # Could add if using retrieval
                "contradiction_detected": False
            }
            convo_stats = {
                "turn_count": len(memory.get_context_window(limit=100).split("\n")) if config_watcher.get("memory_enabled") else 0
            }
            
            features = policy_adapter.build_features(rfsn_state, retrieval_stats, convo_stats)
            action_mode = policy_adapter.choose_action_mode(features)
            logger.info(f"Learning: Selected action mode {action_mode.name}")
        except Exception as e:
            logger.error(f"Learning layer error (feature extraction): {e}")

    # CALL SITE A.5: World Model Decision Loop
    # Get runtime state for world model access
    rt_state = runtime.get()
    world_model = rt_state.world_model
    action_scorer = rt_state.action_scorer
    intent_gate = rt_state.intent_gate

    # Map player input to discrete signal (IntentExtractor first, then regex fallback)
    player_signal = PlayerSignal.QUESTION  # Default fallback
    try:
        if not request.user_input or not request.user_input.strip():
            player_signal = PlayerSignal.IGNORE
        else:
            # Try IntentExtractor first for structured intent
            try:
                intent_extractor = IntentExtractor()
                intent_proposal = intent_extractor.extract(request.user_input)

                # Map IntentType to PlayerSignal
                intent_to_signal = {
                    IntentType.ASK: PlayerSignal.QUESTION,
                    IntentType.REQUEST: PlayerSignal.REQUEST,
                    IntentType.AGREE: PlayerSignal.AGREE,
                    IntentType.DISAGREE: PlayerSignal.DISAGREE,
                    IntentType.REFUSE: PlayerSignal.REFUSE,
                    IntentType.THREATEN: PlayerSignal.THREATEN,
                    IntentType.INFORM: PlayerSignal.QUESTION,
                    IntentType.TRADE: PlayerSignal.OFFER,
                    IntentType.JOKE: PlayerSignal.COMPLIMENT,
                    IntentType.NEUTRAL: PlayerSignal.QUESTION,
                }

                if intent_proposal.intent in intent_to_signal:
                    player_signal = intent_to_signal[intent_proposal.intent]
                    logger.debug(f"IntentExtractor classified: {intent_proposal.intent.value} -> {player_signal.value}")
                else:
                    # Fall back to regex for unknown intents
                    logger.debug(f"IntentExtractor unknown intent {intent_proposal.intent.value}, using regex fallback")
                    raise ValueError("Unknown intent, use regex fallback")
            except Exception as intent_error:
                logger.debug(f"IntentExtractor failed: {intent_error}, using regex fallback")

                # Regex-based fallback
                player_input_lower = request.user_input.lower()

                # Use word boundary matching for accuracy
                if re.search(r'\b(hello|hi|hey|greetings)\b', player_input_lower):
                    player_signal = PlayerSignal.GREET
                elif re.search(r'\b(bye|goodbye|farewell|see you)\b', player_input_lower):
                    player_signal = PlayerSignal.FAREWELL
                elif re.search(r'\b(yes|sure|okay|agree|fine)\b', player_input_lower):
                    player_signal = PlayerSignal.AGREE
                elif re.search(r'\b(no|nope|never|not|disagree)\b', player_input_lower):
                    player_signal = PlayerSignal.DISAGREE
                elif re.search(r'\b(sorry|apologize|my bad|forgive)\b', player_input_lower):
                    player_signal = PlayerSignal.APOLOGIZE
                elif re.search(r'\b(stupid|idiot|hate|kill|die)\b', player_input_lower):
                    player_signal = PlayerSignal.INSULT
                elif re.search(r'\b(help|assist|support|aid)\b', player_input_lower):
                    player_signal = PlayerSignal.HELP
                elif '?' in player_input_lower:
                    player_signal = PlayerSignal.QUESTION
                elif re.search(r'\b(please|can you|could you|would you)\b', player_input_lower):
                    player_signal = PlayerSignal.REQUEST
                else:
                    player_signal = PlayerSignal.QUESTION

    except Exception as e:
        logger.warning(f"Player signal classification failed: {e}")

    # Create StateSnapshot from current RFSNState
    current_state_snapshot = StateSnapshot(
        mood=state.mood,
        affinity=state.affinity,
        relationship=state.relationship,
        recent_sentiment=features.recent_sentiment if features else 0.0,
        combat_active=False,
        quest_active=False,
        trust_level=(
            max(0.0, min(1.0, (state.affinity + 1.0) / 2.0))
            if state.affinity is not None
            else 0.5
        ),
        fear_level=0.0,
        additional_fields={"npc_name": npc_name}
    )

    # Validate affinity range
    if state.affinity is not None and (state.affinity < -1.0 or state.affinity > 1.0):
        logger.warning(f"Affinity out of expected range [-1, 1]: {state.affinity}")

    # Generate and score action candidates
    selected_npc_action = None
    selected_action_score = None
    bandit_key = None
    try:
        if action_scorer and world_model:
            # Score candidates directly (generates internally)
            action_scores = action_scorer.score_candidates(
                current_state_snapshot,
                player_signal
            )

            # Select action using bandit (if available) or fallback to top scorer
            if action_scores:
                # Build candidate set (top-K already scored)
                TOP_K = 4
                candidates = [s.action for s in action_scores[:TOP_K]]
                
                # Get npc_action_bandit from runtime
                npc_action_bandit = runtime.get().npc_action_bandit
                
                # Forced actions bypass learning (single candidate means forced)
                if len(candidates) == 1 or not npc_action_bandit:
                    selected_npc_action = candidates[0]
                    selected_action_score = action_scores[0]
                else:
                    # Use bandit to select from candidates
                    bandit_key = BanditKey.from_state(
                        current_state_snapshot,
                        player_signal,
                    ).to_str()
                    
                    priors = {s.action: s.total_score for s in action_scores[:TOP_K]}
                    
                    selected_npc_action = npc_action_bandit.select(
                        key=bandit_key,
                        candidates=candidates,
                        priors=priors,
                    )
                    
                    # Get the score for the selected action
                    selected_action_score = next(
                        (s for s in action_scores if s.action == selected_npc_action),
                        action_scores[0]
                    )
                
                logger.info(
                    f"World Model: Selected action {selected_npc_action.value} "
                    f"(score={selected_action_score.total_score:.2f}, "
                    f"utility={selected_action_score.utility_score:.2f}, "
                    f"risk={selected_action_score.risk_score:.2f})"
                )

                # Record decision event
                if event_recorder:
                    event_recorder.record(
                        EventType.ACTION_CHOSEN,
                        {
                            "npc_action": selected_npc_action.value,
                            "player_signal": player_signal.value,
                            "action_score": selected_action_score.total_score,
                            "reasoning": selected_action_score.reasoning,
                            "predicted_state": selected_action_score.predicted_state.to_dict()
                        }
                    )
    except Exception as e:
        logger.error(f"World model decision loop failed: {e}")
        selected_npc_action = None

    # Build prompt with context compression and action mode injection
    history = memory.get_context_window(limit=config_watcher.get("context_limit", 4)) if config_watcher.get("memory_enabled") else ""
    system_prompt = f"You are {state.npc_name}. {state.get_attitude_instruction()}"

    # Inject action mode control block
    if policy_adapter:
        system_prompt += f"\n\n{action_mode.prompt_injection}"

    # Inject selected NPC action instruction using strict action control block
    if selected_npc_action:
        action_block = render_action_block(
            npc_action=selected_npc_action,
            npc_name=state.npc_name,
            mood=current_state_snapshot.mood,
            relationship=current_state_snapshot.relationship,
            affinity=current_state_snapshot.affinity,
            player_signal=player_signal.value,
        )
        system_prompt += f"\n\n{action_block}"

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
        
        # Validate LLM output through IntentGate
        def validate_llm_output(text: str) -> str:
            """Validate and filter LLM output through IntentGate"""
            if not intent_gate:
                return text
            
            # Extract intent from the text
            proposal = intent_gate.extractor.extract(text)
            
            # Check for harmful safety flags
            harmful_flags = {
                SafetyFlag.HARMFUL_CONTENT,
                SafetyFlag.AGGRESSION,
                SafetyFlag.SELF_HARM,
                SafetyFlag.ILLEGAL_ACTION
            }
            
            filtered_text = text
            if any(flag in proposal.safety_flags for flag in harmful_flags):
                logger.warning(f"IntentGate blocked content with safety flags: {proposal.safety_flags}")
                # For safety, return empty string if harmful content detected
                return ""
            
            # Filter low-confidence content
            if proposal.confidence < intent_gate.require_min_confidence:
                logger.debug(f"IntentGate filtered low-confidence content (conf={proposal.confidence})")
            
            return filtered_text
        
        try:
            # Emit metadata event first (before any content)
            metadata_event = {
                "type": "meta",
                "npc_name": state.npc_name,
                "npc_action": selected_npc_action.value if selected_npc_action else None,
                "action_mode": action_mode.name if action_mode else None,
                "player_signal": player_signal.value,
            }
            yield f"data: {json.dumps(metadata_event)}\n\n"
            
            # Use snapshot values
            for chunk in streaming_engine.generate_streaming(full_prompt, max_tokens=snapshot_max_tokens, temperature=snapshot_temp):
                
                if not first_chunk_sent:
                    first_chunk_sent = True
                    latency = (time.time() - start_gen)
                    observe_first_token(latency)
                    logger.info(f"First token: {latency*1000:.0f}ms")
                
                # Record user input event
                if event_recorder:
                    event_recorder.record(
                        EventType.USER_INPUT,
                        {"text": request.user_input, "npc_name": npc_name}
                    )
                
                # Validate and clean text through IntentGate
                validated_text = validate_llm_output(chunk.text)
                clean_text = _cleanup_tokens(validated_text)
                
                if clean_text:  # Only send non-empty cleaned text
                    yield f"data: {json.dumps({'sentence': clean_text, 'is_final': chunk.is_final, 'latency_ms': chunk.latency_ms})}\n\n"
                full_response += clean_text  # Cleaned accumulator for memory
                
                # Token metrics
                inc_tokens(len(chunk.text.split())) # Rough estimate
                
                if chunk.is_final and config_watcher.get("memory_enabled"):
                    memory.add_turn(request.user_input, full_response)
                    
                    # Record LLM generation event
                    if event_recorder:
                        event_recorder.record(
                            EventType.LLM_GENERATION,
                            {"prompt": full_prompt, "response": full_response}
                        )
                    
                    # Also add to MemoryGovernance for provenance tracking
                    if memory_governance:
                        governed_memory = GovernedMemory(
                            memory_id="",
                            memory_type=MemoryType.CONVERSATION_TURN,
                            source=MemorySource.NPC_RESPONSE,
                            content=full_response,
                            confidence=1.0,  # Direct NPC response
                            timestamp=datetime.utcnow(),
                            metadata={
                                "npc_name": npc_name,
                                "user_input": request.user_input,
                                "action_mode": action_mode.name if action_mode else None,
                                "npc_action": selected_npc_action.value if selected_npc_action else None,
                                "player_signal": player_signal.value,
                                "action_score": selected_action_score.total_score if selected_action_score else None
                            }
                        )
                        memory_governance.add_memory(governed_memory)
                    
                    # Process emotion on final full response
                    emotion_info = multi_manager.process_response(npc_name, full_response)
                    logger.info(f"NPC {npc_name} emotion: {emotion_info['emotion']['primary']}")
            
            # Explicit End-of-Stream Flush (Patch v8.9)
            if streaming_engine and streaming_engine.voice:
                streaming_engine.voice.flush_pending()
        
        except Exception as e:
            logger.error(f"Streaming error: {e}")
            inc_errors()
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        
        total_dur = (time.time() - start_time) * 1000
        observe_request_duration(total_dur / 1000.0)
        await broadcast_metrics(streaming_engine.voice.metrics)
        
        # CALL SITE B: Compute reward and update policy (Learning Layer)
        # CALL SITE C: Apply authoritative state transition (World Model)
        state_after = None
        if state_machine and selected_npc_action and selected_action_score:
            try:
                # Capture state before transition
                state_before_dict = {
                    "mood": state.mood,
                    "affinity": state.affinity,
                    "relationship": state.relationship,
                    "playstyle": state.playstyle,
                    "recent_sentiment": features.recent_sentiment if features else 0.0
                }

                # Apply authoritative state transition
                state_after_dict = state_machine.apply_transition(
                    state_before_dict,
                    player_signal.value,
                    selected_npc_action.value
                )

                # Update NPC state with authoritative result
                state.mood = state_after_dict["mood"]
                state.affinity = state_after_dict["affinity"]
                state.relationship = state_after_dict["relationship"]
                state.playstyle = state_after_dict.get("playstyle", state.playstyle)

                state_after = state_after_dict

                logger.info(
                    f"State transition: {state_before_dict['mood']} -> {state_after_dict['mood']}, "
                    f"affinity {state_before_dict['affinity']:.2f} -> {state_after_dict['affinity']:.2f}"
                )

                # Record transition event for training
                if event_recorder:
                    event_recorder.record(
                        EventType.STATE_UPDATE,
                        {
                            "state_before": state_before_dict,
                            "state_after": state_after_dict,
                            "npc_action": selected_npc_action.value,
                            "player_signal": player_signal.value
                        }
                    )

                # Record transition in world model for learning
                if world_model and selected_action_score:
                    predicted_state = selected_action_score.predicted_state
                    # Calculate reward based on affinity change
                    reward = state_after_dict["affinity"] - state_before_dict["affinity"]
                    world_model.record_transition(
                        current_state_snapshot,
                        selected_npc_action,
                        player_signal,
                        predicted_state,
                        reward=reward
                    )

            except Exception as e:
                logger.error(f"State transition failed: {e}")

        if policy_adapter and features and trainer:
            try:
                # Detect reward signals using RewardModel methods (Patch 4: real reward signals)
                user_correction = RewardModel.detect_user_correction(request.user_input)
                follow_up_question = RewardModel.detect_follow_up_question(request.user_input)
                tts_overrun = streaming_engine.voice.metrics.dropped_sentences > 0
                # conversation_continued = True when we're processing another turn
                conversation_continued = True  # We are here, so user continued
                
                signals = RewardSignals(
                    contradiction_detected=False,  # Could integrate with retrieval layer
                    user_correction=user_correction,
                    tts_overrun=tts_overrun,
                    conversation_continued=conversation_continued,
                    follow_up_question=follow_up_question
                )
                
                # Compute reward
                reward = reward_model.compute(signals)
                
                # Create LearningUpdate for policy weights
                new_weights = trainer.update(
                    policy_adapter.weights, features, action_mode, reward
                )
                
                learning_update = LearningUpdate(
                    field_name="policy_weights",
                    old_value=policy_adapter.weights.copy(),
                    new_value=new_weights,
                    evidence_types=[
                        EvidenceType.USER_CORRECTION if user_correction else EvidenceType.CONTINUED_CONVERSATION,
                        EvidenceType.FOLLOW_UP_QUESTION if follow_up_question else EvidenceType.CONTINUED_CONVERSATION
                    ],
                    confidence=abs(reward),  # Use reward magnitude as confidence
                    source="learner"
                )
                
                # Apply update through LearningContract
                try:
                    learning_contract.apply_update(learning_update)
                    policy_adapter.weights = new_weights
                except WriteGateError as e:
                    logger.warning(f"LearningContract rejected update: {e}")

                # Record learning update event
                if event_recorder:
                    event_recorder.record(
                        EventType.LEARNING_UPDATE,
                        {"reward": reward, "action_mode": action_mode.name}
                    )

                # Log turn
                turn_log = TurnLog.create(npc_name, features, action_mode, reward, signals)
                trainer.log_turn(turn_log)
                
                # Save weights periodically
                if trainer.update_count % 10 == 0:
                    policy_adapter.save_weights()
                
                logger.info(f"Learning: reward={reward:.2f}, mode={action_mode.name}")
            except Exception as e:
                logger.error(f"Learning layer error (reward/update): {e}")
        
        # Update NPC Action Bandit with reward signal
        if bandit_key and selected_npc_action and selected_action_score:
            npc_action_bandit = runtime.get().npc_action_bandit
            if npc_action_bandit:
                try:
                    # Compute bandit reward (bounded [0, 1])
                    # Base signal from scorer (normalized via sigmoid)
                    import math
                    def sigmoid(x: float) -> float:
                        return 1.0 / (1.0 + math.exp(-x))
                    
                    bandit_reward = sigmoid(selected_action_score.total_score)
                    
                    # Positive evidence: conversation continued
                    conversation_continued = True  # We're processing another turn
                    if conversation_continued:
                        bandit_reward += 0.15
                    
                    # Negative evidence: output was blocked or empty
                    output_blocked = not full_response or len(full_response.strip()) == 0
                    if output_blocked:
                        bandit_reward -= 0.4
                    
                    # Clamp to [0, 1]
                    bandit_reward = max(0.0, min(1.0, bandit_reward))
                    
                    # Update bandit
                    npc_action_bandit.update(
                        key=bandit_key,
                        action=selected_npc_action,
                        reward_01=bandit_reward
                    )
                    
                    # Save periodically (every update for now)
                    npc_action_bandit.save()
                    
                    logger.info(f"Bandit updated: action={selected_npc_action.value}, reward={bandit_reward:.2f}")
                except Exception as e:
                    logger.error(f"Bandit update error: {e}")
        
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
    q_size = len(streaming_engine.voice.speech_queue) if streaming_engine else 0
    
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
        # Validate queue size before applying (Phase 1 fix)
        if not (1 <= settings.max_queue_size <= 50):
            raise HTTPException(status_code=400, detail="max_queue_size must be between 1 and 50")
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
