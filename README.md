# Byngonet
> **AI-Native Distributed Mesh Network Protocol** — Sorabbyngo Labs

TCP/IP connects machines. Byngonet connects intelligent systems. Every packet knows what it is, who sent it, how trusted the sender is, and what compute it needs. The network is a participant in the intelligence.

## Architecture

### Kernel Layer (Phase 1 — Live)
- byngonet_identity v0.2 — NodeID cryptographic verification
- /proc/byngonet_stats — live node identity stats

### Protocol Layer (Phase 5)
- AISP: AI_TASK, AI_RESULT, AI_KNOW, AI_SYNC, AI_PROBE
- AF_BYNGONET socket family
- Post-quantum: Kyber-1024 + Dilithium3

### Swarm Layer (Phase 5)
- Node discovery and trust scoring agents
- Byzantine fault-tolerant offline sync
- Federated intelligence across mesh

## Security Zones
| Zone | Eligibility | Permitted |
|---|---|---|
| PUBLIC | External nodes | AI_PROBE only |
| TRUSTED | Known nodes trust>0.7 | Full AISP |
| PERSONAL | User own devices | Full + memory sync |
| CRITICAL | Medical nodes | All + emergency alerts |

## Status
| Component | Status |
|---|---|
| byngonet_identity v0.2 | Live |
| Netfilter hook v0.3 | In development |
| AISP protocol | Phase 5 |
| Post-quantum security | Month 6+ |

**Sorabbyngo Company** — Kisii, Kenya | 2026
