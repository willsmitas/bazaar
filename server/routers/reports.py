from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from db.models import Report, User
from server.dependencies import get_current_user, get_db
from server.schemas import CreateReportRequest, ReportResponse

router = APIRouter(prefix="/reports", tags=["reports"])


@router.post("", response_model=ReportResponse, status_code=201)
def create_report(
    body:         CreateReportRequest,
    current_user: User    = Depends(get_current_user),
    db:           Session = Depends(get_db),
):
    if not body.reported_user_id and not body.reported_listing_id:
        raise HTTPException(status_code=400, detail="Must provide reported_user_id or reported_listing_id")
    if body.reported_user_id == current_user.user_id:
        raise HTTPException(status_code=400, detail="Cannot report yourself")

    report = Report(reporter_id=current_user.user_id, **body.model_dump())
    db.add(report)
    db.commit()
    db.refresh(report)
    return report
