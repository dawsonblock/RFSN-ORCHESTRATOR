# RFSN Orchestrator - Production Instructions

## Overview

The RFSN (Roleplay Fantasy Social Network) Orchestrator is a production-ready AI system for managing NPC dialogue, learning, and state management in roleplay scenarios. It integrates multiple production modules for governance, observability, and deterministic replay.

**Version:** v9.0

## Table of Contents

1. [System Requirements](#system-requirements)
2. [Installation](#installation)
3. [Configuration](#configuration)
4. [Running the System](#running-the-system)
5. [API Endpoints](#api-endpoints)
6. [Production Modules](#production-modules)
7. [Learning Layer](#learning-layer)
8. [Memory Management](#memory-management)
9. [Troubleshooting](#troubleshooting)
10. [Development](#development)

---

## System Requirements

- **Python:** 3.9+
- **Operating System:** Linux, macOS, or Windows with WSL2
- **Memory:** 8GB RAM minimum (16GB recommended)
- **Storage:** 5GB free space
- **GPU:** Optional (for TTS acceleration)

---

## Installation

### 1. Clone Repository

```bash
git clone https://github.com/your-org/RFSN-ORCHESTRATOR.git
cd RFSN-ORCHESTRATOR
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Setup Configuration

Copy the example configuration:

```bash
cp config.example.json config.json
```

Edit `config.json` with your settings:

```json
{
  "llm_provider": "openai",
  "llm_model": "gpt-4",
  "temperature": 0.7,
  "max_tokens": 80,
  "memory_enabled": true,
  "learning_enabled": true,
  "intent_gate_enabled": true
}
```

### 4. Setup API Keys

Create `api_keys.json`:

```bash
# The system will auto-generate an admin key on first run
# Or generate manually:
python -c "from security import api_key_manager; print(api_key_manager.generate_key('admin', ['admin_role']))"
```

---

## Configuration

### Core Settings

| Setting | Description | Default |
|---------|-------------|---------|
| `llm_provider` | LLM provider (openai, anthropic, local) | openai |
| `llm_model` | Model name | gpt-4 |
| `temperature` | Response randomness (0.0-1.0) | 0.7 |
| `max_tokens` | Max tokens per response | 80 |
| `memory_enabled` | Enable conversation memory | true |
| `learning_enabled` | Enable learning layer | true |
| `intent_gate_enabled` | Enable intent validation | true |

### Hot Configuration

The system supports hot-reloading configuration without restart:

```bash
# Edit config.json while system is running
# Changes take effect on next request
```

---

## Running the System

### Development Mode

```bash
cd Python
python launch_optimized.py
```

### Production Mode

```bash
cd Python
python orchestrator.py
```

### Using Docker

```bash
docker build -t rfsn-orchestrator .
docker run -p 8000:8000 -v $(pwd)/data:/app/data rfsn-orchestrator
```

### Verify Startup

Look for these log messages:

```
RFSN ORCHESTRATOR v8.2 - STARTING UP
======================================================================
Learning layer initialized (Policy Adapter, Reward Model, Trainer, LearningContract, MemoryGovernance, IntentGate, StreamingPipeline, Observability, EventRecorder, StateMachine)
Runtime state initialized atomically
Startup complete!
```

---

## API Endpoints

### Health Check

```bash
curl http://localhost:8000/health
```

Response:
```json
{
  "status": "healthy",
  "components": {
    "streaming_engine": true,
    "piper_engine": true,
    "xva_engine": false
  }
}
```

### Chat Endpoint

```bash
curl -X POST http://localhost:8000/chat \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "npc_name": "Serana",
    "user_input": "Hello, how are you?"
  }'
```

Response (SSE stream):
```
data: {"sentence": "Hello, traveler.", "is_final": false, "latency_ms": 150}

data: {"sentence": "I am well, thank you.", "is_final": true, "latency_ms": 300}
```

### Metrics Endpoint

```bash
curl http://localhost:8000/metrics
```

Returns Prometheus metrics for monitoring.

---

## Production Modules

### 1. Learning Contract

Enforces learning boundaries with write gate and rollback.

**Features:**
- Write gate for learner module only
- Max step size constraints
- Cooldown periods between updates
- Required evidence validation
- Automatic snapshot creation
- Rollback capability

**Configuration:**

```python
# In orchestrator.py startup_event
constraints = LearningConstraints(
    max_step_size=0.1,
    cooldown_seconds=5.0,
    required_evidence_types=["user_correction", "conversation_continued"]
)
```

**Usage:**

```python
learning_update = LearningUpdate(
    field_name="policy_weights",
    old_value=current_weights,
    new_value=new_weights,
    evidence_types=[EvidenceType.USER_CORRECTION],
    confidence=0.8,
    source="learner"
)

try:
    learning_contract.apply_update(learning_update)
except WriteGateError as e:
    logger.warning(f"Update rejected: {e}")
```

### 2. Memory Governance

Manages memory with provenance, confidence, TTL, and quarantine.

**Features:**
- Provenance tracking (source, timestamp)
- Confidence-based admission
- TTL expiration
- Contradiction detection
- Quarantine bucket for low-quality memories

**Storage Location:**
```
data/memory/governed/
```

**Usage:**

```python
governed_memory = GovernedMemory(
    memory_id="",
    memory_type=MemoryType.CONVERSATION_TURN,
    source=MemorySource.NPC_RESPONSE,
    content="Hello, traveler!",
    confidence=1.0,
    timestamp=datetime.utcnow(),
    metadata={"npc_name": "Serana"}
)

success, reason, memory_id = memory_governance.add_memory(governed_memory)
```

### 3. Intent Gate

Validates LLM output for safety and confidence.

**Features:**
- Safety flag detection (harmful, aggression, self-harm, illegal)
- Confidence threshold filtering
- Intent classification (ask, refuse, threaten, joke, etc.)
- Sentiment analysis

**Safety Flags:**
- `HARMFUL_CONTENT`
- `PERSONAL_INFO_REQUEST`
- `MANIPULATION`
- `AGGRESSION`
- `SELF_HARM`
- `ILLEGAL_ACTION`

**Usage:**

```python
proposal = intent_gate.extractor.extract(llm_output)

# Check for harmful content
harmful_flags = {
    SafetyFlag.HARMFUL_CONTENT,
    SafetyFlag.AGGRESSION,
    SafetyFlag.SELF_HARM,
    SafetyFlag.ILLEGAL_ACTION
}

if any(flag in proposal.safety_flags for flag in harmful_flags):
    # Block harmful content
    return ""
```

### 4. Streaming Pipeline

Provides hard guarantees for message delivery.

**Features:**
- Bounded queue with configurable size
- Drop policies (DROP_NEWEST, DROP_OLDEST, REJECT)
- Timeout handling
- Circuit breaker
- Message lifecycle tracking

**Configuration:**

```python
streaming_pipeline = StreamingPipeline(
    max_queue_size=50,
    drop_policy=DropPolicy.DROP_NEWEST,
    timeout_seconds=30
)
```

### 5. Observability

Structured logging and metrics collection.

**Features:**
- Structured JSON logging
- Metrics collection (request duration, token counts, errors)
- Trace correlation
- Log level filtering

**Usage:**

```python
# Structured logging
structured_logger.info(
    "npc_response",
    npc_name="Serana",
    response_length=150,
    confidence=0.95
)

# Metrics
metrics_collector.record("request_duration", 0.5)
metrics_collector.record("token_count", 42)
```

### 6. Event Recorder

Records events for deterministic replay and debugging.

**Features:**
- Event recording (USER_INPUT, LLM_GENERATION, LEARNING_UPDATE)
- Deterministic replay
- Session management
- Recording integrity verification

**Storage Location:**
```
data/recordings/
```

**Usage:**

```python
# Record events
event_recorder.record(
    EventType.USER_INPUT,
    {"text": "Hello", "npc_name": "Serana"}
)

event_recorder.record(
    EventType.LLM_GENERATION,
    {"prompt": "...", "response": "..."}
)

# Save recording
event_recorder.save()
```

### 7. State Machine

Enforces state invariants and transition auditing.

**Features:**
- State transition validation
- Invariant checking
- Drift detection
- Audit log
- RFSN-specific invariants (affinity, mood, relationship bounds)

**Usage:**

```python
state_machine = RFSNStateMachine()

# Transition to new state
state_machine.transition("affinity", 0.5, 0.6)

# Check invariants
is_valid, violations = state_machine.check_invariants()
if not is_valid:
    logger.warning(f"State invariant violations: {violations}")
```

---

## Learning Layer

### Components

1. **Policy Adapter** - Epsilon-greedy contextual bandit for action selection
2. **Reward Model** - Computes reward signals from user behavior
3. **Trainer** - Online learning with gradient updates
4. **Learning Contract** - Enforces learning boundaries

### Reward Signals

| Signal | Description | Weight |
|--------|-------------|--------|
| `contradiction_detected` | User corrects NPC | -1.0 |
| `user_correction` | User provides correction | -0.5 |
| `tts_overrun` | Speech queue overflow | -0.3 |
| `conversation_continued` | User continues conversation | +0.5 |
| `follow_up_question` | User asks follow-up | +0.3 |

### Action Modes

- `AGGRESSIVE` - Direct, confrontational responses
- `FRIENDLY` - Warm, welcoming responses
- `NEUTRAL` - Balanced, factual responses
- `MYSTERIOUS` - Cryptic, intriguing responses

### Training

Weights are saved periodically:

```python
# Auto-saves every 10 updates
# Manual save:
policy_adapter.save_weights()
```

---

## Memory Management

### Conversation Memory

Stored in `memory/` directory:

```
memory/
├── conversations/
│   ├── Serana.json
│   ├── Aela.json
│   └── ...
└── backups/
```

### Governed Memory

Stored in `data/memory/governed/`:

```
data/memory/governed/
├── memories.json
├── quarantine.json
└── index.json
```

### Memory Retrieval

```python
# Get recent turns
context = memory.get_context(npc_name, window_size=5)

# Search by keyword
matches = memory.search(npc_name, "dragon")
```

---

## Troubleshooting

### Common Issues

#### 1. Import Errors

**Problem:** `ModuleNotFoundError: No module named 'learning'`

**Solution:**
```bash
cd Python
export PYTHONPATH="${PYTHONPATH}:$(pwd)"
python orchestrator.py
```

#### 2. LLM API Failures

**Problem:** `OpenAI API error: Invalid API key`

**Solution:**
- Check `api_keys.json` exists
- Verify API key is valid
- Check environment variables if using env vars

#### 3. Memory Persistence Issues

**Problem:** Conversations not being saved

**Solution:**
- Check `memory/` directory permissions
- Verify `memory_enabled: true` in config.json
- Check disk space

#### 4. Learning Not Updating

**Problem:** Policy weights not changing

**Solution:**
- Verify `learning_enabled: true` in config.json
- Check LearningContract logs for rejections
- Verify reward signals are being detected

#### 5. Intent Gate Blocking All Responses

**Problem:** All responses being blocked as unsafe

**Solution:**
- Adjust `require_min_confidence` in IntentGate initialization
- Check safety flag patterns in `intent_extraction.py`
- Review logs for specific flags being triggered

### Debug Mode

Enable debug logging:

```python
# In config.json or environment
LOG_LEVEL=DEBUG python orchestrator.py
```

### Health Check

```bash
curl http://localhost:8000/health
```

### View Logs

```bash
# System logs
tail -f logs/orchestrator.log

# Learning layer logs
tail -f logs/learning.log

# Memory governance logs
tail -f logs/memory.log
```

---

## Development

### Running Tests

```bash
# All tests
pytest Python/tests/ -v

# Production tests only
pytest Python/tests/test_production.py -v

# Specific test class
pytest Python/tests/test_production.py::TestMemoryGovernance -v
```

### Code Quality

```bash
# Linting
flake8 Python/

# Type checking
mypy Python/

# Format
black Python/
```

### Adding New Modules

1. Create module file in `Python/`
2. Add to `RuntimeState` in `runtime_state.py`
3. Initialize in `orchestrator.py` startup_event
4. Add to atomic swap in `runtime.swap()`
5. Write tests in `tests/test_production.py`

### Hot Reload

The system supports hot reloading of configuration:

```bash
# Edit config.json
# Changes apply immediately to next request
```

For code changes, restart the server:

```bash
# Kill and restart
pkill -f orchestrator.py
python orchestrator.py
```

---

## Production Deployment

### Using Gunicorn

```bash
gunicorn -w 4 -k uvicorn.workers.UvicornWorker \
  --bind 0.0.0.0:8000 \
  --access-logfile logs/access.log \
  --error-logfile logs/error.log \
  orchestrator:app
```

### Using Docker Compose

```yaml
version: '3.8'
services:
  orchestrator:
    build: .
    ports:
      - "8000:8000"
    volumes:
      - ./data:/app/data
      - ./memory:/app/memory
    environment:
      - LOG_LEVEL=INFO
      - LEARNING_ENABLED=true
```

### Monitoring

- **Prometheus:** `http://localhost:8000/metrics`
- **Health:** `http://localhost:8000/health`
- **Logs:** `logs/orchestrator.log`

---

## Support

For issues, questions, or contributions:

- **GitHub Issues:** https://github.com/your-org/RFSN-ORCHESTRATOR/issues
- **Documentation:** https://github.com/your-org/RFSN-ORCHESTRATOR/wiki
- **Discord:** https://discord.gg/your-server

---

## License

MIT License - See LICENSE file for details.

---

## Changelog

### v9.0 (Current)
- Integrated LearningContract for learning boundaries
- Integrated MemoryGovernance for provenance tracking
- Integrated IntentGate for LLM output validation
- Integrated StreamingPipeline for delivery guarantees
- Integrated Observability for structured logging
- Integrated EventRecorder for deterministic replay
- Integrated StateMachine for state invariants

### v8.2
- Runtime state atomic swaps
- Learning layer integration
- Production test suite

### v8.0
- Initial production release
- Streaming engine
- TTS integration
- Multi-NPC support
