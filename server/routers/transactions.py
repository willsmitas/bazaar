from datetime import datetime, timezone
from typing import List

import stripe
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from config import settings
from db.models import (
    Chat, Listing, ListingStatus, PaymentStatus, Transaction, TxnStatus, User,
)
from server import stripe_client as sc
from server.dependencies import get_blocked_user_ids, get_verified_user, get_db
from server.schemas import (
    CreateTransactionRequest,
    PaymentIntentResponse,
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
    current_user: User    = Depends(get_verified_user),
    db:           Session = Depends(get_db),
):
    listing = db.query(Listing).filter(Listing.listing_id == body.listing_id).first()
    # Treat a cross-school listing as non-existent — isolation must hold even if a
    # listing_id is guessed, since opening a transaction reveals both identities.
    if not listing or listing.school_id != current_user.school_id:
        raise HTTPException(status_code=404, detail="Listing not found")
    if listing.seller_id == current_user.user_id:
        raise HTTPException(status_code=400, detail="Cannot open a transaction on your own listing")
    blocked_ids = get_blocked_user_ids(current_user.user_id, db)
    if listing.seller_id in blocked_ids:
        raise HTTPException(status_code=404, detail="Listing not found")
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
    current_user: User    = Depends(get_verified_user),
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
    current_user: User    = Depends(get_verified_user),
    db:           Session = Depends(get_db),
):
    txn = _get_or_404(txn_id, db)
    _assert_participant(txn, current_user)
    return txn


@router.put("/{txn_id}", response_model=TransactionResponse)
def update_transaction(
    txn_id:       str,
    body:         UpdateTransactionRequest,
    current_user: User    = Depends(get_verified_user),
    db:           Session = Depends(get_db),
):
    txn = _get_or_404(txn_id, db)
    _assert_participant(txn, current_user)

    if body.agreed_price is not None:
        # The price is only negotiable before it's locked; afterwards it's fixed.
        if txn.status != TxnStatus.negotiating:
            raise HTTPException(status_code=400, detail="Price can only be changed while negotiating")
        txn.agreed_price      = body.agreed_price
        txn.commission_amount = txn.compute_commission()

    if body.status is not None:
        _validate_transition(txn.status, body.status)
        if body.status == TxnStatus.price_locked:
            if txn.agreed_price is None:
                raise HTTPException(status_code=400, detail="Set an agreed price before locking the deal")
            # The buyer pays into escrow at lock, so the seller must be able to
            # receive a payout before the deal can lock. Skipped when Stripe
            # isn't configured (the app still runs without payments).
            if sc.is_configured() and not txn.seller.stripe_payouts_enabled:
                raise HTTPException(
                    status_code=400,
                    detail="The seller hasn't set up payouts yet — they need to finish Stripe onboarding before the price can be locked.",
                )
        txn.status = body.status

        if body.status == TxnStatus.price_locked:
            txn.price_locked_at = datetime.now(timezone.utc)
        elif body.status == TxnStatus.completed:
            txn.completed_at = datetime.now(timezone.utc)
            _on_completed(txn, db)
        elif body.status == TxnStatus.cancelled:
            _on_cancelled(txn, db)

    db.commit()
    db.refresh(txn)
    return txn


@router.post("/{txn_id}/payment-intent", response_model=PaymentIntentResponse)
def create_payment_intent(
    txn_id:       str,
    current_user: User    = Depends(get_verified_user),
    db:           Session = Depends(get_db),
):
    """Buyer-only: create (or resume) the Stripe PaymentIntent that funds escrow.

    The amount is computed server-side from the locked agreed_price — never taken
    from the client. Returns the client_secret the browser confirms with.
    """
    if not sc.is_configured():
        raise HTTPException(status_code=503, detail="Payments are not configured")

    txn = _get_or_404(txn_id, db)
    if current_user.user_id != txn.buyer_id:
        raise HTTPException(status_code=403, detail="Only the buyer can pay for this deal")
    if txn.status != TxnStatus.price_locked:
        raise HTTPException(status_code=400, detail="Lock in the price before paying")
    if txn.payment_status in (PaymentStatus.paid, PaymentStatus.released):
        raise HTTPException(status_code=400, detail="This deal has already been paid")
    if txn.agreed_price is None:
        raise HTTPException(status_code=400, detail="No agreed price on this deal")

    try:
        intent = _get_or_create_intent(txn)
    except stripe.error.StripeError as e:
        raise HTTPException(status_code=502, detail=f"Stripe error: {e.user_message or str(e)}")

    txn.stripe_payment_intent_id = intent.id
    if txn.payment_status == PaymentStatus.unpaid:
        txn.payment_status = PaymentStatus.processing
    db.commit()

    return PaymentIntentResponse(
        client_secret=intent.client_secret,
        publishable_key=settings.stripe_publishable_key,
        amount=txn.agreed_price,
    )


# ── helpers ───────────────────────────────────────────────────────────────────

def _get_or_create_intent(txn: Transaction) -> "stripe.PaymentIntent":
    """Reuse the transaction's PaymentIntent if it's still confirmable, else make
    a new one. Keeps a single live charge per deal."""
    _REUSABLE = {
        "requires_payment_method", "requires_confirmation",
        "requires_action", "processing",
    }
    if txn.stripe_payment_intent_id:
        existing = stripe.PaymentIntent.retrieve(txn.stripe_payment_intent_id)
        if existing.status in _REUSABLE:
            return existing
    return sc.create_payment_intent(sc.to_cents(txn.agreed_price), str(txn.transaction_id))

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
    """Side-effects when a transaction is marked complete.

    Releases the escrowed funds to the seller (minus commission), then updates
    reputation counters and marks the listing sold. Raising here before the
    caller's commit leaves the deal untouched if the payout can't be made.
    """
    _release_escrow(txn)

    # Increment transaction counter on both users
    for uid in (txn.buyer_id, txn.seller_id):
        user = db.query(User).filter(User.user_id == uid).first()
        if user:
            user.transactions_completed += 1

    # Mark the listing as sold
    listing = db.query(Listing).filter(Listing.listing_id == txn.listing_id).first()
    if listing:
        listing.status = ListingStatus.sold


def _release_escrow(txn: Transaction) -> None:
    """Transfer the held charge to the seller, retaining the commission.

    No-op when Stripe isn't configured (cash-only fallback) or the deal was
    already released. Requires the escrow to be funded first.
    """
    if not sc.is_configured() or txn.payment_status == PaymentStatus.released:
        return
    if txn.payment_status != PaymentStatus.paid:
        raise HTTPException(
            status_code=400,
            detail="The buyer must complete payment before the deal can be marked delivered",
        )

    seller = txn.seller
    payout = txn.agreed_price - (txn.commission_amount or txn.compute_commission() or 0)
    try:
        transfer = sc.create_transfer(
            amount_cents=sc.to_cents(payout),
            destination=seller.stripe_account_id,
            source_transaction=txn.stripe_charge_id,
            transaction_id=str(txn.transaction_id),
        )
    except stripe.error.StripeError as e:
        raise HTTPException(status_code=502, detail=f"Could not release payout: {e.user_message or str(e)}")

    txn.stripe_transfer_id = transfer.id
    txn.payment_status     = PaymentStatus.released
    txn.released_at        = datetime.now(timezone.utc)


def _on_cancelled(txn: Transaction, db: Session) -> None:
    """When a deal falls through, refund any escrowed payment to the buyer and
    release the listing back to the marketplace so it can take new offers."""
    _refund_escrow(txn)

    listing = db.query(Listing).filter(Listing.listing_id == txn.listing_id).first()
    if listing and listing.status == ListingStatus.in_negotiation:
        listing.status = ListingStatus.active


def _refund_escrow(txn: Transaction) -> None:
    """Refund the buyer if escrow was funded. No-op otherwise. Funds already
    released to the seller can't be auto-refunded — that's a manual dispute."""
    if not sc.is_configured() or txn.payment_status != PaymentStatus.paid:
        return
    if not txn.stripe_payment_intent_id:
        return
    try:
        sc.create_refund(txn.stripe_payment_intent_id, str(txn.transaction_id))
    except stripe.error.StripeError as e:
        raise HTTPException(status_code=502, detail=f"Could not refund the buyer: {e.user_message or str(e)}")
    txn.payment_status = PaymentStatus.refunded
