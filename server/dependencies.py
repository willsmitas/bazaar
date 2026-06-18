"""
dependencies.py — FastAPI dependency functions shared across routers.
"""
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from db.database import SessionLocal
from db.models import AccountStatus, User
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
    """Like get_current_user, but also requires the account to be an admin."""
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user
