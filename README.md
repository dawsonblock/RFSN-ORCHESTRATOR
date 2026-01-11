# RFSN GenAI Orchestrator v8.1

**Production-ready streaming AI system for Skyrim NPC dialogue with Piper TTS.**

## 🚀 Quick Start

```bash
cd Python
pip install -r requirements.txt
python launch_optimized.py
```

Server runs at: `http://127.0.0.1:8000`

## ✅ Features

- **Smart Sentence Detection** - Avoids splitting on abbreviations ("Dr.", "Jarl Balgruuf")
- **Thread-Safe TTS** - Piper engine with subprocess-based audio playback
- **Token Filtering** - Removes `<|eot_id|>`, `<|end|>` from TTS
- **Backpressure** - Queue maxsize=3, drops old audio if overloaded
- **Error Handling** - Catches TTS failures and logs them (no silent dead air)
- **Safe Memory Reset** - Automatic backup before clearing conversation history

## 📁 Project Structure

```
FAST-RFSN/
├── Python/
│   ├── orchestrator.py        # FastAPI streaming server
│   ├── streaming_engine.py    # Streaming pipeline with fixes
│   ├── piper_tts.py           # Piper TTS engine
│   ├── memory_manager.py      # Persistent conversation memory
│   ├── launch_optimized.py    # One-click launcher
│   ├── requirements.txt       # Dependencies
│   └── tests/                 # Comprehensive test suite
├── Dashboard/
│   └── index.html             # Live metrics dashboard
├── Models/
│   └── piper/                 # Voice models (auto-downloaded)
├── config.json                # Configuration
└── validate_deployment.py     # Pre-flight checker
```

## 🔧 API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/dialogue/stream` | POST | Stream NPC dialogue |
| `/api/memory/{npc}/safe_reset` | POST | Reset with backup |
| `/api/memory/{npc}/stats` | GET | Memory statistics |
| `/api/status` | GET | Health check |
| `/ws/metrics` | WS | Live performance metrics |

## 📊 Performance Targets

- First sentence latency: **<1.5s**
- Token-to-speech pipeline: **<100ms**
- Backpressure queue: **3 sentences**

## 🧪 Testing

```bash
cd Python
python -m pytest tests/ -v
```

## 📄 License

MIT License
