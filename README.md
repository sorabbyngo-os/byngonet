# ByngoNet

AI-native distributed mesh network for Sorabbyngo OS.
Connects every Sorabbyngo device into an intelligent mesh.

## Protocol — AISP (AI Intelligence Sharing Protocol)

Every packet carries identity, type, payload, and signature.

| Message Type | Purpose |
|---|---|
| AI_TASK | Dispatch inference task to remote node |
| AI_RESULT | Return result from remote inference |
| AI_KNOW | Share knowledge update across mesh |
| AI_SYNC | Synchronize model weights or embeddings |
| AI_PROBE | Discover and verify node identity |

## Security zones

| Zone | Min trust | Allowed |
|---|---|---|
| PUBLIC | 0.0 | AI_PROBE only |
| TRUSTED | 0.7 | All types |
| PERSONAL | 1.0 | All types |
| CRITICAL | 1.0 | All types |

## Node tiers

| Tier | Device | Tasks | Model tier |
|---|---|---|---|
| T1_X86 | Server | 8 concurrent | 3 |
| T1_ARM64 | ARM server | 4 concurrent | 2 |
| T2_ARM64 | SBC/Gateway | 2 concurrent | 1 |
| T3_ARM32 | Edge device | 1 concurrent | 1 |

## NodeID

Every node identity derives from the hardware NodeID read from
/proc/sorabbyngo/nodeid (sorabbyngo_nodeid.ko kernel module).
No NodeID = no network participation.

## Offline-first

Nodes queue updates when disconnected.
On reconnect, OfflineSync flushes queued AI_KNOW and AI_SYNC packets.
Byzantine fault-tolerant — mesh survives minority node failures.
