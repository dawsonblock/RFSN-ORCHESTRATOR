# 🎮 RFSN Orchestrator

<div align="center">

**Production-Ready Streaming AI System for Real-Time NPC Dialogue**

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.104+-009688.svg)](https://fastapi.tiangolo.com/)
[![Tests](https://img.shields.io/badge/tests-113%20passing-success.svg)](Python/tests/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Code Style](https://img.shields.io/badge/code%20style-optimized-brightgreen.svg)](Python/)

*Hardened streaming engine with intelligent tokenization, backpressure management, and real-time TTS*

[Features](#-features) • [Quick Start](#-quick-start) • [Architecture](#-architecture) • [API](#-api-reference) • [Performance](#-performance)

</div>

---

## 🌟 Features

### Core Capabilities
- **🧠 Intelligent Tokenization** - Smart sentence detection with abbreviation handling (Dr., Mr., Jarl)
- **🎙️ Real-Time TTS** - Piper engine with streaming audio playback
- **⚡ Backpressure Management** - Dynamic queue resizing with coherent trimming
- **🔒 Thread-Safe** - Lock-based synchronization for concurrent operations
- **📊 Live Metrics** - WebSocket-based performance monitoring dashboard
- **💾 Persistent Memory** - Conversation history with automatic backups

### Production Hardening (v8.10)
- ✅ **113 Tests** - Comprehensive test coverage including edge cases
- ✅ **Zero Race Conditions** - Fixed queue draining and config snapshot issues
- ✅ **Optimized Performance** - Pre-compiled regex, module-level constants
- ✅ **Enhanced Reliability** - Worker error recovery, metrics cleanup, graceful shutdown
- ✅ **Input Validation** - Queue size bounds checking, malformed input handling

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
│                     RFSN Orchestrator                        │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐  │
│  │   FastAPI    │───▶│  Streaming   │───▶│  Piper TTS   │  │
│  │   Server     │    │   Engine     │    │   Engine     │  │
│  └──────────────┘    └──────────────┘    └──────────────┘  │
│         │                    │                    │          │
│         ▼                    ▼                    ▼          │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐  │
│  │   Memory     │    │  Tokenizer   │    │   Audio      │  │
│  │   Manager    │    │  (Smart)     │    │   Player     │  │
│  └──────────────┘    └──────────────┘    └──────────────┘  │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

### Key Components

| Component | Purpose | Location |
|-----------|---------|----------|
| **Orchestrator** | FastAPI server, request handling | `Python/orchestrator.py` |
| **Streaming Engine** | Token processing, sentence detection | `Python/streaming_engine.py` |
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
data: {"type": "sentence", "text": "Whiterun is a great city."}
data: {"type": "sentence", "text": "We welcome all travelers."}
data: {"type": "done"}
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
  "max_tokens": 80,
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

### Optimization Features

- **Pre-compiled Regex** - Eliminates hot-path compilation overhead
- **Module Constants** - Named constants for all magic numbers
- **Queue Snapshot** - Race-free draining with `qsize()` snapshot
- **Worker Resilience** - Explicit error recovery prevents worker death
- **Metrics Cleanup** - Dead WebSocket connection removal prevents memory leaks

---

## 🧪 Testing

### Run All Tests

```bash
cd Python
python -m pytest tests/ -v
```

### Test Coverage

- **Core Functionality**: 98 tests
- **Edge Cases**: 15 tests
- **Total**: 113 tests (100% passing)

### Test Categories

```bash
# Unit tests
pytest tests/test_streaming_fixes.py -v

# Integration tests
pytest tests/test_integration.py -v

# Performance tests
pytest tests/test_performance.py -v

# Edge cases
pytest tests/test_edge_cases.py -v
```

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
  "llm_model_path": "Models/llama-3.2-3b-instruct.Q4_K_M.gguf",
  "temperature": 0.7,
  "max_tokens": 80,
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
│   ├── orchestrator.py          # FastAPI server
│   ├── streaming_engine.py      # Core streaming logic
│   ├── memory_manager.py        # Conversation persistence
│   ├── piper_tts.py            # TTS engine
│   ├── security.py             # Authentication
│   ├── prometheus_metrics.py   # Metrics collection
│   ├── requirements.txt        # Dependencies
│   └── tests/                  # Test suite (113 tests)
├── Dashboard/
│   └── index.html              # Metrics dashboard
├── Models/
│   └── piper/                  # Voice models
├── config.json                 # Configuration
└── README.md                   # This file
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

### v8.10 (Latest) - Critical Bug Fixes
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
