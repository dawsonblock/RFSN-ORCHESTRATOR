# Unity NPC Integration Specification

## Overview

This document specifies how to integrate RFSN (Roleplay Fantasy Social Network) Orchestrator with Unity game engine for dynamic NPC behavior. The integration maintains RFSN as the authoritative decision-maker while Unity handles execution and feedback.

## Architecture Principles

- **RFSN Authority**: RFSN makes all state and action decisions
- **Unity Execution**: Unity only executes actions and reports outcomes
- **Bounded Learning**: Learning is per-state, reversible, and bounded
- **Safety First**: Hard overrides can block any action in Unity

---

## Data Contracts

### 1. Observation Packet (Unity → RFSN)

Unity sensors build and send this packet to RFSN for decision-making.

```json
{
  "t": 1736962800.123,
  "npc_id": "npc_barkeep_01",
  "scene_id": "tavern_main",
  "player": {
    "distance": 2.4,
    "facing_dot": 0.92,
    "is_weapon_drawn": false,
    "last_utterance": "Any work for me?"
  },
  "world": {
    "threat_level": 0.1,
    "noise": 0.3,
    "combat_nearby": false
  },
  "flags": ["player_in_dialogue_range", "tavern_open"]
}
```

**Field Descriptions:**
- `t`: Unix timestamp (seconds since epoch)
- `npc_id`: Unique identifier for this NPC instance
- `scene_id`: Current Unity scene/location
- `player.distance`: Distance from NPC to player (Unity units)
- `player.facing_dot`: Dot product of NPC-to-player and player-forward vectors (-1 to 1)
- `player.is_weapon_drawn`: Boolean weapon state
- `player.last_utterance`: Most recent player dialogue input (text or speech-to-text)
- `world.threat_level`: Normalized threat value (0.0 = safe, 1.0 = combat)
- `world.noise`: Ambient noise level (0.0 = quiet, 1.0 = loud)
- `world.combat_nearby`: Boolean flag for nearby combat
- `flags`: Array of discrete event flags (custom per game)

### 2. Decision Output (RFSN → Unity)

RFSN returns this decision packet after processing observation.

```json
{
  "npc_id": "npc_barkeep_01",
  "state": "FRIENDLY",
  "action_id": "GREET",
  "action_intent": "Welcome the player and offer a basic option.",
  "dialogue_constraints": ["no threats", "no quest promises"],
  "facts": ["NPC is a barkeep", "Player is in the tavern"],
  "cooldowns": {"GREET": 8.0}
}
```

**Field Descriptions:**
- `npc_id`: Echo of NPC identifier
- `state`: Current RFSN state (FRIENDLY, ALERT, HOSTILE, FEARFUL, etc.)
- `action_id`: Selected action to execute
- `action_intent`: One-sentence description of what NPC is trying to achieve
- `dialogue_constraints`: List of constraints for LLM dialogue generation
- `facts`: Curated list of facts for LLM context (3-8 bullets)
- `cooldowns`: Dictionary of {action_id: seconds} for action cooldowns

### 3. Execution Report (Unity → RFSN)

Unity sends this after executing an action to report outcome.

```json
{
  "npc_id": "npc_barkeep_01",
  "action_id": "GREET",
  "executed": true,
  "outcome": {
    "player_engaged": true,
    "player_left": false,
    "combat_started": false
  }
}
```

**Field Descriptions:**
- `npc_id`: NPC identifier
- `action_id`: Action that was executed
- `executed`: Whether action completed successfully
- `outcome`: Dictionary of boolean outcome flags

### 4. Scoring Event (Unity → RFSN, Internal)

RFSN converts execution reports into reward signals for bandit learning.

**Reward Design:**
- Bounded: reward ∈ [-1.0, 1.0]
- Binary Thompson: reward > 0 = success, else failure
- Objective-aligned: measures progress toward goals, not "player liked it"

**Example Scoring:**
```python
if outcome["combat_started"]:
    reward = -1.0  # Failed to maintain peace
elif outcome["player_engaged"]:
    reward = 0.8   # Successfully engaged player
elif outcome["player_left"]:
    reward = -0.3  # Player disengaged
else:
    reward = 0.0   # Neutral outcome
```

---

## Unity Components

### Core Components

#### 1. RfsnClient.cs

HTTP/WebSocket client for communicating with RFSN Python service.

```csharp
using System;
using System.Net.Http;
using System.Threading.Tasks;
using UnityEngine;
using Newtonsoft.Json;

public class RfsnClient : MonoBehaviour
{
    [SerializeField] private string rfsnEndpoint = "http://localhost:8000";
    private HttpClient httpClient;

    void Awake()
    {
        httpClient = new HttpClient();
        httpClient.BaseAddress = new Uri(rfsnEndpoint);
    }

    public async Task<DecisionOutput> RequestDecision(ObservationPacket obs)
    {
        try
        {
            var json = JsonConvert.SerializeObject(obs);
            var content = new StringContent(json, System.Text.Encoding.UTF8, "application/json");
            
            // Set timeout
            using var cts = new System.Threading.CancellationTokenSource(TimeSpan.FromSeconds(5));
            var response = await httpClient.PostAsync("/api/decide", content, cts.Token);
            
            response.EnsureSuccessStatusCode();
            var responseJson = await response.Content.ReadAsStringAsync();
            return JsonConvert.DeserializeObject<DecisionOutput>(responseJson);
        }
        catch (TaskCanceledException)
        {
            Debug.LogError("[RFSN] Request timeout - using fallback");
            return GetFallbackDecision(obs);
        }
        catch (HttpRequestException ex)
        {
            Debug.LogError($"[RFSN] Network error: {ex.Message}");
            return GetFallbackDecision(obs);
        }
        catch (JsonException ex)
        {
            Debug.LogError($"[RFSN] JSON parse error: {ex.Message}");
            return GetFallbackDecision(obs);
        }
    }

    private DecisionOutput GetFallbackDecision(ObservationPacket obs)
    {
        // Fallback to safe idle action
        return new DecisionOutput
        {
            npc_id = obs.npc_id,
            state = "NEUTRAL",
            action_id = "IDLE",
            action_intent = "Remain calm and observant."
        };
    }

    public async Task ReportExecution(ExecutionReport report)
    {
        var json = JsonConvert.SerializeObject(report);
        var content = new StringContent(json, System.Text.Encoding.UTF8, "application/json");
        await httpClient.PostAsync("/api/report", content);
    }
}
```

#### 2. NpcSensor.cs

Builds observation packets from Unity game state.

```csharp
using UnityEngine;

public class NpcSensor : MonoBehaviour
{
    [SerializeField] private Transform player;
    [SerializeField] private string npcId;
    [SerializeField] private string sceneId;

    public ObservationPacket BuildObservation(string playerUtterance)
    {
        Vector3 toPlayer = player.position - transform.position;
        float distance = toPlayer.magnitude;
        float facingDot = Vector3.Dot(toPlayer.normalized, player.forward);

        return new ObservationPacket
        {
            t = Time.time,
            npc_id = npcId,
            scene_id = sceneId,
            player = new PlayerObservation
            {
                distance = distance,
                facing_dot = facingDot,
                is_weapon_drawn = IsPlayerWeaponDrawn(),
                last_utterance = playerUtterance
            },
            world = new WorldObservation
            {
                threat_level = CalculateThreatLevel(),
                noise = CalculateNoiseLevel(),
                combat_nearby = IsCombatNearby()
            },
            flags = GetActiveFlags()
        };
    }

    private bool IsPlayerWeaponDrawn() { /* Implementation */ }
    private float CalculateThreatLevel() { /* Implementation */ }
    private float CalculateNoiseLevel() { /* Implementation */ }
    private bool IsCombatNearby() { /* Implementation */ }
    private string[] GetActiveFlags() { /* Implementation */ }
}
```

#### 3. NpcActuator.cs

Executes actions selected by RFSN.

```csharp
using UnityEngine;

public class NpcActuator : MonoBehaviour
{
    [SerializeField] private Animator animator;
    [SerializeField] private AudioSource audioSource;
    
    public void ExecuteAction(DecisionOutput decision)
    {
        switch (decision.action_id)
        {
            case "GREET":
                animator.SetTrigger("Greet");
                break;
            case "WARN":
                animator.SetTrigger("Warn");
                break;
            case "THREATEN":
                animator.SetTrigger("Threaten");
                break;
            case "FLEE":
                StartFleeing();
                break;
            case "ATTACK":
                if (AllowCombat()) StartAttacking();
                break;
            default:
                animator.SetTrigger("Idle");
                break;
        }
    }

    private void StartFleeing() { /* NavMesh to safe point */ }
    private void StartAttacking() { /* Trigger combat controller */ }
    private bool AllowCombat() { /* Safety check */ }
}
```

#### 4. NpcDialogue.cs

Calls LLM sub-prompt to realize dialogue and plays voice.

```csharp
using System.Threading.Tasks;
using UnityEngine;

public class NpcDialogue : MonoBehaviour
{
    [SerializeField] private string llmEndpoint = "http://localhost:8000/api/realize_dialogue";
    
    public async Task<string> RealizeDialogue(DecisionOutput decision, string playerUtterance)
    {
        var prompt = BuildLLMPrompt(decision, playerUtterance);
        // Call LLM endpoint with prompt
        var response = await CallLLM(prompt);
        
        // Play TTS
        PlayVoice(response);
        
        return response;
    }

    private string BuildLLMPrompt(DecisionOutput decision, string playerUtterance)
    {
        // Use llm_subprompt_template.txt with variable substitution
        return $@"
NPC_PROFILE:
- name: {decision.npc_id}
- state: {decision.state}

RFSN_CONTEXT:
- action_id: {decision.action_id}
- action_intent: {decision.action_intent}

PLAYER_INPUT:
""{playerUtterance}""

FACTS:
{string.Join("\n", decision.facts)}
";
    }

    private async Task<string> CallLLM(string prompt) { /* HTTP call */ }
    private void PlayVoice(string text) { /* TTS playback */ }
}
```

#### 5. NpcBlackboard.asset

ScriptableObject storing NPC profile and constraints.

```csharp
using UnityEngine;

[CreateAssetMenu(fileName = "NpcBlackboard", menuName = "RFSN/NPC Blackboard")]
public class NpcBlackboard : ScriptableObject
{
    [Header("Identity")]
    public string npcName;
    public string npcRole;
    public string setting;

    [Header("Personality")]
    [TextArea(3, 5)]
    public string personalityVector;
    
    [TextArea(3, 5)]
    public string speechStyle;

    [Header("Constraints")]
    public string[] dialogueConstraints;
    public string[] bannedActions;
}
```

#### 6. NpcNav.cs (Optional)

NavMesh movement for MOVE/CHASE/FLEE actions.

```csharp
using UnityEngine;
using UnityEngine.AI;

public class NpcNav : MonoBehaviour
{
    [SerializeField] private NavMeshAgent agent;
    [SerializeField] private Transform safePoint;

    public void MoveTo(Vector3 target)
    {
        agent.SetDestination(target);
    }

    public void FleeToSafety()
    {
        if (safePoint != null)
        {
            agent.SetDestination(safePoint.position);
            agent.speed *= 1.5f; // Sprint
        }
    }

    public void StopMovement()
    {
        agent.ResetPath();
    }
}
```

---

## Action Execution Mappings

| Action ID | Unity Execution | Animation | Audio | Notes |
|-----------|----------------|-----------|-------|-------|
| `GREET` | Play greeting line + idle anim | "Greet" | Greeting voice line | Default friendly |
| `WARN` | Play warning + lean forward | "Warn" | Warning voice line | Tense stance |
| `BARGAIN` | Open dialogue UI | "Gesture" | Bargaining line | Show options |
| `THREATEN` | Play threat + aggressive pose | "Threaten" | Threat voice line | Pre-combat |
| `FLEE` | NavMesh to safe point + sprint | "Run" | Panic sounds | Use NpcNav |
| `ATTACK` | Trigger combat controller | "Attack" | Combat voice line | Safety gated |
| `HELP` | Play help offer + gesture | "Help" | Helpful line | Quest-related |
| `IGNORE` | Turn away + idle | "TurnAway" | Silent or dismissive | Low priority |
| `APOLOGIZE` | Play apology + submissive | "Apologize" | Apologetic line | Conflict resolution |
| `EXPLAIN` | Play explanation + gesture | "Explain" | Informative line | Lore/instructions |

---

## Update Loops

### Main Loop (5-10 Hz)

```
Every 100-200ms:
1. NpcSensor builds observation packet
2. RfsnClient sends to RFSN service
3. RFSN returns decision
4. NpcActuator executes action
5. RfsnClient reports execution result
```

### Animation Loop (30-60 Hz)

```
Unity's normal Update() loop:
- Smooth animation blending
- Position interpolation
- IK adjustments
```

### Dialogue Loop (Event-Driven)

```
On action change or player utterance:
1. NpcDialogue calls LLM realizer
2. LLM returns spoken text
3. TTS generates audio
4. Audio plays through AudioSource
5. Subtitle UI displays text
```

**Example Integration:**

```csharp
public class NpcController : MonoBehaviour
{
    private RfsnClient rfsnClient;
    private NpcSensor sensor;
    private NpcActuator actuator;
    private NpcDialogue dialogue;
    
    private float updateInterval = 0.2f; // 5 Hz
    private float lastUpdate = 0f;

    void Update()
    {
        if (Time.time - lastUpdate >= updateInterval)
        {
            lastUpdate = Time.time;
            UpdateNpc();
        }
    }

    async void UpdateNpc()
    {
        // 1. Build observation
        var obs = sensor.BuildObservation(GetPlayerUtterance());
        
        // 2. Request decision
        var decision = await rfsnClient.RequestDecision(obs);
        
        // 3. Execute action
        actuator.ExecuteAction(decision);
        
        // 4. Realize dialogue if needed
        if (ShouldSpeak(decision))
        {
            var line = await dialogue.RealizeDialogue(decision, obs.player.last_utterance);
        }
        
        // 5. Report execution
        var report = BuildExecutionReport(decision, obs);
        await rfsnClient.ReportExecution(report);
    }
}
```

---

## Safety Hooks

### Global Hard Stop Gate

Unity can override RFSN decisions for critical safety:

```csharp
public class SafetyGate : MonoBehaviour
{
    public bool ShouldBlock(DecisionOutput decision)
    {
        // Example: Block violence in child-safe mode
        if (IsChildSafeMode() && IsViolentAction(decision.action_id))
            return true;
            
        // Example: Block during cutscenes
        if (IsInCutscene())
            return true;
            
        return false;
    }

    public DecisionOutput ApplySafeOverride(DecisionOutput decision)
    {
        if (ShouldBlock(decision))
        {
            decision.action_id = "SAFE_IDLE";
            decision.action_intent = "Remain calm and silent.";
        }
        return decision;
    }
}
```

### Per-Action Cooldowns

Enforce cooldowns to prevent spam:

```csharp
public class CooldownManager : MonoBehaviour
{
    private Dictionary<string, float> cooldowns = new Dictionary<string, float>();

    public bool IsOnCooldown(string actionId)
    {
        if (cooldowns.TryGetValue(actionId, out float cooldownEnd))
        {
            return Time.time < cooldownEnd;
        }
        return false;
    }

    public void SetCooldown(string actionId, float duration)
    {
        cooldowns[actionId] = Time.time + duration;
    }
}
```

### Content Filtering

Filter LLM output before display:

```csharp
public class ContentFilter : MonoBehaviour
{
    private string[] bannedWords = { /* list of inappropriate words */ };

    public string FilterContent(string content)
    {
        foreach (var word in bannedWords)
        {
            if (content.Contains(word, System.StringComparison.OrdinalIgnoreCase))
            {
                return "[Content filtered]";
            }
        }
        return content;
    }
}
```

---

## Configuration Example

**RfsnConfig.asset:**

```csharp
[CreateAssetMenu(fileName = "RfsnConfig", menuName = "RFSN/Config")]
public class RfsnConfig : ScriptableObject
{
    [Header("Connection")]
    public string rfsnEndpoint = "http://localhost:8000";
    public float updateFrequency = 5.0f; // Hz
    
    [Header("Safety")]
    public bool enableSafetyGate = true;
    public bool enableContentFilter = true;
    public bool allowCombatActions = false;
    
    [Header("Performance")]
    public int maxQueuedDecisions = 3;
    public float dialogueTimeout = 5.0f;
}
```

---

## Testing Checklist

- [ ] Observation packets build correctly with all fields
- [ ] RFSN service receives and processes observations
- [ ] Decision outputs are valid and complete
- [ ] Actions execute with correct animations
- [ ] Dialogue realizes correctly via LLM
- [ ] Execution reports send successfully
- [ ] Safety gates block prohibited actions
- [ ] Cooldowns prevent action spam
- [ ] Content filter catches inappropriate content
- [ ] Performance meets target update rate (5-10 Hz)

---

## Performance Considerations

1. **Network Latency**: Async/await calls don't block main thread
2. **Animation Blending**: Use Unity's Animator state machine for smooth transitions
3. **Memory Management**: Pool observation/decision objects to reduce GC
4. **Thread Safety**: Use Unity's main thread dispatcher for UI updates

---

## Debugging

Enable verbose logging in Unity:

```csharp
public static class RfsnDebug
{
    public static bool EnableLogging = true;

    public static void Log(string message)
    {
        if (EnableLogging)
            Debug.Log($"[RFSN] {message}");
    }
}
```

View RFSN service logs:
```bash
tail -f logs/orchestrator.log
```

---

## Next Steps

1. Implement RfsnClient.cs with your networking library
2. Create NPC prefab with all required components
3. Configure NpcBlackboard.asset for each NPC type
4. Test with RFSN service running locally
5. Profile and optimize update loop frequency
6. Deploy RFSN service to cloud for production
