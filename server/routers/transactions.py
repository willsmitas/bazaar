from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from db.models import Chat, Listing, ListingStatus, Transaction, TxnStatus, User
from server.dependencies import get_current_user, get_db
from server.schemas import (
    CreateTransactionRequest,
    TransactionResponse,
    UpdateTransactionRequest,
)

router = APIRouter(prefix="/transactions", tags=["transactions"])

# Valid status transitions: current → allowed next states
_TRANSITIONS: dict[TxnStatus, set[TxnStatus]] = {
    TxnStatus.negotiating:      {TxnStatus.price_locked, TxnStatus.cancelled},
    TxnStatus.price_locked:     {TxnStatus.pending_delivery, TxnStatus.disputed, TxnStatus.cancelled},
    TxnStatus.pending_delivery: {TxnStatus.completed, TxnStatus.disputed},
    TxnStatus.completed:        set(),
    TxnStatus.disputed:         {TxnStatus.completed, TxnStatus.cancelled},
    TxnStatus.cancelled:        set(),
}


@router.post("", response_model=TransactionResponse, status_code=201)
def create_transaction(
    body:         CreateTransactionRequest,
    current_user: User    = Depends(get_current_user),
    db:           Session = Depends(get_db),
):
    listing = db.query(Listing).filter(Listing.listing_id == body.listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    if listing.seller_id == current_user.user_id:
        raise HTTPException(status_code=400, detail="Cannot open a transaction on your own listing")
    if listing.status != ListingStatus.active:
        raise HTTPException(status_code=400, detail="Listing is not available")

    txn = Transaction(
        listing_id=body.listing_id,
        buyer_id=current_user.user_id,
        seller_id=listing.seller_id,
    )
    listing.status = ListingStatus.in_negotiation
    db.add(txn)
    db.flush()  # get txn.transaction_id before creating the chat

    chat = Chat(
        transaction_id=txn.transaction_id,
        listing_id=body.listing_id,
        participant_1=current_user.user_id,
        participant_2=listing.seller_id,
    )
    db.add(chat)
    db.commit()
    db.refresh(txn)
    return txn


@router.get("", response_model=List[TransactionResponse])
def list_transactions(
    current_user: User    = Depends(get_current_user),
    db:           Session = Depends(get_db),
):
    return (
        db.query(Transaction)
        .filter(
            (Transaction.buyer_id == current_user.user_id)
            | (Transaction.seller_id == current_user.user_id)
        )
        .order_by(Transaction.created_at.desc())
        .all()
    )


@router.get("/{txn_id}", response_model=TransactionResponse)
def get_transaction(
    txn_id:       str,
    current_user: User    = Depends(get_current_user),
    db:           Session = Depends(get_db),
):
    txn = _get_or_404(txn_id, db)
    _assert_participant(txn, current_user)
    return txn


@router.put("/{txn_id}", response_model=TransactionResponse)
def update_transaction(
    txn_id:       str,
    body:         UpdateTransactionRequest,
    current_user: User    = Depends(get_current_user),
    db:           Session = Depends(get_db),
):
    txn = _get_or_404(txn_id, db)
    _assert_participant(txn, current_user)

    if body.agreed_price is not None:
        txn.agreed_price      = body.agreed_price
        txn.commission_amount = txn.compute_commission()

    if body.status is not None:
        _validate_transition(txn.status, body.status)
        txn.status = body.status

        if body.status == TxnStatus.price_locked:
            txn.price_locked_at = datetime.now(timezone.utc)

        if body.status == TxnStatus.completed:
            txn.completed_at = datetime.now(timezone.utc)
            _on_completed(txn, db)

    db.commit()
    db.refresh(txn)
    return txn


# ── helpers ───────────────────────────────────────────────────────────────────

def _get_or_404(txn_id: str, db: Session) -> Transaction:
    txn = db.query(Transaction).filter(Transaction.transaction_id == txn_id).first()
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return txn


def _assert_participant(txn: Transaction, user: User) -> None:
    if user.user_id not in (txn.buyer_id, txn.seller_id):
        raise HTTPException(status_code=403, detail="Not your transaction")


def _validate_transition(current: TxnStatus, next_status: TxnStatus) -> None:
    if next_status not in _TRANSITIONS.get(current, set()):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot transition from '{current}' to '{next_status}'",
        )


def _on_completed(txn: Transaction, db: Session) -> None:
    """Side-effects when a transaction is marked complete."""
    # Increment transaction counter on both users
    for uid in (txn.buyer_id, txn.seller_id):
        user = db.query(User).filter(User.user_id == uid).first()
        if user:
            user.transactions_completed += 1

    # Mark the listing as sold
    listing = db.query(Listing).filter(Listing.listing_id == txn.listing_id).first()
    if listing:
        listing.status = ListingStatus.sold
