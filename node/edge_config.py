# Edge Node Configuration
# Per-device-tier Byngonet settings

TIER_CONFIGS = {
    "T1_X86": {
        "max_concurrent_tasks": 8,
        "model_tier": 3,
        "zone": "TRUSTED",
        "offline_queue_size": 1000,
    },
    "T1_ARM64": {
        "max_concurrent_tasks": 4,
        "model_tier": 2,
        "zone": "TRUSTED",
        "offline_queue_size": 500,
    },
    "T2_ARM64": {
        "max_concurrent_tasks": 2,
        "model_tier": 1,
        "zone": "TRUSTED",
        "offline_queue_size": 200,
    },
    "T3_ARM32": {
        "max_concurrent_tasks": 1,
        "model_tier": 1,
        "zone": "TRUSTED",
        "offline_queue_size": 50,
    },
}
