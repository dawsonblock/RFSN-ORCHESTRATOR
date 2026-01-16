ScriptName RFSNNPCAdapter Extends Quest
{
    RFSN NPC Orchestrator Adapter for Skyrim Special Edition
    
    Handles communication with Python orchestrator service via HTTP.
    Maps orchestrator responses to Skyrim dialogue topics, AI packages, and animations.
    
    Installation:
    1. Place Python orchestrator service on localhost (or remote server)
    2. Attach this script to a quest
    3. Configure NPCs with RFSN-enabled dialogue topics
    4. Call ProcessPlayerDialogue() from dialogue fragment
}

;==============================================
; Properties (Configure in CK)
;==============================================

String Property OrchestratorURL = "http://localhost:8000/api/npc/interact" Auto
{URL of RFSN orchestrator service}

Float Property RequestTimeout = 5.0 Auto
{Timeout for HTTP requests in seconds}

Bool Property EnableLogging = True Auto
{Enable debug logging}


;==============================================
; State Variables (Per NPC)
;==============================================

; Internal state storage (keyed by Actor FormID)
; In real implementation, use JContainers or similar JSON library

Struct NPCState
    String Mood
    Float Affinity
    String Relationship
    Float RecentSentiment
    Bool CombatActive
    Bool QuestActive
    Float TrustLevel
    Float FearLevel
EndStruct


;==============================================
; Public API
;==============================================

Function ProcessPlayerDialogue(Actor npc, String playerText)
    {
        Main entry point: Called from dialogue fragment when player speaks.
        
        Args:
            npc: The NPC actor responding to player
            playerText: What the player said (or dialogue option text)
    }
    
    ; Build input event
    String npcID = GetNPCID(npc)
    NPCState state = GetNPCState(npc)
    
    ; Construct JSON input event
    String inputJSON = BuildInputEventJSON(npcID, playerText, state, npc)
    
    ; Send HTTP POST to orchestrator
    String responseJSON = SendHTTPRequest(OrchestratorURL, inputJSON)
    
    If responseJSON != ""
        ; Parse response and execute
        HandleOrchestratorResponse(npc, responseJSON)
    Else
        ; Fallback to canned dialogue if orchestrator fails
        ShowFallbackDialogue(npc, "I'm not sure what to say.")
    EndIf
EndFunction


Function NotifyGameEvent(Actor npc, String eventType)
    {
        Notify orchestrator of game event (combat start, quest update, etc.)
        
        Args:
            npc: The NPC actor
            eventType: Event type ("combat_start", "combat_end", "quest_update")
    }
    
    String npcID = GetNPCID(npc)
    NPCState state = GetNPCState(npc)
    
    ; Construct minimal event JSON
    String eventJSON = BuildGameEventJSON(npcID, eventType, state)
    
    ; Fire and forget (no response handling needed)
    SendHTTPRequest(OrchestratorURL, eventJSON)
EndFunction


;==============================================
; HTTP Communication (Requires SKSE Plugin)
;==============================================

String Function SendHTTPRequest(String url, String jsonBody)
    {
        Send HTTP POST request with JSON body.
        Returns response JSON string or empty string on failure.
        
        NOTE: Requires SKSE plugin that provides HTTP functionality.
        Alternatives:
        - Use SkyUI's HTTP wrapper (if available)
        - Use external process via batch file + file polling
        - Use named pipes for IPC with local Python process
    }
    
    ; Pseudocode - actual implementation depends on SKSE plugin
    
    ; Create request object
    Int requestHandle = HTTPUtil.CreateRequest(url)
    HTTPUtil.SetRequestMethod(requestHandle, "POST")
    HTTPUtil.SetRequestHeader(requestHandle, "Content-Type", "application/json")
    HTTPUtil.SetRequestBody(requestHandle, jsonBody)
    HTTPUtil.SetRequestTimeout(requestHandle, RequestTimeout)
    
    ; Send synchronous request (blocks until response or timeout)
    ; In production, use async with callback
    Bool success = HTTPUtil.Send(requestHandle)
    
    If success
        String response = HTTPUtil.GetResponseBody(requestHandle)
        HTTPUtil.DestroyRequest(requestHandle)
        Return response
    Else
        If EnableLogging
            Debug.Trace("RFSN: HTTP request failed: " + HTTPUtil.GetError(requestHandle))
        EndIf
        HTTPUtil.DestroyRequest(requestHandle)
        Return ""
    EndIf
EndFunction


;==============================================
; JSON Construction
;==============================================

String Function BuildInputEventJSON(String npcID, String playerText, NPCState state, Actor npc)
    {
        Build input event JSON for orchestrator.
        Uses JContainers (or similar) for JSON serialization.
    }
    
    ; Create JMap for input event
    Int eventMap = JMap.Object()
    
    JMap.SetStr(eventMap, "event_type", "player_input")
    JMap.SetStr(eventMap, "npc_id", npcID)
    JMap.SetStr(eventMap, "player_text", playerText)
    JMap.SetInt(eventMap, "timestamp", Utility.GetCurrentGameTime() as Int)
    
    ; Add context
    Int contextMap = JMap.Object()
    JMap.SetStr(contextMap, "location", npc.GetCurrentLocation().GetName())
    JMap.SetInt(contextMap, "player_level", Game.GetPlayer().GetLevel())
    JMap.SetStr(contextMap, "time_of_day", GetTimeOfDay())
    JMap.SetFlt(contextMap, "player_distance", npc.GetDistance(Game.GetPlayer()))
    JMap.SetObj(eventMap, "context", contextMap)
    
    ; Serialize to JSON string
    String json = JValue.SolveStr(eventMap, "")
    JValue.Release(eventMap)
    
    Return json
EndFunction


String Function BuildGameEventJSON(String npcID, String eventType, NPCState state)
    {Build game event JSON (simplified)}
    
    Int eventMap = JMap.Object()
    JMap.SetStr(eventMap, "event_type", eventType)
    JMap.SetStr(eventMap, "npc_id", npcID)
    JMap.SetInt(eventMap, "timestamp", Utility.GetCurrentGameTime() as Int)
    
    String json = JValue.SolveStr(eventMap, "")
    JValue.Release(eventMap)
    
    Return json
EndFunction


;==============================================
; Response Handling
;==============================================

Function HandleOrchestratorResponse(Actor npc, String responseJSON)
    {
        Parse orchestrator response and execute in-game actions.
        
        Response structure:
        {
            "event_type": "dialogue",
            "npc_id": "...",
            "action": "accept",
            "dialogue_text": "Of course, I'll help you.",
            "animation_trigger": "Accept_Nod",
            "audio_file": "tts/npc_12345.wav",
            "state_after": { ... }
        }
    }
    
    ; Parse JSON using JContainers
    Int responseMap = JValue.ObjectFromString(responseJSON)
    
    If responseMap == 0
        If EnableLogging
            Debug.Trace("RFSN: Failed to parse response JSON")
        EndIf
        Return
    EndIf
    
    ; Extract fields
    String action = JMap.GetStr(responseMap, "action")
    String dialogueText = JMap.GetStr(responseMap, "dialogue_text")
    String animationTrigger = JMap.GetStr(responseMap, "animation_trigger")
    String audioFile = JMap.GetStr(responseMap, "audio_file")
    Int stateAfter = JMap.GetObj(responseMap, "state_after")
    
    ; Update NPC state
    If stateAfter != 0
        UpdateNPCState(npc, stateAfter)
    EndIf
    
    ; Play animation
    If animationTrigger != ""
        PlayNPCAnimation(npc, animationTrigger)
    EndIf
    
    ; Show dialogue
    If dialogueText != ""
        ShowNPCDialogue(npc, dialogueText, audioFile)
    EndIf
    
    ; Log action
    If EnableLogging
        Debug.Trace("RFSN: NPC " + GetNPCID(npc) + " performed action: " + action)
    EndIf
    
    JValue.Release(responseMap)
EndFunction


;==============================================
; Animation Mapping
;==============================================

Function PlayNPCAnimation(Actor npc, String animationTrigger)
    {
        Map animation trigger to Skyrim animation events.
        Uses Debug.SendAnimationEvent() or custom animation graph.
    }
    
    ; Map RFSN animation triggers to Skyrim animation events
    ; These are examples - adjust based on your animation setup
    
    If animationTrigger == "Greet_Wave"
        Debug.SendAnimationEvent(npc, "IdleWave")
    ElseIf animationTrigger == "Farewell_Wave"
        Debug.SendAnimationEvent(npc, "IdleWave")
    ElseIf animationTrigger == "Accept_Nod"
        Debug.SendAnimationEvent(npc, "IdleNod")
    ElseIf animationTrigger == "Refuse_Shake"
        Debug.SendAnimationEvent(npc, "IdleShakeHead")
    ElseIf animationTrigger == "Threaten_Point"
        Debug.SendAnimationEvent(npc, "IdlePoint")
    ElseIf animationTrigger == "Attack_Draw"
        npc.DrawWeapon()
    ElseIf animationTrigger == "Defend_Block"
        ; Trigger defensive idle
        Debug.SendAnimationEvent(npc, "BlockStart")
    ElseIf animationTrigger == "Flee_Run"
        ; Apply flee package (handled in AI package system)
        npc.StartCombat(Game.GetPlayer())  ; Or apply flee package
    ElseIf animationTrigger == "Explain_Gesture"
        Debug.SendAnimationEvent(npc, "IdleGesture01")
    Else
        ; Default talking animation
        Debug.SendAnimationEvent(npc, "IdleDialogueExpressive")
    EndIf
EndFunction


;==============================================
; Dialogue Integration
;==============================================

Function ShowNPCDialogue(Actor npc, String text, String audioFile)
    {
        Display NPC dialogue in Skyrim's dialogue UI.
        
        Options:
        1. Use custom dialogue topic with dynamic text injection
        2. Use subtitle system
        3. Use notification system (for testing)
    }
    
    ; Option 1: Dynamic dialogue topic (requires custom topic setup)
    ; Topic RFSNDynamicResponse has dialogue info with script fragment
    ; that reads from global storage
    
    ; Store dialogue text in global storage (JContainers)
    JDB.SolveStrSetter(".rfsn.lastDialogueText." + GetNPCID(npc), text, True)
    JDB.SolveStrSetter(".rfsn.lastAudioFile." + GetNPCID(npc), audioFile, True)
    
    ; Force the NPC to say the dynamic topic
    ; (Topic must have "Random" flag unchecked and be set to "Say Once")
    Topic dynamicTopic = Game.GetFormFromFile(0x00001234, "RFSNOrchestrator.esp") as Topic
    npc.Say(dynamicTopic)
    
    ; Option 2: Subtitle system (no voice)
    ; Debug.MessageBox(npc.GetDisplayName() + ": " + text)
    
    ; Option 3: Play custom voice audio if available
    ; Requires xVASynth integration or pre-recorded voice files
    If audioFile != ""
        PlayVoiceAudio(npc, audioFile)
    EndIf
EndFunction


Function PlayVoiceAudio(Actor npc, String audioFile)
    {
        Play TTS-generated voice audio for NPC.
        
        Requires:
        - Audio files in Data/Sound/Voice/RFSNOrchestrator.esp/
        - Sound descriptor forms created in CK
        - Or dynamic audio loading via SKSE plugin
    }
    
    ; Pseudocode - requires custom audio loading
    ; In practice, you'd either:
    ; 1. Pre-generate all possible audio and reference as Sound forms
    ; 2. Use SKSE plugin to load .wav files dynamically
    ; 3. Use xVASynth or similar in-game TTS system
    
    ; Example: Play sound from file
    ; Sound audioForm = LoadSoundFromFile(audioFile)
    ; Int soundInstance = audioForm.Play(npc)
EndFunction


;==============================================
; State Management
;==============================================

NPCState Function GetNPCState(Actor npc)
    {Retrieve NPC state from persistent storage}
    
    String npcID = GetNPCID(npc)
    
    ; Load from JContainers persistent storage
    String stateKey = ".rfsn.state." + npcID
    Int stateMap = JDB.SolveObj(stateKey)
    
    If stateMap == 0
        ; Initialize default state
        NPCState state = CreateDefaultState()
        SaveNPCState(npc, state)
        Return state
    EndIf
    
    ; Parse state from JMap
    NPCState state = new NPCState
    state.Mood = JMap.GetStr(stateMap, "mood", "neutral")
    state.Affinity = JMap.GetFlt(stateMap, "affinity", 0.0)
    state.Relationship = JMap.GetStr(stateMap, "relationship", "stranger")
    state.RecentSentiment = JMap.GetFlt(stateMap, "recent_sentiment", 0.0)
    state.CombatActive = JMap.GetInt(stateMap, "combat_active", 0) as Bool
    state.QuestActive = JMap.GetInt(stateMap, "quest_active", 0) as Bool
    state.TrustLevel = JMap.GetFlt(stateMap, "trust_level", 0.5)
    state.FearLevel = JMap.GetFlt(stateMap, "fear_level", 0.0)
    
    Return state
EndFunction


Function SaveNPCState(Actor npc, NPCState state)
    {Save NPC state to persistent storage}
    
    String npcID = GetNPCID(npc)
    String stateKey = ".rfsn.state." + npcID
    
    Int stateMap = JMap.Object()
    JMap.SetStr(stateMap, "mood", state.Mood)
    JMap.SetFlt(stateMap, "affinity", state.Affinity)
    JMap.SetStr(stateMap, "relationship", state.Relationship)
    JMap.SetFlt(stateMap, "recent_sentiment", state.RecentSentiment)
    JMap.SetInt(stateMap, "combat_active", state.CombatActive as Int)
    JMap.SetInt(stateMap, "quest_active", state.QuestActive as Int)
    JMap.SetFlt(stateMap, "trust_level", state.TrustLevel)
    JMap.SetFlt(stateMap, "fear_level", state.FearLevel)
    
    JDB.SolveObjSetter(stateKey, stateMap, True)
EndFunction


Function UpdateNPCState(Actor npc, Int stateAfterMap)
    {Update NPC state from orchestrator response}
    
    NPCState state = new NPCState
    state.Mood = JMap.GetStr(stateAfterMap, "mood")
    state.Affinity = JMap.GetFlt(stateAfterMap, "affinity")
    state.Relationship = JMap.GetStr(stateAfterMap, "relationship")
    state.RecentSentiment = JMap.GetFlt(stateAfterMap, "recent_sentiment")
    state.CombatActive = JMap.GetInt(stateAfterMap, "combat_active") as Bool
    state.QuestActive = JMap.GetInt(stateAfterMap, "quest_active") as Bool
    state.TrustLevel = JMap.GetFlt(stateAfterMap, "trust_level")
    state.FearLevel = JMap.GetFlt(stateAfterMap, "fear_level")
    
    SaveNPCState(npc, state)
    
    ; Update Skyrim relationship rank based on affinity
    UpdateSkyrimRelationship(npc, state.Affinity)
EndFunction


Function UpdateSkyrimRelationship(Actor npc, Float affinity)
    {Map RFSN affinity to Skyrim relationship rank}
    
    ; Skyrim relationship ranks: -4 (Arch Nemesis) to 4 (Lover)
    Int rank = 0
    
    If affinity <= -0.8
        rank = -4  ; Arch Nemesis
    ElseIf affinity <= -0.5
        rank = -3  ; Enemy
    ElseIf affinity <= -0.2
        rank = -2  ; Foe
    ElseIf affinity < 0.2
        rank = 0   ; Acquaintance
    ElseIf affinity < 0.5
        rank = 1   ; Friend
    ElseIf affinity < 0.8
        rank = 2   ; Confidant
    Else
        rank = 3   ; Ally (or 4 for Lover if appropriate)
    EndIf
    
    npc.SetRelationshipRank(Game.GetPlayer(), rank)
EndFunction


;==============================================
; Utility Functions
;==============================================

String Function GetNPCID(Actor npc)
    {Generate unique NPC identifier}
    Return npc.GetBaseObject().GetFormID() as String
EndFunction


String Function GetTimeOfDay()
    {Get time of day string (day/night)}
    Float currentTime = Utility.GetCurrentGameTime()
    Float hour = (currentTime - (currentTime as Int)) * 24.0
    
    If hour >= 6.0 && hour < 18.0
        Return "day"
    Else
        Return "night"
    EndIf
EndFunction


NPCState Function CreateDefaultState()
    {Create default NPC state for new NPCs}
    NPCState state = new NPCState
    state.Mood = "neutral"
    state.Affinity = 0.0
    state.Relationship = "stranger"
    state.RecentSentiment = 0.0
    state.CombatActive = False
    state.QuestActive = False
    state.TrustLevel = 0.5
    state.FearLevel = 0.0
    Return state
EndFunction


Function ShowFallbackDialogue(Actor npc, String text)
    {Show fallback dialogue when orchestrator is unavailable}
    Debug.Notification(npc.GetDisplayName() + ": " + text)
EndFunction


;==============================================
; Event Handlers (Register in OnInit)
;==============================================

Event OnInit()
    RegisterForModEvent("RFSN_ProcessDialogue", "OnProcessDialogue")
    RegisterForModEvent("RFSN_CombatStart", "OnCombatStart")
    RegisterForModEvent("RFSN_CombatEnd", "OnCombatEnd")
EndEvent


Event OnProcessDialogue(String eventName, String strArg, Float numArg, Form sender)
    {Mod event handler for dialogue processing}
    Actor npc = sender as Actor
    If npc
        ProcessPlayerDialogue(npc, strArg)
    EndIf
EndEvent


Event OnCombatStart(String eventName, String strArg, Float numArg, Form sender)
    {Mod event handler for combat start}
    Actor npc = sender as Actor
    If npc
        NotifyGameEvent(npc, "combat_start")
    EndIf
EndEvent


Event OnCombatEnd(String eventName, String strArg, Float numArg, Form sender)
    {Mod event handler for combat end}
    Actor npc = sender as Actor
    If npc
        NotifyGameEvent(npc, "combat_end")
    EndIf
EndEvent
