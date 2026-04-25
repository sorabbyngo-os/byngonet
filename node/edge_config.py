"""
Byngonet — Node Tier Configurations
Defines capabilities and limits per hardware tier.
"""
from protocol.message_types import AI_TASK, AI_RESULT, AI_KNOW, AI_SYNC, AI_PROBE

TIER_CONFIGS = {
    # T1 — Server class (x86_64)
    "T1_X86": {
        "description":          "Server — x86_64",
        "max_concurrent_tasks": 8,
        "model_tier":           3,
        "allowed_types":        [AI_TASK, AI_RESULT, AI_KNOW, AI_SYNC, AI_PROBE],
        "offline_queue_size":   1000,
        "heartbeat_interval":   30,
        "default_zone":         "TRUSTED",
    },
    # T1 — ARM64 server (hospital server, Pi cluster)
    "T1_ARM64": {
        "description":          "ARM64 Server",
        "max_concurrent_tasks": 4,
        "model_tier":           2,
        "allowed_types":        [AI_TASK, AI_RESULT, AI_KNOW, AI_SYNC, AI_PROBE],
        "offline_queue_size":   500,
        "heartbeat_interval":   30,
        "default_zone":         "TRUSTED",
    },
    # T2 — SBC / Gateway (Raspberry Pi 4, ward gateway)
    "T2_ARM64": {
        "description":          "SBC / Gateway — ARM64",
        "max_concurrent_tasks": 2,
        "model_tier":           1,
        "allowed_types":        [AI_TASK, AI_RESULT, AI_KNOW, AI_PROBE],
        "offline_queue_size":   200,
        "heartbeat_interval":   60,
        "default_zone":         "TRUSTED",
    },
    # T3 — Edge device (IoT, sensors, minimal)
    "T3_ARM32": {
        "description":          "Edge Device — ARM32",
        "max_concurrent_tasks": 1,
        "model_tier":           1,
        "allowed_types":        [AI_PROBE, AI_RESULT],
        "offline_queue_size":   50,
        "heartbeat_interval":   120,
        "default_zone":         "PUBLIC",
    },
}
