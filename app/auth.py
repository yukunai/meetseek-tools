from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext


def _resolve_jwt_secret() -> str:
    """JWT signing secret. Never use ADMIN_TOKEN here (privilege separation)."""
    secret = (os.getenv("JWT_SECRET") or os.getenv("SECRET_KEY") or "").strip()
    if secret:
        return secret
    if os.getenv("MEETSEEK_DEV_INSECURE_JWT", "").lower() in {"1", "true", "yes"}:
        return "meetseek-dev-secret"
    raise RuntimeError(
        "Set JWT_SECRET or SECRET_KEY in the environment for signing auth tokens. "
        "For disposable local testing only, set MEETSEEK_DEV_INSECURE_JWT=1 "
        "(never enable that in production)."
    )


JWT_SECRET = _resolve_jwt_secret()
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRE_DAYS = int(os.getenv("JWT_EXPIRE_DAYS", "30"))

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password_bcrypt(password: str) -> str:
    return pwd_context.hash(password)


def verify_password_bcrypt(password: str, hashed_password: str) -> bool:
    if not hashed_password:
        return False
    try:
        return pwd_context.verify(password, hashed_password)
    except Exception:
        return False


def create_access_token(subject: int | str, extra: dict[str, Any] | None = None) -> str:
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(days=JWT_EXPIRE_DAYS)).timestamp()),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any] | None:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError:
        return None
