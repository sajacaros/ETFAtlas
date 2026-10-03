import pytest
from pydantic import ValidationError

from app.routers.auth import RegisterRequest
from app.utils.session import hash_token
from app.utils.security import hash_password, verify_password


def test_password_hash_roundtrip():
    h = hash_password("s3cret-pass")
    assert h != "s3cret-pass"
    assert verify_password("s3cret-pass", h)
    assert not verify_password("wrong-pass", h)


def test_verify_password_rejects_malformed_hash():
    assert not verify_password("anything", "not-a-bcrypt-hash")


def test_session_token_stored_as_hash():
    h = hash_token("raw-session-token")
    assert h != "raw-session-token"
    assert len(h) == 64
    assert h == hash_token("raw-session-token")
    assert h != hash_token("other-token")


@pytest.mark.parametrize("username,password", [
    ("ab", "password123"),          # username too short
    ("bad name", "password123"),    # invalid chars
    ("alice", "short"),             # password too short
    ("alice", "가" * 30),           # 90 bytes > bcrypt 72-byte limit
])
def test_register_request_validation(username, password):
    with pytest.raises(ValidationError):
        RegisterRequest(username=username, password=password)


def test_register_request_ok():
    req = RegisterRequest(username="alice_01", password="password123")
    assert req.name is None


def test_password_reset_request_validation():
    from app.routers.auth import PasswordResetRequest
    assert PasswordResetRequest(token="t", password="password123").password == "password123"
    for kwargs in ({"token": "t", "password": "short"},
                   {"token": "t", "password": "가" * 30},
                   {"token": "", "password": "password123"}):
        with pytest.raises(ValidationError):
            PasswordResetRequest(**kwargs)
