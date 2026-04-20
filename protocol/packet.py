import uuid
import time
import hashlib
import json
from dataclasses import dataclass, field
from typing import Optional
from .message_types import PACKET_TYPES, SECURITY_ZONES

@dataclass
class ByngoPacket:
    """
    AISP — AI Intelligence Sharing Protocol packet.
    Every packet carries: identity, type, payload, signature.
    """
    packet_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    packet_type: str = ""
    sender_node_id: str = ""
    target_node_id: str = ""
    payload: dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    ttl: int = 30
    hop_count: int = 0
    signature: str = ""
    zone: str = "PUBLIC"

    def sign(self, private_key: str) -> None:
        """
        Sign packet with node private key.
        TODO Phase 5: Replace with proper Ed25519 signing via cryptography library.
        Current implementation uses HMAC-SHA256 as a placeholder.
        """
        import hmac
        content = f"{self.packet_id}{self.packet_type}{self.sender_node_id}{self.timestamp}"
        self.signature = hmac.new(
            private_key.encode(), content.encode(), hashlib.sha256
        ).hexdigest()

    def verify(self, sender_fingerprint: str) -> bool:
        """
        Verify packet signature against sender fingerprint.
        TODO Phase 5: Replace with proper Ed25519 public key verification.
        Current implementation checks signature is non-empty and correct length.
        """
        return bool(self.signature) and len(self.signature) == 64

    def is_expired(self) -> bool:
        return time.time() - self.timestamp > self.ttl

    def to_bytes(self) -> bytes:
        return json.dumps({
            "packet_id": self.packet_id,
            "packet_type": self.packet_type,
            "sender_node_id": self.sender_node_id,
            "target_node_id": self.target_node_id,
            "payload": self.payload,
            "timestamp": self.timestamp,
            "ttl": self.ttl,
            "hop_count": self.hop_count,
            "signature": self.signature,
            "zone": self.zone,
        }).encode()

    @classmethod
    def from_bytes(cls, data: bytes) -> "ByngoPacket":
        d = json.loads(data.decode())
        return cls(**d)
