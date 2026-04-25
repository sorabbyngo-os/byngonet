# Byngonet Node Identity
# Reads NodeID from kernel and builds node certificate

import hashlib
from pathlib import Path

NODEID_PATH = "/proc/sorabbyngo/nodeid"

def get_nodeid() -> str:
    """Read hardware NodeID from kernel driver or fallback sources."""
    import os
    import hashlib
    import socket

    # 1. Kernel module (production)
    path = Path(NODEID_PATH)
    if path.exists():
        return path.read_text().strip()

    # 2. Sealed file (provisioned machine)
    sealed = Path("/var/lib/sorabbyngo/nodeid")
    if sealed.exists():
        return sealed.read_text().strip()

    # 3. Environment variable (dev/testing)
    env_id = os.environ.get("SORABBYNGO_NODE_ID")
    if env_id:
        return env_id

    # 4. Derive from hostname (last resort)
    hostname = socket.gethostname()
    return hashlib.sha256(f"byngonet:dev:{hostname}".encode()).hexdigest()

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
