# Skyrim NPC Integration Specification

## Overview

This document specifies two integration paths for RFSN with Skyrim Special Edition:
- **Path A**: Bounded dialogue using Skyrim's native dialogue system (fastest, most stable)
- **Path B**: Dynamic speech using SKSE plugin bridge (advanced, requires more setup)

Both paths maintain RFSN as the authoritative state machine while respecting Skyrim's modding constraints.

---

## Architecture Principles

- **RFSN Authority**: RFSN manages state, memory, and action selection
- **Skyrim Execution**: Skyrim executes actions through dialogue, animations, or scripts
- **Bounded Fallback**: Always have pre-authored fallback lines
- **State-Driven**: Use Skyrim conditions to gate dialogue based on RFSN state
- **Safety First**: Never let LLM control game logic or quest progression

---

## Path A: Bounded Dialogue (Recommended)

This path uses Skyrim's native dialogue system with RFSN providing state management and action selection. **This is production-ready and shippable.**

### How It Works

1. RFSN selects action and state
2. RFSN outputs topic ID and variant number
3. Skyrim dialogue system plays corresponding pre-authored line
4. Skyrim conditions check RFSN state via global variables
5. No LLM required (optional enhancement later)

### Data Flow

```
Player → RFSN Service
         ↓
    State Update
         ↓
    Action Selection
         ↓
    Topic + Variant
         ↓
Skyrim Dialogue System
         ↓
    Play Audio + Subtitle
```

### RFSN Decision Output (Path A)

```json
{
  "npc_id": "BarkeepJon",
  "state": "FRIENDLY",
  "action_id": "GREET",
  "topic_id": "BarkeepGreeting",
  "variant": 2,
  "global_vars": {
    "RFSN_STATE": "FRIENDLY",
    "RFSN_AFFINITY": 0.7,
    "RFSN_TRUST": 0.6
  }
}
```

### Skyrim Dialogue Structure

**Creation Kit Example:**

```
Topic: BarkeepGreeting
  Condition: GetDistance Player < 500
  Condition: IsWeaponOut == 0
  Condition: GlobalVariable RFSN_STATE == FRIENDLY
  
  Response 1: "Welcome, traveler. What can I get you?"
  Response 2: "Ah, good to see a friendly face."
  Response 3: "Come in, come in! We've got warm food and cold drinks."
```

### Global Variables Setup

Create these global variables in Creation Kit:

| Variable Name | Type | Initial | Purpose |
|--------------|------|---------|---------|
| `RFSN_STATE` | Int | 0 | State enum (0=NEUTRAL, 1=FRIENDLY, 2=ALERT, 3=HOSTILE) |
| `RFSN_AFFINITY` | Float | 0.5 | NPC affinity toward player (0.0-1.0) |
| `RFSN_TRUST` | Float | 0.5 | NPC trust level (0.0-1.0) |
| `RFSN_FEAR` | Float | 0.0 | NPC fear level (0.0-1.0) |

### Papyrus Script Integration

**RFSNBridge.psc** (runs on NPC):

```papyrus
Scriptname RFSNBridge extends Actor

; Global variables
GlobalVariable Property RFSN_STATE Auto
GlobalVariable Property RFSN_AFFINITY Auto
GlobalVariable Property RFSN_TRUST Auto

; HTTP request to RFSN service
Function UpdateState(String playerInput)
    ; Build observation
    String observation = BuildObservation(playerInput)
    
    ; Send to RFSN service (via SKSE HTTP if available)
    String decision = SendToRFSN(observation)
    
    ; Parse decision and update globals
    ParseDecision(decision)
EndFunction

Function ParseDecision(String decision)
    ; Parse JSON response
    Int newState = GetStateFromJSON(decision)
    Float newAffinity = GetAffinityFromJSON(decision)
    
    ; Update global variables
    RFSN_STATE.SetValue(newState)
    RFSN_AFFINITY.SetValue(newAffinity)
EndFunction

String Function BuildObservation(String playerInput)
    Float distance = Self.GetDistance(Game.GetPlayer())
    Bool weaponDrawn = Game.GetPlayer().IsWeaponDrawn()
    
    ; Build simple observation packet
    String obs = "{"
    obs += "\"npc_id\":\"" + Self.GetDisplayName() + "\","
    obs += "\"distance\":" + distance + ","
    obs += "\"weapon_drawn\":" + weaponDrawn + ","
    obs += "\"player_input\":\"" + playerInput + "\""
    obs += "}"
    
    Return obs
EndFunction
```

### Action-to-Topic Mapping

Define mappings for each NPC:

| Action ID | Topic ID | Description |
|-----------|----------|-------------|
| `GREET` | `NPCGreeting` | Friendly greeting |
| `WARN` | `NPCWarning` | Warning/threat |
| `BARGAIN` | `NPCBargain` | Offer trade/quest |
| `THREATEN` | `NPCThreat` | Combat threat |
| `FLEE` | `NPCFlee` | Flee dialogue |
| `HELP` | `NPCHelp` | Offer assistance |
| `REFUSE` | `NPCRefuse` | Decline request |
| `EXPLAIN` | `NPCExplain` | Provide information |

### Variant Selection Strategy

RFSN can select variants based on:
- Recent conversation history (avoid repetition)
- Time of day
- Location
- Quest state
- Random variation

**Example:**
```python
# In RFSN action selector
variants = [1, 2, 3]  # Available variants for this topic
# Exclude recently used
recent = memory.get_recent_variants("BarkeepGreeting", window=5)
available = [v for v in variants if v not in recent]
# Select from available
variant = random.choice(available) if available else random.choice(variants)
```

### Pros and Cons

**Pros:**
- ✅ Stable and production-ready
- ✅ No voice synthesis required
- ✅ Uses native Skyrim systems
- ✅ Easy to author and test
- ✅ Compatible with all Skyrim versions
- ✅ No SKSE dependency (basic version)

**Cons:**
- ❌ Limited to pre-authored lines
- ❌ Requires Creation Kit work for each NPC
- ❌ Less dynamic than full LLM approach
- ❌ Variant management overhead

---

## Path B: Dynamic Speech (Advanced)

This path uses SKSE plugin to bridge Skyrim with RFSN's LLM dialogue realizer. **This is more complex but enables fully dynamic dialogue.**

### How It Works

1. SKSE plugin captures dialogue start event
2. Plugin sends player utterance to RFSN service
3. RFSN selects action and generates intent
4. LLM realizes dialogue line from intent
5. TTS generates voice audio
6. Plugin injects audio + subtitle into Skyrim

### Data Flow

```
Player Speech (STT) or Text
         ↓
   SKSE Plugin
         ↓
   RFSN Service
         ↓
   LLM Dialogue Realizer
         ↓
   TTS Engine (xVASynth)
         ↓
   Audio File
         ↓
   SKSE Audio Injection
         ↓
   Skyrim Playback + Subtitle
```

### Technical Components

#### 1. SKSE Plugin (C++)

**RFSNBridge.cpp**:

```cpp
#include "skse64/PluginAPI.h"
#include "skse64/GameEvents.h"
#include <curl/curl.h>
#include <json/json.h>

class DialogueEventHandler : public BSTEventSink<TESTopicInfoEvent>
{
public:
    virtual EventResult ReceiveEvent(TESTopicInfoEvent* evn, EventDispatcher<TESTopicInfoEvent>* dispatcher)
    {
        // Validate pointers
        // SKSE may dispatch TESTopicInfoEvent with null event data, speaker, or targetInfo
        // (for example during load/unload or when dialogue is aborted). We must treat these
        // as no-op and continue to avoid dereferencing invalid pointers in the event sink.
        if (!evn || !evn->speaker || !evn->targetInfo)
        {
            _ERROR("[RFSN] Null pointer in dialogue event");
            return kEvent_Continue;
        }
        
        if (evn->stage == TESTopicInfoEvent::kStage_Begin)
        {
            // Capture dialogue start
            HandleDialogueStart(evn->speaker, evn->targetInfo);
        }
        return kEvent_Continue;
    }
    
    void HandleDialogueStart(TESObjectREFR* speaker, TESTopicInfo* info)
    {
        try
        {
            // Get player input
            std::string playerInput = GetPlayerInput();
            
            // Build observation packet
            Json::Value observation;
            observation["npc_id"] = GetNPCId(speaker);
            observation["player_input"] = playerInput;
            observation["distance"] = GetDistance(speaker);
            
            // Send to RFSN service
            std::string decision = SendToRFSN(observation.toStyledString());
            
            // Parse response
            Json::Value response;
            Json::Reader reader;
            if (!reader.parse(decision, response))
            {
                _ERROR("[RFSN] Failed to parse JSON response");
                return;
            }
            
            // Get dialogue line
            std::string dialogueLine = response.get("dialogue_line", "").asString();
            if (dialogueLine.empty())
            {
                _WARNING("[RFSN] Empty dialogue line received");
                return;
            }
            
            // Generate TTS
            std::string audioPath = GenerateTTS(dialogueLine, GetNPCVoice(speaker));
            
            // Inject audio
            PlayAudio(speaker, audioPath);
            
            // Show subtitle
            ShowSubtitle(dialogueLine);
        }
        catch (const std::exception& ex)
        {
            _ERROR("[RFSN] Exception in HandleDialogueStart: %s", ex.what());
        }
    }
};
```

#### 2. RFSN Service Endpoint

**New endpoint in orchestrator.py**:

```python
@app.post("/api/skyrim/dialogue")
async def skyrim_dialogue(request: SkyrimDialogueRequest):
    """
    Handle Skyrim dialogue request with RFSN decision + LLM realization.
    """
    # Build observation from request
    observation = {
        "npc_id": request.npc_id,
        "player": {
            "distance": request.distance,
            "last_utterance": request.player_input
        }
    }
    
    # Get RFSN decision
    decision = rfsn_decide(observation)
    
    # Realize dialogue with LLM
    prompt = build_llm_prompt(
        npc_name=request.npc_id,
        action_intent=decision["action_intent"],
        player_utterance=request.player_input,
        facts=decision["facts"],
        constraints=decision["dialogue_constraints"]
    )
    
    dialogue_line = await llm_realize(prompt)
    
    # Return response
    return {
        "dialogue_line": dialogue_line,
        "state": decision["state"],
        "action_id": decision["action_id"]
    }
```

#### 3. TTS Integration (xVASynth)

Use xVASynth for Skyrim-accurate voice synthesis:

```python
import requests

def generate_skyrim_tts(text: str, voice_model: str) -> str:
    """
    Generate TTS using xVASynth.
    
    Args:
        text: Dialogue text to synthesize
        voice_model: Skyrim voice model (e.g., "maleguard01")
        
    Returns:
        Path to generated audio file
        
    Raises:
        RuntimeError: If TTS generation fails
    """
    try:
        response = requests.post(
            "http://localhost:8008/synthesize",
            json={
                "text": text,
                "voice": voice_model,
                "pace": 1.0,
                "pitch": 1.0
            },
            timeout=5.0
        )
        
        response.raise_for_status()
        
        data = response.json()
        if "audio_path" not in data:
            raise RuntimeError("Missing audio_path in response")
        
        audio_path = data["audio_path"]
        
        # Verify file exists
        if not os.path.exists(audio_path):
            raise RuntimeError(f"Generated audio file not found: {audio_path}")
        
        return audio_path
        
    except requests.Timeout:
        raise RuntimeError("TTS request timeout")
    except requests.RequestException as ex:
        raise RuntimeError(f"TTS network error: {ex}")
    except (KeyError, ValueError) as ex:
        raise RuntimeError(f"Invalid TTS response: {ex}")
```

#### 4. Audio Injection

**SkyrimAudioInjector.cpp**:

```cpp
void PlayAudio(TESObjectREFR* speaker, const char* audioPath)
{
    // Load audio file
    BSISoundDescriptor* sound = LoadSoundFromFile(audioPath);
    
    // Play on speaker
    PlaySound(speaker, sound);
}

void ShowSubtitle(const char* text)
{
    // Get subtitle manager
    SubtitleManager* manager = SubtitleManager::GetSingleton();
    
    // Show subtitle
    manager->ShowSubtitle(text, 5.0f);  // 5 second duration
}
```

### Observation Packet (Path B)

```json
{
  "npc_id": "BarkeepJon",
  "scene_id": "Whiterun_BanneredMare",
  "player": {
    "distance": 150.0,
    "facing_dot": 0.8,
    "is_weapon_drawn": false,
    "last_utterance": "Got any work for me?"
  },
  "world": {
    "threat_level": 0.0,
    "time_of_day": 18.5,
    "location": "BanneredMare"
  },
  "quest_flags": {
    "main_quest_stage": 20,
    "player_is_thane": false
  }
}
```

### Decision Output (Path B)

```json
{
  "npc_id": "BarkeepJon",
  "state": "FRIENDLY",
  "action_id": "HELP",
  "action_intent": "Offer the player a simple task.",
  "dialogue_line": "I might have something. There's been trouble with bandits on the road. Clear them out and I'll pay you well.",
  "audio_path": "/tmp/skyrim_tts/barkeep_response_001.wav",
  "duration": 5.2
}
```

### Minimum Technical Requirements

**Required:**
- SKSE64 (Skyrim Script Extender)
- HTTP library for SKSE plugin (libcurl)
- xVASynth for TTS (or alternative)
- RFSN service running on localhost or LAN

**Optional:**
- Speech-to-text for player voice input
- Lip sync generation (FonixData)
- Facial animation control

### Integration Options

#### Option 1: Existing Mod Framework

Use existing AI dialogue mods as a base:
- **Mantella**: Already has SKSE bridge and TTS integration
- **Herika**: Has dialogue interception hooks
- **AIFF**: Has LLM integration patterns

#### Option 2: Custom SKSE Plugin

Build custom plugin from scratch:
- More control over integration
- Can optimize for RFSN specifically
- Requires C++ development

#### Option 3: Hybrid Approach

Combine both:
- Use existing mod for SKSE hooks and audio
- Replace AI backend with RFSN
- Modify prompts to use RFSN structure

### Pros and Cons

**Pros:**
- ✅ Fully dynamic dialogue
- ✅ No pre-authoring required
- ✅ Leverages full RFSN capabilities
- ✅ Can adapt to any player input

**Cons:**
- ❌ Complex setup (SKSE plugin required)
- ❌ TTS quality may vary
- ❌ Higher latency (network + LLM + TTS)
- ❌ Requires local service or cloud deployment
- ❌ Harder to debug and test

---

## Fallback Strategy

**Critical**: Always have a fallback path if RFSN service is unavailable.

### Fallback Levels

1. **Network Failure**: Use Path A (bounded dialogue)
2. **LLM Failure**: Use pre-cached responses for common actions
3. **TTS Failure**: Show subtitle only
4. **Complete Failure**: Use vanilla Skyrim dialogue

### Implementation

```papyrus
Function SafeDialogue(String playerInput)
    If IsRFSNAvailable()
        ; Try RFSN path
        TryRFSNDialogue(playerInput)
    Else
        ; Fall back to bounded dialogue
        UseBoundedDialogue()
    EndIf
EndFunction

Bool Function IsRFSNAvailable()
    ; Check if service responds within timeout
    Return CheckHTTPConnection("http://localhost:8000/health", 1.0)
EndFunction
```

---

## Data Contracts

### Shared Between Paths

Both paths use the same core data structures for RFSN state:

#### State Enum

```
0 = NEUTRAL   (Default state)
1 = FRIENDLY  (Positive affinity)
2 = ALERT     (Cautious, elevated attention)
3 = HOSTILE   (Combat imminent)
4 = FEARFUL   (Wants to flee)
```

#### Action Set

```
GREET, WARN, THREATEN, FLEE, ATTACK, HELP,
REFUSE, EXPLAIN, BARGAIN, APOLOGIZE, IGNORE
```

---

## Testing Strategy

### Path A Testing

1. Create test NPC in Creation Kit
2. Set up global variables
3. Create dialogue topics with conditions
4. Test in-game with console commands
5. Verify state transitions

**Console Commands:**
```
set RFSN_STATE to 1  ; Set to FRIENDLY
set RFSN_AFFINITY to 0.8
```

### Path B Testing

1. Deploy RFSN service locally
2. Load SKSE plugin
3. Test with debug logging enabled
4. Verify network communication
5. Check TTS generation
6. Validate audio playback

**Debug Logging:**
```cpp
_MESSAGE("[RFSN] Sending request to service...");
_MESSAGE("[RFSN] Received response: %s", response.c_str());
_MESSAGE("[RFSN] Playing audio: %s", audioPath.c_str());
```

---

## Performance Considerations

### Path A Performance

- ✅ Instant (native dialogue system)
- ✅ No network latency
- ✅ No TTS generation
- ✅ Minimal CPU usage

### Path B Performance

| Step | Latency |
|------|---------|
| Network request | 10-50ms |
| RFSN decision | 20-100ms |
| LLM generation | 500-2000ms |
| TTS synthesis | 200-1000ms |
| Audio playback | 0ms (async) |
| **Total** | **730-3150ms** |

**Optimization Tips:**
- Cache common responses
- Pre-generate TTS for frequent lines
- Use streaming TTS if available
- Run RFSN service on local network
- Use faster LLM models (quantized)

---

## Security Considerations

### Content Filtering

Even with RFSN constraints, add Skyrim-specific filters:

```python
SKYRIM_BANNED_WORDS = [
    # Modern terms that break immersion
    "internet", "computer", "phone", "AI",
    # Explicit content
    # ... add as needed
]

def filter_skyrim_content(text: str) -> str:
    for word in SKYRIM_BANNED_WORDS:
        if word.lower() in text.lower():
            return "[The NPC remains silent]"
    return text
```

### Quest Protection

Never let LLM control quest logic:

```python
# In RFSN decision layer
if npc_has_active_quest(npc_id):
    # Use bounded dialogue only
    use_path_a = True
    # Or restrict action set
    allowed_actions = ["EXPLAIN", "HELP", "AGREE"]
```

---

## Deployment Checklist

### Path A Deployment

- [ ] Create global variables in Creation Kit
- [ ] Author dialogue topics for each NPC
- [ ] Create dialogue conditions based on RFSN state
- [ ] Attach Papyrus script to NPCs
- [ ] Test state transitions
- [ ] Package as ESP file
- [ ] Document required global variables
- [ ] Create MCM configuration menu (optional)

### Path B Deployment

- [ ] Build SKSE plugin
- [ ] Deploy RFSN service (local or cloud)
- [ ] Configure xVASynth or TTS alternative
- [ ] Test network communication
- [ ] Verify audio injection works
- [ ] Create fallback dialogue
- [ ] Package plugin + ESP
- [ ] Write installation guide
- [ ] Create troubleshooting guide

---

## Recommended Approach

**Start with Path A:**
1. Implement bounded dialogue system
2. Validate RFSN state management works
3. Test with players
4. Gather feedback

**Upgrade to Path B if needed:**
1. Add SKSE plugin
2. Integrate LLM realizer
3. Add TTS generation
4. Keep Path A as fallback

This ensures a stable, shippable product while allowing future enhancement.

---

## Example: Complete Path A Implementation

### 1. Global Variables (Creation Kit)

Create:
- `RFSN_STATE` (Int, default 0)
- `RFSN_AFFINITY` (Float, default 0.5)

### 2. NPC Dialogue (Creation Kit)

**Topic: BarkeepGreeting**

Conditions:
- `GetDistance Player < 500`
- `RFSN_STATE == 1` (FRIENDLY)

Responses:
- Variant 1: "Welcome! What'll it be?"
- Variant 2: "Good to see you again, friend."
- Variant 3: "Pull up a chair, drinks are cold!"

**Topic: BarkeepWarn**

Conditions:
- `GetDistance Player < 500`
- `RFSN_STATE == 2` (ALERT)

Responses:
- Variant 1: "Easy now, no trouble here."
- Variant 2: "Watch yourself, stranger."

### 3. Papyrus Script

```papyrus
Scriptname BarkeepRFSN extends Actor

GlobalVariable Property RFSN_STATE Auto
GlobalVariable Property RFSN_AFFINITY Auto

Event OnInit()
    RegisterForUpdate(5.0)  ; Update every 5 seconds
EndEvent

Event OnUpdate()
    UpdateRFSNState()
EndEvent

Function UpdateRFSNState()
    Float distance = Self.GetDistance(Game.GetPlayer())
    
    If distance < 300
        ; Player is close, be friendly
        RFSN_STATE.SetValue(1)
        RFSN_AFFINITY.Mod(0.01)
    ElseIf distance > 1000
        ; Player is far, return to neutral
        RFSN_STATE.SetValue(0)
    EndIf
EndFunction
```

### 4. Testing

1. Place NPC in worldspace
2. Attach script
3. Approach NPC
4. Verify dialogue triggers correctly
5. Check console: `show RFSN_STATE`

---

## Support Resources

### Documentation
- SKSE Documentation: https://skse.silverlock.org/
- Creation Kit Wiki: https://ck.uesp.net/
- xVASynth: https://github.com/DanRuta/xVA-Synth

### Community
- Skyrim Modding Discord
- r/skyrimmods
- SKSE Plugin Development Forum

---

## Conclusion

Both paths are viable. **Path A** is recommended for initial release due to stability and ease of implementation. **Path B** can be added later as an enhancement for users who want fully dynamic dialogue.

The key is to keep RFSN as the brain while letting Skyrim handle execution, maintaining the "LLM realizes, doesn't decide" principle throughout.
