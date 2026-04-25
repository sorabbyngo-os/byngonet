"""
Byngonet — AISP Packet
AI Intelligence Sharing Protocol — core packet definition.
Every packet carries: identity, type, payload, signature.
Signing: Ed25519 (real) via protocol.signing, HMAC-SHA256 fallback.
"""
import json
import time
import uuid
from dataclasses import dataclass, field

from .message_types import PACKET_TYPES, SECURITY_ZONES


@dataclass
class ByngoPacket:
    """AISP packet — the unit of communication in the Byngonet mesh."""

    packet_id:      str   = field(default_factory=lambda: str(uuid.uuid4()))
    packet_type:    str   = ""
    sender_node_id: str   = ""
    target_node_id: str   = ""
    payload:        dict  = field(default_factory=dict)
    timestamp:      float = field(default_factory=time.time)
    ttl:            int   = 30
    hop_count:      int   = 0
    signature:      str   = ""
    zone:           str   = "PUBLIC"

    # ── Signing ───────────────────────────────────────────────────────────────

    def _sign_content(self) -> str:
        return (
            f"{self.packet_id}"
            f"{self.packet_type}"
            f"{self.sender_node_id}"
            f"{self.timestamp}"
        )

    def sign(self, private_key: bytes | str) -> None:
        """Sign packet with node Ed25519 private key."""
        from .signing import sign as _sign
        if isinstance(private_key, str):
            private_key = bytes.fromhex(private_key) if len(private_key) == 64 else private_key.encode()
        self.signature = _sign(self._sign_content(), private_key)

    def verify(self, public_key: bytes | str) -> bool:
        """Verify packet Ed25519 signature."""
        from .signing import verify as _verify
        if isinstance(public_key, str):
            try:
                public_key = bytes.fromhex(public_key)
            except ValueError:
                public_key = public_key.encode()
        return _verify(self._sign_content(), self.signature, public_key)

    # ── Validation ────────────────────────────────────────────────────────────

    def is_expired(self) -> bool:
        return time.time() - self.timestamp > self.ttl

    def is_allowed_in_zone(self, trust_score: float) -> bool:
        """Check if this packet type is allowed given current trust score."""
        zone_cfg = SECURITY_ZONES.get(self.zone, SECURITY_ZONES["PUBLIC"])
        return (
            self.packet_type in zone_cfg["allowed"]
            and trust_score >= zone_cfg["min_trust"]
        )

    # ── Serialization ─────────────────────────────────────────────────────────

    def to_bytes(self) -> bytes:
        return json.dumps({
            "packet_id":      self.packet_id,
            "packet_type":    self.packet_type,
            "sender_node_id": self.sender_node_id,
            "target_node_id": self.target_node_id,
            "payload":        self.payload,
            "timestamp":      self.timestamp,
            "ttl":            self.ttl,
            "hop_count":      self.hop_count,
            "signature":      self.signature,
            "zone":           self.zone,
        }).encode()

    @classmethod
    def from_bytes(cls, data: bytes) -> "ByngoPacket":
        d = json.loads(data.decode())
        return cls(**d)

    def __repr__(self) -> str:
        return (
            f"ByngoPacket(type={self.packet_type}, "
            f"from={self.sender_node_id[:8]}..., "
            f"zone={self.zone}, "
            f"hop={self.hop_count})"
        )
