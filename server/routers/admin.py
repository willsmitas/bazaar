"""
admin.py — Moderation endpoints. Every route requires an admin account
(enforced by the router-level get_current_admin dependency).
"""
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from db.models import AccountStatus, Listing, ListingStatus, Report, ReportStatus, User
from server.dependencies import get_current_admin, get_db
from server.schemas import (
    AdminUserResponse,
    BanRequest,
    ListingResponse,
    ReportResponse,
    ResolveReportRequest,
    SuspendRequest,
)

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(get_current_admin)])


# ── Reports ─────────────────────────────────────────────────────────────────────

@router.get("/reports", response_model=List[ReportResponse])
def list_reports(
    status: Optional[ReportStatus] = Query(None, description="Filter by status; omit for all"),
    db:     Session                = Depends(get_db),
):
    query = db.query(Report)
    if status:
        query = query.filter(Report.status == status)
    return query.order_by(Report.created_at.desc()).all()


@router.post("/reports/{report_id}/resolve", response_model=ReportResponse)
def resolve_report(report_id: str, body: ResolveReportRequest, db: Session = Depends(get_db)):
    report = db.query(Report).filter(Report.report_id == report_id).first()
    if not report:
        raise HTTPException(404, "Report not found")
    if body.status == ReportStatus.pending:
        raise HTTPException(400, "Choose 'reviewed', 'resolved', or 'dismissed'")
    report.status = body.status
    report.resolved_at = (
        datetime.now(timezone.utc)
        if body.status in (ReportStatus.resolved, ReportStatus.dismissed)
        else None
    )
    db.commit()
    db.refresh(report)
    return report


# ── User moderation ───────────────────────────────────────────────────────────────

@router.get("/users", response_model=List[AdminUserResponse])
def list_users(
    q:  Optional[str] = Query(None, description="Search email or full name"),
    db: Session       = Depends(get_db),
):
    query = db.query(User)
    if q:
        query = query.filter(or_(User.email.ilike(f"%{q}%"), User.full_name.ilike(f"%{q}%")))
    return query.order_by(User.created_at.desc()).limit(100).all()


@router.get("/users/{user_id}", response_model=AdminUserResponse)
def get_user(user_id: str, db: Session = Depends(get_db)):
    """Full user record (incl. email) for moderation views."""
    return _get_user_or_404(user_id, db)


@router.post("/users/{user_id}/ban", response_model=AdminUserResponse)
def ban_user(
    user_id: str,
    body:    BanRequest,
    admin:   User    = Depends(get_current_admin),
    db:      Session = Depends(get_db),
):
    user = _get_user_or_404(user_id, db)
    _guard(user, admin)
    user.account_status    = AccountStatus.banned
    user.ban_reason        = body.reason
    user.suspension_ends_at = None
    db.commit()
    db.refresh(user)
    return user


@router.post("/users/{user_id}/suspend", response_model=AdminUserResponse)
def suspend_user(
    user_id: str,
    body:    SuspendRequest,
    admin:   User    = Depends(get_current_admin),
    db:      Session = Depends(get_db),
):
    user = _get_user_or_404(user_id, db)
    _guard(user, admin)
    user.account_status     = AccountStatus.suspended
    user.suspension_ends_at = datetime.now(timezone.utc) + timedelta(days=body.days)
    user.ban_reason         = body.reason
    db.commit()
    db.refresh(user)
    return user


@router.post("/users/{user_id}/reinstate", response_model=AdminUserResponse)
def reinstate_user(user_id: str, db: Session = Depends(get_db)):
    user = _get_user_or_404(user_id, db)
    user.account_status     = AccountStatus.active
    user.suspension_ends_at = None
    user.ban_reason         = None
    db.commit()
    db.refresh(user)
    return user


# ── Listing moderation ────────────────────────────────────────────────────────────

@router.post("/listings/{listing_id}/remove", response_model=ListingResponse)
def remove_listing(listing_id: str, db: Session = Depends(get_db)):
    listing = db.query(Listing).filter(Listing.listing_id == listing_id).first()
    if not listing:
        raise HTTPException(404, "Listing not found")
    listing.status = ListingStatus.removed
    db.commit()
    db.refresh(listing)
    return listing


# ── helpers ───────────────────────────────────────────────────────────────────────

def _get_user_or_404(user_id: str, db: Session) -> User:
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    return user


def _guard(target: User, admin: User) -> None:
    if target.user_id == admin.user_id:
        raise HTTPException(400, "You can't moderate your own account")
    if target.is_admin:
        raise HTTPException(403, "You can't moderate another admin")
