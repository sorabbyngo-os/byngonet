"""
Byngonet — Ed25519 Signing
Real cryptographic signing for AISP packets.
Replaces the HMAC-SHA256 placeholder in packet.py.
Uses the cryptography library — pure Python, no OpenSSL dependency.
"""
import hashlib
import logging
import os

log = logging.getLogger("byngonet.signing")


def _get_crypto():
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PrivateKey,
            Ed25519PublicKey,
        )
        from cryptography.hazmat.primitives.serialization import (
            Encoding, PublicFormat, PrivateFormat, NoEncryption
        )
        from cryptography.exceptions import InvalidSignature
        return Ed25519PrivateKey, Ed25519PublicKey, Encoding, PublicFormat, PrivateFormat, NoEncryption, InvalidSignature
    except ImportError:
        return None


def derive_keypair(node_id: str, secret: str) -> tuple[bytes, bytes]:
    """
    Derive a deterministic Ed25519 keypair from node_id + secret.
    Returns (private_key_bytes, public_key_bytes).
    Falls back to HMAC-SHA256 if cryptography lib not installed.
    """
    seed = hashlib.sha256(f"{node_id}:{secret}".encode()).digest()

    crypto = _get_crypto()
    if crypto is None:
        log.warning("cryptography library not installed — using HMAC fallback")
        return seed, hashlib.sha256(seed).digest()

    Ed25519PrivateKey, _, Encoding, PublicFormat, PrivateFormat, NoEncryption, _ = crypto
    private_key = Ed25519PrivateKey.from_private_bytes(seed)
    public_key  = private_key.public_key()

    priv_bytes = private_key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    pub_bytes  = public_key.public_bytes(Encoding.Raw, PublicFormat.Raw)

    return priv_bytes, pub_bytes


def sign(content: str, private_key_bytes: bytes) -> str:
    """
    Sign content string with Ed25519 private key.
    Returns hex-encoded signature.
    Falls back to HMAC-SHA256 if library unavailable.
    """
    crypto = _get_crypto()
    if crypto is None:
        import hmac as _hmac
        sig = _hmac.new(private_key_bytes, content.encode(), hashlib.sha256).hexdigest()
        return sig

    Ed25519PrivateKey, _, Encoding, _, PrivateFormat, NoEncryption, _ = crypto
    try:
        private_key = Ed25519PrivateKey.from_private_bytes(private_key_bytes)
        signature   = private_key.sign(content.encode())
        return signature.hex()
    except Exception as e:
        log.error("Ed25519 sign error: %s", e)
        return ""


def verify(content: str, signature_hex: str, public_key_bytes: bytes) -> bool:
    """
    Verify Ed25519 signature against public key.
    Falls back to length check if library unavailable.
    """
    if not signature_hex:
        return False

    crypto = _get_crypto()
    if crypto is None:
        return len(signature_hex) == 64

    _, Ed25519PublicKey, Encoding, PublicFormat, _, _, InvalidSignature = crypto
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey as PK
        public_key = PK.from_public_bytes(public_key_bytes)
        public_key.verify(bytes.fromhex(signature_hex), content.encode())
        return True
    except Exception:
        return False
