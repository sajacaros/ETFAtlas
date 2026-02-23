"""Application-level AES-256-GCM column encryption for SQLAlchemy."""
import base64
import os
from decimal import Decimal
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator


def _get_key() -> bytes:
    from ..config import get_settings
    key_hex = get_settings().encryption_key
    if not key_hex:
        raise RuntimeError("ENCRYPTION_KEY is not set")
    return bytes.fromhex(key_hex)


def encrypt_value(plaintext: str) -> str:
    """Encrypt a string value and return Base64-encoded ciphertext."""
    key = _get_key()
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)  # 96-bit nonce for GCM
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode('utf-8'), None)
    return base64.b64encode(nonce + ciphertext).decode('ascii')


def decrypt_value(token: str) -> str:
    """Decrypt a Base64-encoded ciphertext and return the plaintext string."""
    key = _get_key()
    aesgcm = AESGCM(key)
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
