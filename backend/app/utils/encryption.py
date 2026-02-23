"""Application-level AES-256-GCM column encryption for SQLAlchemy."""
import base64
import os
from decimal import Decimal
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator


def _get_key() -> bytes:
    """Get encryption key directly from environment variable."""
    key_hex = os.environ.get('ENCRYPTION_KEY', '')
    if not key_hex:
        raise RuntimeError("ENCRYPTION_KEY environment variable is not set")
    return bytes.fromhex(key_hex)


_aesgcm_instance: AESGCM | None = None


def _get_aesgcm() -> AESGCM:
    """Return a cached AESGCM instance (created once per process)."""
    global _aesgcm_instance
    if _aesgcm_instance is None:
        _aesgcm_instance = AESGCM(_get_key())
    return _aesgcm_instance


def encrypt_value(plaintext: str) -> str:
    """Encrypt a string value and return Base64-encoded ciphertext."""
    aesgcm = _get_aesgcm()
    nonce = os.urandom(12)  # 96-bit nonce for GCM
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode('utf-8'), None)
    return base64.b64encode(nonce + ciphertext).decode('ascii')


def decrypt_value(token: str) -> str:
    """Decrypt a Base64-encoded ciphertext and return the plaintext string."""
    aesgcm = _get_aesgcm()
    raw = base64.b64decode(token)
    nonce = raw[:12]
    ciphertext = raw[12:]
    return aesgcm.decrypt(nonce, ciphertext, None).decode('utf-8')


class EncryptedDecimal(TypeDecorator):
    """Transparently encrypts/decrypts Decimal values."""
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return encrypt_value(str(value))

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        plaintext = decrypt_value(value)
        return Decimal(plaintext)


class EncryptedFloat(TypeDecorator):
    """Transparently encrypts/decrypts float values."""
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return encrypt_value(str(value))

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        plaintext = decrypt_value(value)
        return float(plaintext)
