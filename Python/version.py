# version.py
# Single source of truth for version strings
# Import this everywhere instead of hardcoding versions

ORCHESTRATOR_VERSION = "8.2.0"
STREAMING_ENGINE_VERSION = "9.0.0"
PIPER_TTS_VERSION = "3.0.0"
LEARNING_LAYER_VERSION = "1.0.0"

# Build identifier (can be overwritten by CI/CD)
BUILD_ID = "RFSN-ORCHESTRATOR-local"

def get_version_string() -> str:
    """Returns a formatted version string for logging/display"""
    return f"RFSN Orchestrator v{ORCHESTRATOR_VERSION} (Engine v{STREAMING_ENGINE_VERSION})"
