# AISP Message Types
# AI Intelligence Sharing Protocol

AI_TASK  = "AI_TASK"   # Dispatch an AI task to a remote node
AI_RESULT = "AI_RESULT" # Return result from remote inference
AI_KNOW  = "AI_KNOW"   # Share a knowledge update
AI_SYNC  = "AI_SYNC"   # Synchronize model weights or embeddings
AI_PROBE = "AI_PROBE"  # Discover and verify node identity

PACKET_TYPES = [AI_TASK, AI_RESULT, AI_KNOW, AI_SYNC, AI_PROBE]

SECURITY_ZONES = {
    "PUBLIC":   {"min_trust": 0.0, "allowed": [AI_PROBE]},
    "TRUSTED":  {"min_trust": 0.7, "allowed": [AI_TASK, AI_RESULT, AI_KNOW, AI_SYNC, AI_PROBE]},
    "PERSONAL": {"min_trust": 1.0, "allowed": [AI_TASK, AI_RESULT, AI_KNOW, AI_SYNC, AI_PROBE]},
    "CRITICAL": {"min_trust": 1.0, "allowed": [AI_TASK, AI_RESULT, AI_KNOW, AI_SYNC, AI_PROBE]},
}
