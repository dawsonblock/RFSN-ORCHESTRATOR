# NPC Integration Specification

## Overview

This document defines how game engines (Unity, Skyrim) integrate with the RFSN Orchestrator to create intelligent, responsive NPCs. The orchestrator acts as the authoritative NPC brain, making action decisions and generating dialogue based on game state.

## Architecture Principles

1. **Game engine never calls LLM directly** - All AI decisions go through the orchestrator
2. **Orchestrator never reaches into game state** - Game provides explicit state via API
3. **Actions chosen before speech** - NPC behavior is deterministic and game-controllable
4. **Streaming-first** - Dialogue and voice stream in real-time for responsive feel

---

## Data Contract: Game → Orchestrator

### Request Endpoint

```
POST /api/dialogue/stream
Content-Type: application/json
```

### Request Body

```json
{
  "user_input": "What do you know about the dragons?",
  "npc_state": {
    "npc_name": "Lydia",
    "mood": "neutral",
    "affinity": 0.3,
    "relationship": "ally",
    "recent_sentiment": 0.1,
    "combat_active": false,
    "quest_active": true,
    "trust_level": 0.7,
    "fear_level": 0.1
  },
  "enable_voice": true,
  "tts_engine": "piper"
}
```

### Required Fields

| Field | Type | Description | Valid Values |
|-------|------|-------------|--------------|
| `npc_name` | string | Unique NPC identifier | Any string |
| `mood` | string | Current emotional state | "happy", "neutral", "sad", "angry", "fearful" |
| `affinity` | float | NPC's fondness for player | -1.0 (hostile) to 1.0 (friendly) |
| `relationship` | string | Social bond type | "stranger", "acquaintance", "friend", "ally", "enemy" |
| `recent_sentiment` | float | Sentiment of recent interaction | -1.0 to 1.0 |
| `combat_active` | boolean | Is NPC in combat? | true/false |
| `quest_active` | boolean | Is NPC involved in active quest? | true/false |
| `trust_level` | float | Player's trustworthiness | 0.0 (untrusted) to 1.0 (trusted) |
| `fear_level` | float | NPC's fear of player | 0.0 (fearless) to 1.0 (terrified) |

### Optional Fields

| Field | Type | Description |
|-------|------|-------------|
| `world_facts` | array[string] | Contextual world information (e.g., ["dragon_nearby", "raining"]) |
| `playstyle` | string | Player's observed style (e.g., "stealth", "combat") |

---

## Response Contract: Orchestrator → Game

### Response Format

Server-Sent Events (SSE) stream with two event types:

#### 1. Metadata Event (First Event)

```json
{
  "type": "meta",
  "npc_name": "Lydia",
  "npc_action": "explain",
  "action_mode": "DETAILED_EMPATHETIC",
  "player_signal": "question"
}
```

**Purpose**: Tells game engine which animation/behavior to trigger

**Fields**:
- `npc_action`: The chosen NPC action (see Action Types below)
- `action_mode`: Dialogue style (TERSE_DIRECT, DETAILED_EMPATHETIC, FORMAL_CAUTIOUS)
- `player_signal`: Detected player intent

#### 2. Sentence Events (Dialogue Stream)

```json
{
  "sentence": "The dragons have returned to Skyrim after centuries.",
  "is_final": false,
  "latency_ms": 45.2
}
```

**Purpose**: Streams dialogue for subtitles and voice synthesis

**Fields**:
- `sentence`: Text chunk for display/TTS
- `is_final`: true on last sentence
- `latency_ms`: Generation latency for monitoring

---

## NPC Action Types

The `npc_action` field determines the NPC's behavioral intent. Game engines should map these to animations and state changes.

### Social Actions
- `GREET` - Welcome/acknowledge player
- `FAREWELL` - End conversation
- `AGREE` - Consent to player's request
- `DISAGREE` - Reject player's statement
- `APOLOGIZE` - Express regret

### Emotional Actions
- `COMPLIMENT` - Praise player
- `INSULT` - Belittle player
- `THREATEN` - Issue warning

### Transactional Actions
- `OFFER` - Propose trade/help
- `REQUEST` - Ask for something
- `ACCEPT` - Agree to deal
- `REFUSE` - Decline request

### Combat Actions
- `ATTACK` - Hostile action
- `DEFEND` - Defensive stance
- `FLEE` - Retreat from danger

### Informational Actions
- `INQUIRE` - Ask question
- `EXPLAIN` - Provide information
- `HELP` - Offer assistance
- `IGNORE` - Dismiss player

### Special Actions
- `BETRAY` - Break trust

---

## Unity Integration

### C# Client Implementation

```csharp
using System;
using System.Net.Http;
using System.Text;
using System.Threading.Tasks;
using UnityEngine;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

public class NPCController : MonoBehaviour
{
    [SerializeField] private string npcName = "Guard";
    [SerializeField] private string orchestratorUrl = "http://localhost:8001";
    
    private NPCState npcState = new NPCState();
    private Animator animator;
    private AudioSource audioSource;
    
    void Start()
    {
        animator = GetComponent<Animator>();
        audioSource = GetComponent<AudioSource>();
    }
    
    public async Task OnPlayerSpeak(string playerInput)
    {
        var request = new DialogueRequest
        {
            user_input = playerInput,
            npc_state = npcState.ToDict()
        };
        
        await StreamDialogue(request);
    }
    
    private async Task StreamDialogue(DialogueRequest request)
    {
        using var client = new HttpClient();
        var content = new StringContent(
            JsonConvert.SerializeObject(request),
            Encoding.UTF8,
            "application/json"
        );
        
        var response = await client.PostAsync(
            $"{orchestratorUrl}/api/dialogue/stream",
            content
        );
        
        using var stream = await response.Content.ReadAsStreamAsync();
        using var reader = new StreamReader(stream);
        
        bool firstEvent = true;
        string line;
        while ((line = await reader.ReadLineAsync()) != null)
        {
            if (!line.StartsWith("data: ")) continue;
            
            var json = line.Substring(6);
            var data = JObject.Parse(json);
            
            if (firstEvent && data["type"]?.ToString() == "meta")
            {
                // First event: trigger animation
                var action = data["npc_action"]?.ToString();
                TriggerAnimation(action);
                firstEvent = false;
            }
            else if (data["sentence"] != null)
            {
                // Dialogue event: show subtitle and play audio
                var sentence = data["sentence"].ToString();
                ShowSubtitle(sentence);
                // Optionally: await SynthesizeSpeech(sentence);
            }
        }
    }
    
    private void TriggerAnimation(string action)
    {
        switch (action)
        {
            case "greet":
                animator.SetTrigger("Wave");
                break;
            case "attack":
                animator.SetTrigger("DrawWeapon");
                break;
            case "flee":
                animator.SetTrigger("RunAway");
                break;
            case "agree":
                animator.SetTrigger("Nod");
                break;
            // Add more mappings...
        }
    }
    
    private void ShowSubtitle(string text)
    {
        // Display in UI
        Debug.Log($"[{npcName}]: {text}");
    }
}

[Serializable]
public class NPCState
{
    public string npc_name;
    public string mood = "neutral";
    public float affinity = 0.0f;
    public string relationship = "stranger";
    public float recent_sentiment = 0.0f;
    public bool combat_active = false;
    public bool quest_active = false;
    public float trust_level = 0.5f;
    public float fear_level = 0.0f;
    
    public Dictionary<string, object> ToDict()
    {
        return new Dictionary<string, object>
        {
            ["npc_name"] = npc_name,
            ["mood"] = mood,
            ["affinity"] = affinity,
            ["relationship"] = relationship,
            ["recent_sentiment"] = recent_sentiment,
            ["combat_active"] = combat_active,
            ["quest_active"] = quest_active,
            ["trust_level"] = trust_level,
            ["fear_level"] = fear_level
        };
    }
}

[Serializable]
public class DialogueRequest
{
    public string user_input;
    public Dictionary<string, object> npc_state;
}
```

### Unity State Management

Update NPC state based on gameplay events:

```csharp
// On player attacks NPC
npcState.combat_active = true;
npcState.affinity -= 0.3f;
npcState.fear_level += 0.5f;

// On quest acceptance
npcState.quest_active = true;
npcState.relationship = "ally";

// On positive interaction
npcState.affinity = Mathf.Clamp(npcState.affinity + 0.1f, -1f, 1f);
npcState.mood = "happy";
```

---

## Skyrim Integration

### Architecture

1. **SKSE Plugin** (preferred) or **Papyrus + HTTP Bridge**
2. **Event Loop**: Player dialogue → Send request → Receive stream → Feed to xVASynth/Subtitles
3. **Session Management**: Per-NPC session IDs for memory persistence

### SKSE Plugin Approach (Recommended)

```cpp
// NPCOrchestrator.h
#pragma once
#include <string>
#include <functional>

class NPCOrchestrator {
public:
    static NPCOrchestrator* GetSingleton();
    
    void SendDialogue(
        const char* npcName,
        const char* playerInput,
        RE::TESObjectREFR* npcRef,
        std::function<void(const char*)> onSentence
    );
    
private:
    struct NPCState {
        std::string name;
        std::string mood;
        float affinity;
        std::string relationship;
        bool combatActive;
        bool questActive;
        float trustLevel;
        float fearLevel;
    };
    
    NPCState ExtractState(RE::TESObjectREFR* npcRef);
    void StreamResponse(const std::string& url, const std::string& body);
};
```

### Papyrus Bridge (Alternative)

```papyrus
Scriptname NPCOrchestratorBridge extends Quest

String Property OrchestratorURL = "http://localhost:8001" AutoReadOnly

Function SendDialogue(Actor npc, String playerInput)
    ; Build state dict
    Float affinity = npc.GetRelationshipRank(Game.GetPlayer()) / 4.0
    Bool inCombat = npc.IsInCombat()
    
    ; Call HTTP bridge (external tool)
    String response = HTTPCall(OrchestratorURL + "/api/dialogue/stream", BuildJSON(npc, playerInput, affinity, inCombat))
    
    ; Parse and display
    ParseResponse(npc, response)
EndFunction

String Function BuildJSON(Actor npc, String input, Float affinity, Bool combat)
    ; Construct JSON request
    return "{\"user_input\":\"" + input + "\",\"npc_state\":{\"npc_name\":\"" + npc.GetDisplayName() + "\",\"affinity\":" + affinity + ",\"combat_active\":" + combat + "}}"
EndFunction

Function ParseResponse(Actor npc, String json)
    ; Extract sentences and feed to subtitles/xVASynth
    Debug.Notification("[" + npc.GetDisplayName() + "]: " + ExtractSentence(json))
EndFunction
```

### xVASynth Integration

For voice synthesis, process orchestrator SSE output:

```bash
# Example: Extract sentences from SSE stream and send to xVASynth
curl -X POST http://localhost:8001/api/dialogue/stream \
  -H "Content-Type: application/json" \
  -d '{"user_input":"Hello","npc_state":{"npc_name":"Lydia","mood":"neutral","affinity":0.0,"relationship":"stranger","recent_sentiment":0.0,"combat_active":false,"quest_active":false,"trust_level":0.5,"fear_level":0.0}}' \
  | grep '^data: ' \
  | sed 's/^data: //' \
  | jq -r 'select(.sentence != null) | .sentence' \
  | while read -r sentence; do
      echo "$sentence" | xvasynth --voice skyrim_lydia --output "audio_${RANDOM}.wav"
    done
```

**Note**: This is a simplified example. Production integration should use proper SSE parsing libraries.

---

## Sequence Diagrams

### Normal Dialogue Flow

```
Player → Game: "What's your story?"
Game → Orchestrator: POST /api/dialogue/stream
                      {user_input, npc_state}
Orchestrator → Game: SSE meta {npc_action: "explain"}
Game → NPC: Trigger "explain" animation
Orchestrator → Game: SSE sentence "I grew up in Whiterun..."
Game → Player: Show subtitle + play TTS
Orchestrator → Bandit: Update reward for "explain"
Bandit → Disk: Persist learning
```

### Combat Override

```
Player → Game: Attacks NPC
Game → Orchestrator: POST /api/dialogue/stream
                      {user_input: "attack", combat_active: true}
Orchestrator: ActionScorer forces FLEE (safety override)
Orchestrator → Game: SSE meta {npc_action: "flee"}
Game → NPC: Trigger "flee" animation
Orchestrator → Game: SSE sentence "I need to get out of here!"
Game → Player: Show subtitle
Bandit: NO UPDATE (forced action bypasses learning)
```

---

## Session Management

### Creating Sessions

```http
POST /api/dialogue/stream
{
  "user_input": "...",
  "npc_state": {
    "npc_name": "Lydia",
    ...
  }
}
```

Memory is automatically managed per `npc_name`.

### Resetting Memory

```http
POST /api/memory/Lydia/safe_reset
Authorization: Bearer <api_key>
```

Creates backup before clearing conversation history.

---

## Caching Strategy

### Per-NPC Session IDs

Game engines should maintain session IDs per NPC:

```csharp
private Dictionary<string, string> npcSessions = new Dictionary<string, string>();

string GetSessionId(string npcName)
{
    if (!npcSessions.ContainsKey(npcName))
    {
        npcSessions[npcName] = Guid.NewGuid().ToString();
    }
    return npcSessions[npcName];
}
```

### Memory Reset Endpoints

- `POST /api/memory/{npc_name}/safe_reset` - Reset with backup
- `GET /api/memory/{npc_name}/stats` - Get memory statistics
- `GET /api/memory/backups` - List all backups

---

## Error Handling

### Network Errors

```csharp
try
{
    await StreamDialogue(request);
}
catch (HttpRequestException e)
{
    // Fallback: Use canned dialogue
    ShowSubtitle("I don't have much to say right now.");
    Debug.LogError($"Orchestrator unreachable: {e.Message}");
}
```

### Timeout Strategy

```csharp
var cts = new CancellationTokenSource(TimeSpan.FromSeconds(5));
try
{
    await StreamDialogue(request, cts.Token);
}
catch (TaskCanceledException)
{
    ShowSubtitle("...");
}
```

### Empty Response Handling

If orchestrator returns no sentences:
1. Display fallback text
2. Log error for debugging
3. Continue gameplay without blocking

---

## Performance Considerations

### Latency Targets

- **First token**: < 200ms (metadata event)
- **First sentence**: < 500ms
- **Sentence streaming**: 50-100ms per chunk

### Bandwidth

- **Metadata**: ~200 bytes
- **Sentence**: ~100-500 bytes per event
- **Total per dialogue turn**: 1-5 KB

### Threading

Unity: Use `async`/`await` to avoid blocking main thread
Skyrim: Run HTTP calls on background thread or use async Papyrus (SKSE)

---

## Security

### Authentication

For production deployments, use API keys:

```csharp
client.DefaultRequestHeaders.Add("Authorization", "Bearer <api_key>");
```

### Rate Limiting

Orchestrator enforces rate limits:
- 100 requests/minute per client
- 10 concurrent streams per client

### Content Filtering

Orchestrator filters harmful content via IntentGate:
- Blocks violence descriptions
- Blocks real-world harm proposals
- Filters low-confidence outputs

---

## Testing

### Unit Test (Unity)

```csharp
[Test]
public async Task TestDialogueFlow()
{
    var controller = new NPCController();
    controller.npcState.npc_name = "TestNPC";
    
    await controller.OnPlayerSpeak("Hello");
    
    Assert.IsTrue(controller.lastAction == "greet");
    Assert.IsNotEmpty(controller.lastSubtitle);
}
```

### Integration Test (Orchestrator)

```python
def test_forced_action_bypass():
    """Bandit should not learn from forced actions"""
    state = StateSnapshot(
        mood="fearful",
        affinity=-0.8,
        relationship="enemy",
        combat_active=True,
        trust_level=0.1,
        fear_level=0.9,
        recent_sentiment=-0.9
    )
    
    # ActionScorer forces FLEE
    scores = action_scorer.score_candidates(state, PlayerSignal.ATTACK)
    assert len(scores) == 1
    assert scores[0].action == NPCAction.FLEE
    
    # Bandit should not be called
    # (test by checking bandit update count remains 0)
```

---

## Appendix: Complete Example Flow

```
1. Player clicks NPC in Unity
2. Unity captures NPC state from game objects
3. Unity sends POST to orchestrator
4. Orchestrator receives request
5. ActionScorer generates candidates (GREET, INQUIRE, OFFER)
6. Bandit selects GREET based on learned policy
7. Orchestrator emits SSE meta {npc_action: "greet"}
8. Unity receives meta event, triggers wave animation
9. Orchestrator generates "Well met, traveler!"
10. Unity receives sentence event, shows subtitle
11. Unity plays TTS audio via Piper
12. Player responds, goto step 3
13. After turn, Bandit updates α/β for GREET action
14. Bandit saves state to disk
```

---

## Support

For issues or questions:
- GitHub: [RFSN-ORCHESTRATOR Issues](https://github.com/dawsonblock/RFSN-ORCHESTRATOR/issues)
- Documentation: See `README.md` and `IMPLEMENTATION_SUMMARY.md`
