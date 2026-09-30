from datetime import timedelta

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.routers.auth import RegisterRequest
from app.utils.jwt import create_access_token, decode_access_token
from app.utils.security import hash_password, verify_password


def test_password_hash_roundtrip():
    h = hash_password("s3cret-pass")
    assert h != "s3cret-pass"
    assert verify_password("s3cret-pass", h)
    assert not verify_password("wrong-pass", h)


def test_verify_password_rejects_malformed_hash():
    assert not verify_password("anything", "not-a-bcrypt-hash")


def test_jwt_roundtrip():
    token = create_access_token({"sub": "42"})
    assert decode_access_token(token)["sub"] == "42"


def test_jwt_expired():
    token = create_access_token({"sub": "42"}, expires_delta=timedelta(seconds=-1))
    with pytest.raises(HTTPException) as exc:
        decode_access_token(token)
    assert exc.value.status_code == 401


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
