#!/usr/bin/env python3
"""
node_identity.py — Byngonet HAL Identity Registration
Reads NodeID from /proc/sorabbyngo/nodeid (kernel driver)
Derives mesh identity, signs it with Ed25519
Publishes to NATS: sorabbyngo.byngonet.mesh.register
This is the first thing Byngonet does at boot.
"""

import os
import time
import json
import hashlib
import base64
import socket
import platform
import logging

log = logging.getLogger("byngonet.identity")

NODEID_PATH  = "/proc/sorabbyngo/nodeid"
KEY_DIR      = os.path.expanduser("~/.sorabbyngo/byngonet/keys")
PRIV_KEY     = os.path.join(KEY_DIR, "node.key")
PUB_KEY      = os.path.join(KEY_DIR, "node.pub")
IDENTITY_FILE = os.path.expanduser("~/.sorabbyngo/byngonet/identity.json")


class HALIdentity:
    """
    Reads hardware identity from kernel NodeID driver.
    Derives Byngonet mesh identity from it.
    Generates Ed25519 keypair bound to NodeID.
    """

    def __init__(self):
        self.node_id     = self._read_nodeid()
        self.mesh_id     = self._derive_mesh_id()
        self.hostname    = socket.gethostname()
        self.kernel      = platform.release()
        self.sealed      = self.node_id is not None
        self._priv_key   = None
        self._pub_key    = None
        self._ensure_keys()

    def _read_nodeid(self) -> str | None:
        try:
            with open(NODEID_PATH) as f:
                nid = f.read().strip()
                log.info(f"NodeID read from HAL: {nid[:16]}...")
                return nid
        except FileNotFoundError:
            log.warning(f"NodeID not found at {NODEID_PATH} — running unsealed")
            return None
        except PermissionError:
            log.error(f"Permission denied reading {NODEID_PATH}")
            return None

    def _derive_mesh_id(self) -> str:
        """
        Mesh ID is a deterministic derivation of NodeID.
        Same device always gets same mesh ID.
        Different from NodeID — mesh ID is safe to share publicly.
        """
        if self.node_id:
            return hashlib.sha256(
                f"byngonet:mesh:{self.node_id}".encode()
            ).hexdigest()[:32]
        # Fallback for dev/QEMU — derive from hostname
        return hashlib.sha256(
            f"byngonet:mesh:dev:{socket.gethostname()}".encode()
        ).hexdigest()[:32]

    def _ensure_keys(self):
        """Generate Ed25519 keypair if not present. Bind to NodeID."""
        os.makedirs(KEY_DIR, exist_ok=True)

        if os.path.exists(PRIV_KEY) and os.path.exists(PUB_KEY):
            self._load_keys()
            return

        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
            from cryptography.hazmat.primitives.serialization import (
                Encoding, PrivateFormat, PublicFormat, NoEncryption
            )

            private_key = Ed25519PrivateKey.generate()
            public_key  = private_key.public_key()

            priv_bytes = private_key.private_bytes(
                Encoding.Raw, PrivateFormat.Raw, NoEncryption()
            )
            pub_bytes = public_key.public_bytes(Encoding.Raw, PublicFormat.Raw)

            with open(PRIV_KEY, "wb") as f:
                f.write(priv_bytes)
            os.chmod(PRIV_KEY, 0o600)

            with open(PUB_KEY, "wb") as f:
                f.write(pub_bytes)

            self._priv_key = private_key
            self._pub_key  = public_key

            log.info(f"Node keypair generated: {PUB_KEY}")
            log.info(f"Public key: {base64.b64encode(pub_bytes).decode()[:32]}...")

        except ImportError:
            log.warning("cryptography not available — node signing disabled")

    def _load_keys(self):
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import (
                Ed25519PrivateKey, Ed25519PublicKey
            )
            with open(PRIV_KEY, "rb") as f:
                self._priv_key = Ed25519PrivateKey.from_private_bytes(f.read())
            with open(PUB_KEY, "rb") as f:
                pub_bytes = f.read()
                self._pub_key = Ed25519PublicKey.from_public_bytes(pub_bytes)
            log.info("Node keys loaded")
        except Exception as e:
            log.error(f"Failed to load keys: {e}")

    def sign(self, data: bytes) -> str | None:
        """Sign arbitrary data with node private key"""
        if not self._priv_key:
            return None
        try:
            sig = self._priv_key.sign(data)
            return base64.b64encode(sig).decode()
        except Exception as e:
            log.error(f"Sign error: {e}")
            return None

    def public_key_b64(self) -> str | None:
        if not self._pub_key:
            return None
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
        pub_bytes = self._pub_key.public_bytes(Encoding.Raw, PublicFormat.Raw)
        return base64.b64encode(pub_bytes).decode()

    def to_dict(self) -> dict:
        return {
            "mesh_id":    self.mesh_id,
            "hostname":   self.hostname,
            "kernel":     self.kernel,
            "sealed":     self.sealed,
            "public_key": self.public_key_b64(),
            "timestamp":  time.time(),
        }

    def save(self):
        os.makedirs(os.path.dirname(IDENTITY_FILE), exist_ok=True)
        with open(IDENTITY_FILE, "w") as f:
            json.dump(self.to_dict(), f, indent=2)
        log.info(f"Identity saved: {IDENTITY_FILE}")

    def __repr__(self):
        return (
            f"HALIdentity("
            f"mesh_id={self.mesh_id[:12]}..., "
            f"sealed={self.sealed}, "
            f"hostname={self.hostname})"
        )
