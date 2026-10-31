"""Password hashing (bcrypt)."""
import bcrypt


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


# 없는 아이디로 로그인할 때도 같은 시간을 쓰도록 비교할 해시 (응답 시간으로 아이디 존재 여부가 드러나지 않게)
_DUMMY_HASH = bcrypt.hashpw(b"not-a-real-password", bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, password_hash: str | None) -> bool:
    if password_hash is None:
        bcrypt.checkpw(password.encode("utf-8"), _DUMMY_HASH.encode("ascii"))
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))
    except ValueError:
        return False
