# Byngonet Node Identity
# Reads NodeID from kernel and builds node certificate

import hashlib
from pathlib import Path

NODEID_PATH = "/proc/sorabbyngo/nodeid"

def get_nodeid() -> str:
    """Read hardware NodeID from kernel driver."""
    path = Path(NODEID_PATH)
    if not path.exists():
        raise RuntimeError(
            f"NodeID driver not loaded. Is 6.19.10-sorabbyngo kernel running?"
        )
    return path.read_text().strip()

def build_node_certificate(nodeid: str, capabilities: list) -> dict:
    """Build a Byngonet node certificate from NodeID."""
    return {
        "node_id": nodeid,
        "capabilities": capabilities,
        "fingerprint": hashlib.sha256(nodeid.encode()).hexdigest(),
        "zone": "TRUSTED",
        "trust_score": 0.0,  # Starts at 0, builds over time
    }

if __name__ == "__main__":
    nid = get_nodeid()
    cert = build_node_certificate(nid, ["AI_TASK", "AI_RESULT", "AI_KNOW"])
    print(f"NodeID: {nid}")
    print(f"Certificate: {cert}")
