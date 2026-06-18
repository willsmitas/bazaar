"""
security.py — Passwords, JWTs, and one-time code generation.

Passwords use bcrypt directly (not passlib, which is unmaintained and breaks
with modern bcrypt releases).
"""
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from jose import JWTError, jwt

from config import settings

_ALGORITHM = "HS256"

# bcrypt only uses the first 72 bytes of a password and bcrypt>=4 raises on
# anything longer, so we truncate explicitly (and identically on hash + verify).
_BCRYPT_MAX_BYTES = 72


# ── Passwords ─────────────────────────────────────────────────────────────────

def hash_password(plain: str) -> str:
    pw = plain.encode("utf-8")[:_BCRYPT_MAX_BYTES]
    return bcrypt.hashpw(pw, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8")[:_BCRYPT_MAX_BYTES], hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# ── One-time codes ──────────────────────────────────────────────────────────────

def generate_otp() -> str:
    """Return a random 6-digit numeric code (100000–999999)."""
    return str(secrets.randbelow(900_000) + 100_000)


# ── JWT ───────────────────────────────────────────────────────────────────────

def create_access_token(user_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_ttl_minutes)
    return jwt.encode(
        {"sub": user_id, "type": "access", "exp": expire},
        settings.secret_key,
        algorithm=_ALGORITHM,
    )


def create_refresh_token(user_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_ttl_days)
    return jwt.encode(
        {"sub": user_id, "type": "refresh", "exp": expire},
        settings.secret_key,
        algorithm=_ALGORITHM,
    )


def decode_access_token(token: str) -> Optional[str]:
    return _decode(token, expected_type="access")


def decode_refresh_token(token: str) -> Optional[str]:
    return _decode(token, expected_type="refresh")


def _decode(token: str, expected_type: str) -> Optional[str]:
    """Returns the user_id (sub) or None if the token is invalid, expired, or wrong type."""
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[_ALGORITHM])
        if payload.get("type") != expected_type:
            return None
        return payload.get("sub")
    except JWTError:
        return None
