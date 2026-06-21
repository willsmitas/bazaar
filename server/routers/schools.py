from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from db.models import School
from server.dependencies import get_db
from server.schemas import SchoolResponse

router = APIRouter(prefix="/schools", tags=["schools"])


@router.get("", response_model=List[SchoolResponse])
def list_schools(db: Session = Depends(get_db)):
    """Active schools and their branding.

    Public (no auth): the client uses this to theme the sign-in screens by
    matching a typed email domain to a school before the user has an account.
    """
    return (
        db.query(School)
        .filter(School.is_active.is_(True))
        .order_by(School.name)
        .all()
    )
