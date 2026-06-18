from decimal import ROUND_HALF_UP, Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from db.models import Rating, Transaction, TxnStatus, User
from server.dependencies import get_verified_user, get_db
from server.schemas import CreateRatingRequest, RatingResponse

router = APIRouter(prefix="/ratings", tags=["ratings"])


@router.post("", response_model=RatingResponse, status_code=201)
def create_rating(
    body:         CreateRatingRequest,
    current_user: User    = Depends(get_verified_user),
    db:           Session = Depends(get_db),
):
    txn = db.query(Transaction).filter(Transaction.transaction_id == body.transaction_id).first()
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")
    if txn.status != TxnStatus.completed:
        raise HTTPException(status_code=400, detail="Can only rate completed transactions")
    if current_user.user_id not in (txn.buyer_id, txn.seller_id):
        raise HTTPException(status_code=403, detail="Not your transaction")
    if body.ratee_id not in (txn.buyer_id, txn.seller_id):
        raise HTTPException(status_code=400, detail="Ratee is not part of this transaction")
    if body.ratee_id == current_user.user_id:
        raise HTTPException(status_code=400, detail="Cannot rate yourself")

    if db.query(Rating).filter(
        Rating.transaction_id == body.transaction_id,
        Rating.rater_id       == current_user.user_id,
    ).first():
        raise HTTPException(status_code=409, detail="Already rated this transaction")

    rating = Rating(
        transaction_id=body.transaction_id,
        rater_id=current_user.user_id,
        ratee_id=body.ratee_id,
        score=body.score,
        review=body.review,
    )
    db.add(rating)
    db.flush()

    # Recompute ratee's cached average
    avg, count = db.query(
        func.avg(Rating.score), func.count(Rating.rating_id)
    ).filter(Rating.ratee_id == body.ratee_id).first()

    ratee = db.query(User).filter(User.user_id == body.ratee_id).first()
    if ratee:
        # Keep it in Decimal end-to-end so the cached average matches the
        # Numeric(3,2) column exactly (no float rounding drift).
        avg_dec = Decimal(str(avg)) if avg is not None else Decimal("0")
        ratee.rating_avg   = avg_dec.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        ratee.rating_count = count or 0

    db.commit()
    db.refresh(rating)
    return rating
