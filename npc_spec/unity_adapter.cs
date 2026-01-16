using System;
using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Networking;
using Newtonsoft.Json;

namespace RFSN.NPC
{
    /// <summary>
    /// Unity adapter for RFSN NPC Orchestrator.
    /// Handles communication with Python orchestrator service and maps events to Unity systems.
    /// </summary>
    public class RFSNNPCAdapter : MonoBehaviour
    {
        #region Configuration
        
        [Header("Orchestrator Connection")]
        [SerializeField] private string orchestratorUrl = "http://localhost:8000";
        [SerializeField] private float requestTimeout = 5f;
        
        [Header("NPC Configuration")]
        [SerializeField] private string npcId = "npc_001";
        [SerializeField] private Animator animator;
        [SerializeField] private AudioSource audioSource;
        
        #endregion
        
        #region Data Transfer Objects (DTOs)
        
        [Serializable]
        public class InputEvent
        {
            public string event_type;
            public string npc_id;
            public string player_text;
            public Dictionary<string, object> context;
            public long timestamp;
        }
        
        [Serializable]
        public class OutputEvent
        {
            public string event_type;
            public string npc_id;
            public string action;
            public string dialogue_text;
            public string animation_trigger;
            public string audio_file;
            public StateVariables state_after;
            public Dictionary<string, object> metadata;
        }
        
        [Serializable]
        public class StateVariables
        {
            public string mood;
            public float affinity;
            public string relationship;
            public float recent_sentiment;
            public bool combat_active;
            public bool quest_active;
            public float trust_level;
            public float fear_level;
        }
        
        #endregion
        
        #region State Management
        
        private StateVariables currentState;
        
        void Start()
        {
            // Initialize default state
            currentState = new StateVariables
            {
                mood = "neutral",
                affinity = 0.0f,
                relationship = "stranger",
                recent_sentiment = 0.0f,
                combat_active = false,
                quest_active = false,
                trust_level = 0.5f,
                fear_level = 0.0f
            };
        }
        
        #endregion
        
        #region Public API
        
        /// <summary>
        /// Process player dialogue input and get NPC response.
        /// </summary>
        /// <param name="playerText">What the player said</param>
        /// <param name="callback">Callback with NPC response</param>
        public void ProcessPlayerInput(string playerText, Action<OutputEvent> callback)
        {
            var inputEvent = new InputEvent
            {
                event_type = "player_input",
                npc_id = npcId,
                player_text = playerText,
                context = BuildContext(),
                timestamp = DateTimeOffset.UtcNow.ToUnixTimeSeconds()
            };
            
            StartCoroutine(SendEventToOrchestrator(inputEvent, callback));
        }
        
        /// <summary>
        /// Notify orchestrator of game event (combat start/end, quest update, etc.)
        /// </summary>
        public void NotifyGameEvent(string eventType, Dictionary<string, object> eventData = null)
        {
            var inputEvent = new InputEvent
            {
                event_type = eventType,
                npc_id = npcId,
                player_text = null,
                context = eventData ?? new Dictionary<string, object>(),
                timestamp = DateTimeOffset.UtcNow.ToUnixTimeSeconds()
            };
            
            StartCoroutine(SendEventToOrchestrator(inputEvent, null));
        }
        
        #endregion
        
        #region Orchestrator Communication
        
        private IEnumerator SendEventToOrchestrator(InputEvent input, Action<OutputEvent> callback)
        {
            string json = JsonConvert.SerializeObject(input);
            byte[] bodyRaw = System.Text.Encoding.UTF8.GetBytes(json);
            
            using (UnityWebRequest request = new UnityWebRequest($"{orchestratorUrl}/api/npc/interact", "POST"))
            {
                request.uploadHandler = new UploadHandlerRaw(bodyRaw);
                request.downloadHandler = new DownloadHandlerBuffer();
                request.SetRequestHeader("Content-Type", "application/json");
                request.timeout = (int)requestTimeout;
                
                yield return request.SendWebRequest();
                
                if (request.result == UnityWebRequest.Result.Success)
                {
                    try
                    {
                        OutputEvent output = JsonConvert.DeserializeObject<OutputEvent>(request.downloadHandler.text);
                        HandleOrchestratorResponse(output);
                        callback?.Invoke(output);
                    }
                    catch (Exception e)
                    {
                        Debug.LogError($"Failed to parse orchestrator response: {e.Message}");
                    }
                }
                else
                {
                    Debug.LogError($"Orchestrator request failed: {request.error}");
                }
            }
        }
        
        #endregion
        
        #region Response Handling
        
        private void HandleOrchestratorResponse(OutputEvent output)
        {
            // Update NPC state
            if (output.state_after != null)
            {
                currentState = output.state_after;
            }
            
            // Trigger animation
            if (!string.IsNullOrEmpty(output.animation_trigger) && animator != null)
            {
                TriggerAnimation(output.animation_trigger);
            }
            
            // Play audio
            if (!string.IsNullOrEmpty(output.audio_file) && audioSource != null)
            {
                StartCoroutine(PlayAudioFile(output.audio_file));
            }
            
            // Display dialogue (integrate with your dialogue UI system)
            if (!string.IsNullOrEmpty(output.dialogue_text))
            {
                DisplayDialogue(output.dialogue_text);
            }
            
            // Log metadata
            Debug.Log($"NPC {output.npc_id} performed action: {output.action}");
            if (output.metadata != null && output.metadata.ContainsKey("latency_ms"))
            {
                Debug.Log($"Orchestrator latency: {output.metadata["latency_ms"]}ms");
            }
        }
        
        #endregion
        
        #region Animation Mapping
        
        /// <summary>
        /// Map NPCAction to Unity animation triggers.
        /// Customize this based on your animation controller.
        /// </summary>
        private void TriggerAnimation(string animationTrigger)
        {
            if (animator == null) return;
            
            // Example animation mappings
            switch (animationTrigger)
            {
                case "Greet_Wave":
                    animator.SetTrigger("Wave");
                    break;
                case "Farewell_Wave":
                    animator.SetTrigger("Wave");
                    break;
                case "Accept_Nod":
                    animator.SetTrigger("Nod");
                    break;
                case "Refuse_Shake":
                    animator.SetTrigger("ShakeHead");
                    break;
                case "Threaten_Point":
                    animator.SetTrigger("Point");
                    break;
                case "Attack_Draw":
                    animator.SetTrigger("DrawWeapon");
                    break;
                case "Defend_Block":
                    animator.SetTrigger("Block");
                    break;
                case "Flee_Run":
                    animator.SetTrigger("Run");
                    break;
                case "Explain_Gesture":
                    animator.SetTrigger("Gesture");
                    break;
                default:
                    // Generic talk animation
                    animator.SetTrigger("Talk");
                    break;
            }
        }
        
        /// <summary>
        /// Static mapping from NPCAction enum values to animation triggers.
        /// </summary>
        public static Dictionary<string, string> GetDefaultAnimationMapping()
        {
            return new Dictionary<string, string>
            {
                { "greet", "Greet_Wave" },
                { "farewell", "Farewell_Wave" },
                { "agree", "Accept_Nod" },
                { "disagree", "Refuse_Shake" },
                { "apologize", "Apologize_Bow" },
                { "insult", "Insult_Dismissive" },
                { "compliment", "Compliment_Smile" },
                { "threaten", "Threaten_Point" },
                { "request", "Request_Gesture" },
                { "offer", "Offer_HandOut" },
                { "refuse", "Refuse_Shake" },
                { "accept", "Accept_Nod" },
                { "attack", "Attack_Draw" },
                { "defend", "Defend_Block" },
                { "flee", "Flee_Run" },
                { "help", "Help_Gesture" },
                { "betray", "Betray_Sinister" },
                { "ignore", "Ignore_TurnAway" },
                { "inquire", "Inquire_Curious" },
                { "explain", "Explain_Gesture" }
            };
        }
        
        #endregion
        
        #region Audio Playback
        
        private IEnumerator PlayAudioFile(string audioFilePath)
        {
            // If orchestrator provides full URL
            if (audioFilePath.StartsWith("http"))
            {
                using (UnityWebRequest www = UnityWebRequestMultimedia.GetAudioClip(audioFilePath, AudioType.WAV))
                {
                    yield return www.SendWebRequest();
                    
                    if (www.result == UnityWebRequest.Result.Success)
                    {
                        AudioClip clip = DownloadHandlerAudioClip.GetContent(www);
                        audioSource.clip = clip;
                        audioSource.Play();
                    }
                    else
                    {
                        Debug.LogError($"Failed to load audio: {www.error}");
                    }
                }
            }
            // If orchestrator provides local path (pre-generated TTS)
            else
            {
                // Load from Resources or StreamingAssets
                // Implementation depends on your project structure
                Debug.LogWarning("Local audio file loading not implemented");
            }
        }
        
        #endregion
        
        #region UI Integration
        
        private void DisplayDialogue(string text)
        {
            // Integrate with your dialogue UI system
            // Example: DialogueManager.Instance.ShowNPCDialogue(npcId, text);
            Debug.Log($"[{npcId}]: {text}");
        }
        
        #endregion
        
        #region Context Building
        
        private Dictionary<string, object> BuildContext()
        {
            // Build context dictionary with game state information
            var context = new Dictionary<string, object>
            {
                { "location", GetCurrentLocation() },
                { "nearby_npcs", GetNearbyNPCs() },
                { "player_level", GetPlayerLevel() },
                { "time_of_day", GetTimeOfDay() },
                { "current_state", currentState }
            };
            
            return context;
        }
        
        private string GetCurrentLocation()
        {
            // Return current scene or location identifier
            return UnityEngine.SceneManagement.SceneManager.GetActiveScene().name;
        }
        
        private List<string> GetNearbyNPCs()
        {
            // Find nearby NPCs (implement based on your NPC system)
            return new List<string>();
        }
        
        private int GetPlayerLevel()
        {
            // Get player level from game state
            return 1; // Placeholder
        }
        
        private string GetTimeOfDay()
        {
            // Get time of day from game state
            return "day"; // Placeholder
        }
        
        #endregion
        
        #region Save/Load
        
        [Serializable]
        public class NPCSaveData
        {
            public string npc_id;
            public StateVariables state;
            public List<MemoryEntry> memory;
        }
        
        [Serializable]
        public class MemoryEntry
        {
            public long timestamp;
            public string player_signal;
            public string npc_action;
            public string outcome;
        }
        
        public NPCSaveData GetSaveData()
        {
            return new NPCSaveData
            {
                npc_id = npcId,
                state = currentState,
                memory = new List<MemoryEntry>() // Populate with actual memory if tracked
            };
        }
        
        public void LoadSaveData(NPCSaveData data)
        {
            npcId = data.npc_id;
            currentState = data.state;
            // Restore memory if needed
        }
        
        #endregion
    }
}
