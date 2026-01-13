# 🎮 RFSN Orchestrator

<div align="center">

**Production-Ready Streaming AI System for Real-Time NPC Dialogue**

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.104+-009688.svg)](https://fastapi.tiangolo.com/)
[![Tests](https://img.shields.io/badge/tests-142%20passing-success.svg)](Python/tests/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Code Style](https://img.shields.io/badge/code%20style-optimized-brightgreen.svg)](Python/)

*Production-ready streaming AI with semantic action selection, world model prediction, and real-time TTS*

[Features](#-features) • [Quick Start](#-quick-start) • [Architecture](#-architecture) • [API](#-api-reference) • [Performance](#-performance)

</div>

---

## 🌟 Features

### Core Capabilities
- **🧠 Intelligent Tokenization** - Smart sentence detection with abbreviation handling (Dr., Mr., Jarl)
- **🎯 Semantic Action Selection** - World model predicts outcomes and scores NPC actions (GREET, APOLOGIZE, THREATEN, etc.)
- **🎙️ Real-Time TTS** - Piper engine with streaming audio playback
- **⚡ Thread-Safe Queue** - Deque+Condition pattern eliminates race conditions
- **🔒 Atomic Runtime** - Safe hot-reloads without half-applied config
- **📊 Live Metrics** - WebSocket-based performance monitoring dashboard
- **💾 Persistent Memory** - Conversation history with automatic backups
- **🤖 Adaptive Learning** - Contextual bandit learns optimal dialogue styles per NPC
- **🛡️ Safety Rules** - Hard overrides prevent learned stupidity in combat/trust/quest contexts

### Production Hardening (v9.0)
- ✅ **142 Tests** - Comprehensive coverage including edge cases, learning layer, and world model integration
- ✅ **Zero Race Conditions** - Deque+Condition queue pattern (no task_done/join bugs)
- ✅ **Atomic State Swaps** - RuntimeState prevents half-applied config during reloads
- ✅ **Single TTS Queue** - Unified backpressure (no double-buffering)
- ✅ **Canonical Versioning** - Single source of truth for version strings
- ✅ **Safety Rules** - Hard overrides prevent learned stupidity in critical states

---

## 🚀 Quick Start

### Prerequisites
- Python 3.9+
- 4GB RAM minimum
- macOS, Linux, or Windows

### Installation

```bash
# Clone the repository
git clone https://github.com/dawsonblock/RFSN-ORCHESTRATOR.git
cd RFSN-ORCHESTRATOR

# Install dependencies
cd Python
pip install -r requirements.txt

# Launch the server
python launch_optimized.py
```

**Server URL**: `http://127.0.0.1:8000`  
**Dashboard**: `http://127.0.0.1:8000` (opens automatically)

### Docker (Optional)

```bash
docker build -t rfsn-orchestrator .
docker run -p 8000:8000 rfsn-orchestrator
```

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     RFSN Orchestrator v9.0                   │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐  │
│  │   FastAPI    │───▶│  Streaming   │───▶│  Piper TTS   │  │
│  │   Server     │    │   Engine     │    │  (sync-only) │  │
│  └──────────────┘    └──────────────┘    └──────────────┘  │
│         │                    │                    │          │
│         ▼                    ▼                    ▼          │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐  │
│  │   Learning   │    │ DequeSpeech  │    │   Audio      │  │
│  │    Layer     │    │    Queue     │    │   Player     │  │
│  └──────────────┘    └──────────────┘    └──────────────┘  │
│         │                    │                               │
│         ▼                    ▼                               │
│  ┌──────────────┐    ┌──────────────┐                       │
│  │  World Model │───▶│Action Scorer │                       │
│  │  (Prediction)│    │  (Scoring)   │                       │
│  └──────────────┘    └──────────────┘                       │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

### Key Components

| Component | Purpose | Location |
|-----------|---------|----------|
| **Orchestrator** | FastAPI server, request handling | `Python/orchestrator.py` |
| **Streaming Engine** | Token processing, sentence detection | `Python/streaming_engine.py` |
| **DequeSpeechQueue** | Thread-safe bounded queue with drop policy | `Python/streaming_voice_system.py` |
| **World Model** | Predicts state transitions from actions | `Python/world_model.py` |
| **Action Scorer** | Scores candidate actions using predictions | `Python/action_scorer.py` |
| **Learning Layer** | Contextual bandit for dialogue style selection | `Python/learning/` |
| **Runtime State** | Atomic state management for safe reloads | `Python/runtime_state.py` |
| **State Machine** | Authoritative state transitions with invariants | `Python/state_machine.py` |
| **Memory Manager** | Conversation persistence, backups | `Python/memory_manager.py` |
| **Piper TTS** | Text-to-speech synthesis | `Python/piper_tts.py` |
| **Dashboard** | Live metrics visualization | `Dashboard/index.html` |

---

## 📡 API Reference

### Streaming Dialogue

```http
POST /api/dialogue/stream
Content-Type: application/json

{
  "npc_name": "Jarl Balgruuf",
  "user_input": "Tell me about Whiterun."
}
```

**Response**: Server-Sent Events (SSE) stream

```
data: {"sentence": "Whiterun is a great city.", "is_final": false, "latency_ms": 150}
data: {"sentence": "We welcome all travelers.", "is_final": true, "latency_ms": 280}
```

### Memory Management

```http
# Get memory stats
GET /api/memory/{npc_name}/stats

# Safe reset with backup
POST /api/memory/{npc_name}/safe_reset

# List backups
GET /api/memory/{npc_name}/backups
```

### Performance Tuning

```http
POST /api/tune-performance
Content-Type: application/json

{
  "temperature": 0.7,
  "max_tokens": 150,
  "max_queue_size": 3
}
```

### Health & Metrics

```http
# Health check
GET /api/health

# WebSocket metrics stream
WS /ws/metrics
```

---

## ⚡ Performance

### Benchmarks

| Metric | Target | Actual |
|--------|--------|--------|
| First Token Latency | <1.5s | ~1.2s |
| Sentence Detection | <50ms | ~30ms |
| TTS Processing | <100ms | ~80ms |
| Queue Throughput | 10 items/s | 12 items/s |

### Key Optimizations

- **Deque+Condition Queue** - Eliminates task_done/join race conditions
- **Atomic Drop Policy** - Drop runs under same lock as worker get()
- **Pre-compiled Regex** - Eliminates hot-path compilation overhead
- **Sync-Only TTS** - Single queue path prevents double-buffering
- **Config Snapshots** - Per-request snapshots prevent mid-stream changes

---

## 🧪 Testing

### Run All Tests

```bash
cd Python
python -m pytest tests/ -v
```

### Test Coverage

- **Core Functionality**: 105 tests
- **Learning Layer**: 21 tests
- **World Model Integration**: 3 tests
- **Edge Cases**: 13 tests
- **Total**: 142 tests (100% passing)

### Test Categories

```bash
# Unit tests
pytest tests/test_streaming_fixes.py -v

# Learning layer tests
pytest tests/test_learning.py tests/test_learning_policy.py -v

# Performance tests
pytest tests/test_performance.py -v

# Edge cases
pytest tests/test_edge_cases.py -v

# Backpressure tests
pytest tests/test_backpressure.py -v
```

---

## 🎯 World Model & Action Scoring

The system includes a world model that predicts state transitions and scores NPC actions based on predicted outcomes:

### NPC Actions

| Action | Description | Use Case |
|--------|-------------|----------|
| `GREET` | Warmly welcome the player | First meeting, friendly encounters |
| `APOLOGIZE` | Express regret for mistakes | After conflicts, mistakes |
| `THREATEN` | Intimidate the player | Combat, hostile situations |
| `COMPLIMENT` | Praise the player | Building rapport |
| `HELP` | Offer assistance | Quests, requests for aid |
| `REQUEST` | Ask for something | Quest objectives |
| `AGREE` | Accept player proposals | Cooperation |
| `DISAGREE` | Reject player proposals | Conflict, boundaries |
| `IGNORE` | Dismiss the player | Low trust, busy |
| `INQUIRE` | Ask questions | Information gathering |
| `EXPLAIN` | Provide information | Lore, instructions |

### Player Signals

The system classifies player input into discrete signals:

- `GREET` - Friendly greetings
- `INSULT` - Hostile language
- `HELP` - Requests for assistance
- `THREATEN` - Combat initiation
- `APOLOGIZE` - Conciliatory language
- `QUESTION` - Information seeking
- `REQUEST` - Demands or asks

### Safety Rules

Hard overrides prevent learned stupidity in critical states:

- **Combat + Fear > 0.7** → Forces `FLEE` action
- **Trust < 0.1** → Forbids `ACCEPT`, `OFFER`, `HELP` actions
- **Quest Active** → Biases toward `HELP`, `ACCEPT`, `AGREE` actions

### How It Works

1. **Player Signal Classification** - Regex-based pattern matching with word boundaries
2. **State Snapshot Creation** - Captures current NPC state (mood, affinity, trust, fear)
3. **Candidate Proposal** - Generates 5-9 candidate actions with safety overrides
4. **World Model Prediction** - Predicts outcome state for each action
5. **Utility Scoring** - Scores predicted states using affinity, trust, fear weights
6. **Action Selection** - Selects highest-scoring action
7. **Prompt Injection** - Injects action instruction into LLM system prompt
8. **State Transition** - Applies authoritative state update via `apply_transition()`

---

## 🤖 Learning Layer

The system includes a lightweight contextual bandit that learns optimal dialogue styles per NPC:

### Action Modes

| Mode | Description |
|------|-------------|
| `TERSE_DIRECT` | Short, factual responses (3-4 sentences) |
| `WARM_FRIENDLY` | Empathetic, relational responses |
| `LORE_RICH` | Detailed world-building responses |
| `PLAYFUL_WITTY` | Humorous, light-hearted responses |
| `FORMAL_RESPECTFUL` | Distant, proper responses |
| `NEUTRAL_BALANCED` | Default balanced approach |

### How It Works

1. **Feature Extraction** - Extracts 10 features from NPC state, conversation history, and memory retrieval
2. **Policy Selection** - ε-greedy exploration over action modes with linear weights
3. **Reward Learning** - Updates policy based on conversation signals (continuation, correction, follow-up)

### Safety Guarantees

- Learning is scoped to style selection only (not model weights)
- Weights are bounded with decay and clipping
- Atomic weight persistence
- Per-NPC isolation

---

## 📊 Monitoring

### Dashboard Features

- **Real-time Metrics** - First token, sentence, and total generation latency
- **Queue Status** - Current size and dropped sentence count
- **Performance Tuning** - Live adjustment of temperature, tokens, queue size
- **Visual Feedback** - Glassmorphism UI with smooth animations

### Metrics Available

```javascript
{
  "first_token_ms": 1200,
  "first_sentence_ms": 1500,
  "total_generation_ms": 3000,
  "tts_queue_size": 2,
  "dropped_sentences": 0
}
```

---

## 🔧 Configuration

### `config.json`

```json
{
  "llm_model_path": "Models/Mantella-Skyrim-Llama-3-8B-Q4_K_M.gguf",
  "temperature": 0.7,
  "max_tokens": 150,
  "max_queue_size": 3,
  "piper_model": "en_US-lessac-medium",
  "log_level": "INFO"
}
```

### Environment Variables

```bash
export RFSN_PORT=8000
export RFSN_HOST=0.0.0.0
export RFSN_LOG_LEVEL=DEBUG
```

---

## 🛠️ Development

### Project Structure

```
RFSN-ORCHESTRATOR/
├── Python/
│   ├── orchestrator.py           # FastAPI server
│   ├── streaming_engine.py       # Core streaming logic
│   ├── streaming_voice_system.py # DequeSpeechQueue (thread-safe)
│   ├── runtime_state.py          # Atomic runtime management
│   ├── version.py                # Canonical version strings
│   ├── memory_manager.py         # Conversation persistence
│   ├── piper_tts.py              # TTS engine
│   ├── security.py               # Authentication
│   ├── learning/                 # Contextual bandit layer
│   │   ├── schemas.py            # ActionMode definitions
│   │   ├── policy_adapter.py     # Feature extraction + action selection
│   │   ├── reward_model.py       # Reward computation
│   │   └── trainer.py            # Online weight updates
│   ├── requirements.txt          # Dependencies
│   └── tests/                    # Test suite (139 tests)
├── Dashboard/
│   └── index.html                # Metrics dashboard
├── Models/
│   └── piper/                    # Voice models
├── config.json                   # Configuration
└── README.md                     # This file
```

### Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Run tests (`pytest tests/ -v`)
4. Commit changes (`git commit -m 'Add amazing feature'`)
5. Push to branch (`git push origin feature/amazing-feature`)
6. Open a Pull Request

---

## 📈 Changelog

### v9.0 (Latest) - Thread-Safe Queue Rewrite
- **Deque+Condition queue** replaces queue.Queue (eliminates race conditions)
- Removed all task_done/join semantics
- Drop policy runs atomically with consumer
- Added `RuntimeState` for atomic config swaps
- Added `version.py` for canonical versioning
- Removed dead code (StreamingVoiceSystemV2)
- Added `enable_queue` flag to Piper TTS

### v8.10 - Critical Bug Fixes
- Fixed `/ws/metrics` crash (missing `asdict` import)
- Corrected end-of-stream flush semantics
- Renamed `flush()` → `reset()`, added `flush_pending()`

### v8.9 - Operational Hardening
- Tokenizer continuation fix
- Explicit end-of-stream flush
- Stream hygiene improvements
- `/api/health` endpoint
- Structured trace logging

### v8.8 - Backpressure & Resize Hardening
- Coherent queue trimming (keep first/last)
- Worker wakeup sentinel
- Thread-safe resize operations

### v8.7 - Reliability Hardening
- Smart sentence boundary detection
- Quote-aware tokenization
- Newline boundary support

[View Full Changelog](CHANGELOG.md)

---

## 🤝 Acknowledgments

- **LLaMA** - Meta's language model
- **Piper TTS** - Rhasspy's neural TTS engine
- **FastAPI** - Modern Python web framework

---

## 📄 License

MIT License - see [LICENSE](LICENSE) file for details

---

## 🔗 Links

- **Repository**: [github.com/dawsonblock/RFSN-ORCHESTRATOR](https://github.com/dawsonblock/RFSN-ORCHESTRATOR)
- **Issues**: [Report a bug](https://github.com/dawsonblock/RFSN-ORCHESTRATOR/issues)
- **Discussions**: [Join the conversation](https://github.com/dawsonblock/RFSN-ORCHESTRATOR/discussions)

---

<div align="center">

**Made with ❤️ for immersive NPC interactions**

⭐ Star this repo if you find it useful!

</div>
