# RFSN NPC Runtime Loop

## Overview

This document describes the authoritative tick loop for RFSN-controlled NPCs. This loop enforces bounded state transitions and ensures that LLM outputs are constrained within safe, game-appropriate bounds.

## Architecture Principles

1. **Bounded State Machine**: All state variables have explicit min/max bounds
2. **Authoritative Transitions**: State changes are determined by rule-based logic, not LLM output
3. **LLM as Realizer**: LLM generates dialogue text only, not actions or state changes
4. **Learning Layer**: Bandit learner optimizes action selection based on player engagement
5. **Streaming Response**: Dialogue is streamed token-by-token for low-latency experience

## The Authoritative Tick

### Phase 1: Input Event Reception

**Inputs:**
- `InputEvent` from game engine (see schema.json)
- Current `StateSnapshot` of NPC

**Processing:**
1. Validate input event structure
2. Extract player text (if player_input event)
3. Classify player text into `PlayerSignal` using regex-based classifier
4. Log input event to telemetry

**Output:**
- `PlayerSignal` enum value
- Validated context

---

### Phase 2: Candidate Action Generation

**Inputs:**
- Current `StateSnapshot`
- Classified `PlayerSignal`

**Processing:**
1. `ActionScorer.propose_candidates()` generates 8-12 candidate actions
   - Uses hard-coded rules based on state and signal
   - Example: If combat_active=true, only combat actions are candidates
2. `ActionScorer.score_action()` scores each candidate
   - Utility score (how well does action match state/signal)
   - Risk score (potential negative consequences)
   - Personality weights (from NPC profile)
3. Select top K=4 candidates for bandit selection

**Output:**
- List of 4 candidate `NPCAction` values
- Score per candidate

---

### Phase 3: Bandit Action Selection

**Inputs:**
- Top-K candidate actions
- Bandit context key (state bucket: mood|relationship|affinity_band|signal|combat|quest)
- Action scores as priors

**Processing:**
1. `BanditCore.select()` chooses one action from candidates
   - Thompson Sampling (or Softmax/UCB1 depending on config)
   - Blends scorer priors with learned preferences
   - Exploration bias for under-explored state-action pairs
2. Log bandit decision (key, candidates, priors, chosen action)

**Output:**
- Selected `NPCAction`

---

### Phase 4: LLM Dialogue Realization

**Inputs:**
- Selected `NPCAction`
- Current `StateSnapshot`
- `PlayerSignal`
- NPC profile (name, personality, backstory)

**Processing:**
1. Build system prompt with NPC profile
2. Build action sub-prompt using `build_action_subprompt()`
   - Machine-readable header: ACTION, MODE, SAFETY, STATE_SUMMARY
   - Action-specific constraints: INTENT, ALLOWED, FORBIDDEN
   - Style constraints: name, mood, relationship, affinity
3. Add current conversation context
4. Stream LLM generation with:
   - Token-by-token emission
   - Sentence segmentation (smart abbreviation handling)
   - Intent gate filtering (blocks meta-commentary)
   - TTS queueing (optional)
5. Collect full response text

**Output:**
- Dialogue text (1-3 sentences)
- Streaming tokens (for real-time display)
- Optional TTS audio files

---

### Phase 5: Authoritative State Transition

**Inputs:**
- Current `StateSnapshot`
- Selected `NPCAction`
- `PlayerSignal`
- Transition rules (from state_machine.py)

**Processing:**
1. Look up transition rule for (action, signal) pair
2. Apply bounded deltas:
   - `affinity += affinity_delta` (clamped to [-1.0, 1.0])
   - `trust_level += trust_delta` (clamped to [0.0, 1.0])
   - `fear_level += fear_delta` (clamped to [0.0, 1.0])
3. Apply mood transition (if specified in rule)
4. Apply relationship tier change (if affinity crosses threshold)
5. Validate state after transition
6. Log state transition (before, after, deltas)

**Output:**
- `StateSnapshot` after transition

---

### Phase 6: Output Event Emission

**Inputs:**
- Selected `NPCAction`
- Dialogue text
- State after transition
- Animation mapping (from NPC profile)
- Audio file path (if TTS generated)

**Processing:**
1. Build `OutputEvent` structure:
   - event_type = "dialogue"
   - npc_id
   - action (selected NPCAction)
   - dialogue_text
   - animation_trigger (mapped from action)
   - audio_file (TTS output path)
   - state_after (new state snapshot)
   - metadata (confidence, latency, bandit_key)
2. Serialize to JSON
3. Send to game engine via HTTP response or message queue

**Output:**
- `OutputEvent` JSON

---

### Phase 7: Learning Update

**Inputs:**
- Bandit context key
- Selected `NPCAction`
- Reward signal

**Processing:**
1. Compute reward in [0, 1]:
   - Base: sigmoid(action_score.total_score)
   - Positive evidence: +0.15 if conversation continued
   - Negative evidence: -0.4 if output blocked or empty
   - Clamp to [0, 1]
2. Update bandit: `BanditCore.update(key, action, reward)`
3. Persist bandit state (every update or every N updates)
4. Log learning event (key, action, reward, arm statistics)

**Output:**
- Updated bandit state (persisted to disk)

---

### Phase 8: Persistence

**Inputs:**
- NPC ID
- State after transition
- Conversation history (last N turns)
- Bandit state (optional)

**Processing:**
1. Build `SaveBlob` structure (see schema.json)
2. Write to game save file or database
3. Atomic write pattern (write to .tmp, then replace)

**Output:**
- Persisted NPC state

---

## Timing and Performance

**Target Latencies (from input to first token):**
- Cold start: < 500ms
- Warm (cached model): < 150ms

**Target Throughput:**
- 30+ tokens/second on consumer GPU
- 10+ tokens/second on CPU

**Bottleneck Analysis:**
1. LLM inference: 80-90% of latency
2. Action scoring: 5-10%
3. Everything else: < 5%

**Optimization Strategies:**
- Keep model loaded in memory
- Use quantized models (Q4_K_M or Q5_K_M)
- Batch multiple NPCs if possible
- Cache common prompts

---

## Error Handling

**Input Validation Failures:**
- Log warning
- Return safe fallback action (e.g., IGNORE or GREET)
- Do not crash

**LLM Generation Failures:**
- Retry once with same prompt
- If still fails, return canned dialogue for action
- Log error with full context

**State Transition Violations:**
- Clamp to valid bounds
- Log error (indicates bug in transition rules)
- Continue execution

**Bandit Update Failures:**
- Log error
- Continue without learning (better than crash)

---

## Determinism and Reproducibility

**For Testing/Debugging:**
1. Set bandit seed: `BanditCore(seed=42)`
2. Set LLM seed: `temperature=0.0` or fixed seed
3. Record input events and state snapshots
4. Replay inputs to reproduce exact behavior

**For Production:**
1. Use `temperature > 0` for varied dialogue
2. Use stochastic bandit selection
3. Log all decisions for post-hoc analysis

---

## Integration Checklist

**Game Engine Must Provide:**
- [ ] Send `InputEvent` JSON on player interaction
- [ ] Receive `OutputEvent` JSON and parse
- [ ] Map `animation_trigger` to animation controller
- [ ] Play audio_file through audio system
- [ ] Update NPC state_after in game state
- [ ] Persist `SaveBlob` on game save

**Orchestrator Must Provide:**
- [ ] HTTP endpoint or message queue for events
- [ ] Streaming response support (SSE or WebSocket)
- [ ] TTS generation (optional but recommended)
- [ ] Bandit state persistence
- [ ] Logging and telemetry

**Monitoring and Observability:**
- [ ] Log every tick (input → output)
- [ ] Track latencies (per phase)
- [ ] Track bandit statistics (exploration rate, top actions)
- [ ] Track LLM statistics (tokens/sec, cache hit rate)
- [ ] Alert on errors or anomalies

---

## Example: Full Tick Execution

**Input:**
```json
{
  "event_type": "player_input",
  "npc_id": "lydia_001",
  "player_text": "I need your help with this quest.",
  "context": {"location": "dragonsreach", "quest_id": "MQ104"},
  "timestamp": 1705456789
}
```

**Phase 1: Classify Signal**
- Player text: "I need your help with this quest."
- Classified signal: `REQUEST`

**Phase 2: Generate Candidates**
- State: mood=friendly, affinity=0.6, relationship=ally
- Signal: REQUEST
- Candidates: ACCEPT (score 8.5), HELP (7.2), AGREE (6.8), INQUIRE (5.1)

**Phase 3: Select Action**
- Bandit key: "friendly|ally|pos|request|no_combat|quest"
- Priors: {ACCEPT: 8.5, HELP: 7.2, AGREE: 6.8, INQUIRE: 5.1}
- Thompson sample: ACCEPT (sample=0.87, prior_bump=0.04, score=0.91)

**Phase 4: Generate Dialogue**
- Action: ACCEPT
- Sub-prompt: [ACTION=accept, MODE=quest, SAFETY=LOW_RISK, ...]
- LLM output: "I'll stand by your side. What do you need me to do?"

**Phase 5: Transition State**
- Rule: (ACCEPT, REQUEST) → affinity +0.05, trust +0.05
- State after: affinity=0.65, trust_level=0.80, mood=friendly

**Phase 6: Emit Output**
```json
{
  "event_type": "dialogue",
  "npc_id": "lydia_001",
  "action": "accept",
  "dialogue_text": "I'll stand by your side. What do you need me to do?",
  "animation_trigger": "Accept_Nod",
  "audio_file": "tts/lydia_001_56789.wav",
  "state_after": { "affinity": 0.65, "trust_level": 0.80, ... }
}
```

**Phase 7: Update Bandit**
- Reward: sigmoid(8.5) + 0.15 = 1.0 (clamped)
- Update: key="...", action=ACCEPT, reward=1.0
- Arm stats: alpha=12.5, beta=3.2, n=11

**Phase 8: Persist**
- Write SaveBlob to game save file

---

## Future Enhancements

**Short-term:**
- Multi-NPC conversations (group dynamics)
- Player emotion detection (from voice tone)
- Dynamic personality traits (NPCs change over time)

**Long-term:**
- Full MPC planner (predict N steps ahead)
- Hierarchical bandits (meta-strategies)
- Cross-NPC learning (transfer knowledge)
