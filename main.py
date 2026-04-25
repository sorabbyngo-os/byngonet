#!/usr/bin/env python3
"""
Byngonet — Main entry point
Starts a Byngonet mesh node with proper signal handling,
logging, environment loading, and NATS sentinel integration.

Usage:
    python3 main.py [--tier T1_X86|T1_ARM64|T2_ARM64|T3_ARM32]
    byngonet-node --tier T2_ARM64
"""
import asyncio
import argparse
import logging
import os
import signal
import sys
from pathlib import Path

# Load .env if present
def _load_env():
    env_file = Path(__file__).parent / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

_load_env()

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ]
)

# Add file handler if log dir exists
log_dir = Path("/var/log/sorabbyngo")
if log_dir.exists() and os.access(log_dir, os.W_OK):
    fh = logging.FileHandler(log_dir / "byngonet.log")
    fh.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s — %(message)s"
    ))
    logging.getLogger().addHandler(fh)

log = logging.getLogger("byngonet.main")

BANNER = """
╔══════════════════════════════════════════════════════════╗
║   Byngonet — AI-native Mesh Network                     ║
║   AISP v0.2 · Sorabbyngo Labs · Kisii, Kenya            ║
╚══════════════════════════════════════════════════════════╝
"""

async def run(tier: str):
    from node.byngonet_node import ByngonetNode
    from sentinel_bridge import SentinelBridge

    print(BANNER)
    log.info("Starting Byngonet node — tier=%s", tier)

    node   = ByngonetNode(tier=tier)
    bridge = SentinelBridge(node)

    loop = asyncio.get_event_loop()

    # Graceful shutdown on SIGINT/SIGTERM
    def _shutdown():
        log.info("Shutdown signal received")
        node.stop()
        bridge.stop()
        for task in asyncio.all_tasks(loop):
            task.cancel()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _shutdown)

    try:
        await asyncio.gather(
            node.start(),
            bridge.start(),
            return_exceptions=True,
        )
    except asyncio.CancelledError:
        pass
    finally:
        log.info("Byngonet node stopped")

def main():
    parser = argparse.ArgumentParser(
        description="Byngonet AI-native mesh network node"
    )
    parser.add_argument(
        "--tier",
        default=os.environ.get("BYNGONET_TIER", "T1_X86"),
        choices=["T1_X86", "T1_ARM64", "T2_ARM64", "T3_ARM32"],
        help="Node hardware tier"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("BYNGONET_PORT", 7422)),
        help="UDP port for AISP mesh (default: 7422)"
    )
    args = parser.parse_args()

    os.environ["BYNGONET_PORT"] = str(args.port)
    os.environ["BYNGONET_TIER"] = args.tier

    asyncio.run(run(args.tier))

if __name__ == "__main__":
    main()
