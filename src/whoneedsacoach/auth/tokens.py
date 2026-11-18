import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import jwt

from whoneedsacoach.utils.config import AUTH_ACCESS_TTL_SECONDS, AUTH_JWT_SECRET

ALGORITHM = "HS256"
REFRESH_COOKIE = "refresh_token"
REFRESH_PATH = "/auth"


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_refresh_token() -> str:
    return secrets.token_urlsafe(32)


def create_access_token(user_id: int, *, ttl_seconds: int | None = None) -> str:
    ttl = AUTH_ACCESS_TTL_SECONDS if ttl_seconds is None else ttl_seconds
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(seconds=ttl),
        "jti": secrets.token_hex(8),
    }
    return jwt.encode(payload, AUTH_JWT_SECRET, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict:
    return jwt.decode(token, AUTH_JWT_SECRET, algorithms=[ALGORITHM])
