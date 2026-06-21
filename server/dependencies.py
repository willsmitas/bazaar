"""
dependencies.py — FastAPI dependency functions shared across routers.
"""
import uuid
from typing import Set

from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from db.database import SessionLocal
from db.models import AccountStatus, Block, User
from server.security import decode_access_token

_bearer = HTTPBearer()


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    user_id = decode_access_token(credentials.credentials)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    if user.account_status == AccountStatus.banned:
        raise HTTPException(status_code=403, detail="Account is banned")
    if user.account_status == AccountStatus.suspended:
        from datetime import datetime, timezone
        if user.suspension_ends_at and user.suspension_ends_at > datetime.now(timezone.utc):
            raise HTTPException(status_code=403, detail="Account is suspended")
        # Suspension expired — reinstate automatically
        user.account_status = AccountStatus.active
        db.commit()

    return user


def get_verified_user(current_user: User = Depends(get_current_user)) -> User:
    """Like get_current_user, but also requires a verified email address."""
    if not current_user.email_verified:
        raise HTTPException(status_code=403, detail="Verify your email address to do that")
    return current_user


def get_current_admin(current_user: User = Depends(get_current_user)) -> User:
    """Require any admin role (school or global)."""
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user


def get_blocked_user_ids(user_id: uuid.UUID, db: Session) -> Set[uuid.UUID]:
    """User IDs in either direction of a block relationship with `user_id`.

    Returns a set of users that the given user should be mutually invisible to
    (they don't see each other's listings, can't start new transactions, etc.).
    """
    rows = (
        db.query(Block.blocker_id, Block.blocked_id)
        .filter((Block.blocker_id == user_id) | (Block.blocked_id == user_id))
        .all()
    )
    ids: Set[uuid.UUID] = set()
    for blocker, blocked in rows:
        ids.add(blocker if blocker != user_id else blocked)
    return ids


def get_global_admin(current_user: User = Depends(get_current_user)) -> User:
    """Require global admin — operations that span schools."""
    if not current_user.is_global_admin:
        raise HTTPException(status_code=403, detail="Global admin access required")
    return current_user
