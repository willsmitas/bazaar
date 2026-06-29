"""
payments.py — Stripe Connect onboarding, client config, and the webhook.

The buyer's "create a PaymentIntent" action lives on the transactions router
(it's a transaction-scoped operation and reuses those helpers). Everything else
about money flow — seller onboarding, payout status, and Stripe's async events —
lives here.

See server/stripe_client.py for the escrow model these endpoints implement.
"""
from datetime import datetime, timezone
from decimal import Decimal

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from config import settings
from db.models import PaymentStatus, Transaction, TxnStatus, User
from server import stripe_client as sc
from server.dependencies import get_db, get_verified_user
from server.schemas import (
    ConnectStatusResponse,
    OnboardResponse,
    PaymentConfigResponse,
)

router = APIRouter(prefix="/payments", tags=["payments"])

# Default commission rate surfaced to the client for fee display. Mirrors the
# Transaction.commission_rate column default; the authoritative rate is still
# stored per-transaction.
_DEFAULT_COMMISSION_RATE = Decimal("0.0500")


@router.get("/config", response_model=PaymentConfigResponse)
def payment_config():
    """Public config the browser needs to render checkout. No auth — contains
    only the publishable key (safe to expose) and the commission rate."""
    return PaymentConfigResponse(
        publishable_key=settings.stripe_publishable_key,
        commission_rate=_DEFAULT_COMMISSION_RATE,
        payments_enabled=sc.is_configured(),
    )


@router.post("/connect/onboard", response_model=OnboardResponse)
def connect_onboard(
    current_user: User    = Depends(get_verified_user),
    db:           Session = Depends(get_db),
):
    """Start (or resume) Stripe Connect onboarding for the current user as a
    seller. Returns a hosted Stripe URL the client should redirect to."""
    if not sc.is_configured():
        raise HTTPException(status_code=503, detail="Payments are not configured")

    if not current_user.stripe_account_id:
        current_user.stripe_account_id = sc.create_express_account(current_user.email)
        db.commit()

    try:
        url = sc.create_account_link(current_user.stripe_account_id)
    except stripe.error.StripeError as e:
        raise HTTPException(status_code=502, detail=f"Stripe error: {e.user_message or str(e)}")
    return OnboardResponse(onboarding_url=url)


@router.get("/connect/status", response_model=ConnectStatusResponse)
def connect_status(
    current_user: User    = Depends(get_verified_user),
    db:           Session = Depends(get_db),
):
    """Whether the current user can receive payouts. Cheap to poll — reads the
    cached flag, which the account.updated webhook keeps fresh."""
    if not sc.is_configured() or not current_user.stripe_account_id:
        return ConnectStatusResponse(payouts_enabled=False, has_account=False)

    # Pull the live capability once here too, so a seller returning from
    # onboarding sees the right state without waiting on the webhook.
    enabled = sc.account_payouts_enabled(current_user.stripe_account_id)
    if enabled != current_user.stripe_payouts_enabled:
        current_user.stripe_payouts_enabled = enabled
        db.commit()
    return ConnectStatusResponse(payouts_enabled=enabled, has_account=True)


@router.post("/webhook", include_in_schema=False)
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    """Receive Stripe events. Signature-verified; never trusts the body blindly.

    Handled events:
      account.updated         → refresh a seller's payouts_enabled flag
      payment_intent.succeeded→ mark escrow funded, advance to pending_delivery
      charge.refunded         → mark the deal refunded (backstop for cancels)
    """
    if not settings.stripe_webhook_secret:
        raise HTTPException(status_code=503, detail="Webhook secret not configured")

    payload = await request.body()
    sig = request.headers.get("stripe-signature")
    try:
        event = sc.construct_event(payload, sig)
    except (ValueError, stripe.error.SignatureVerificationError):
        # Bad payload or forged/garbled signature.
        raise HTTPException(status_code=400, detail="Invalid webhook signature")

    obj = event["data"]["object"]
    etype = event["type"]

    if etype == "account.updated":
        _handle_account_updated(obj, db)
    elif etype == "payment_intent.succeeded":
        _handle_payment_succeeded(obj, db)
    elif etype == "charge.refunded":
        _handle_charge_refunded(obj, db)
    # Unhandled event types are acknowledged (200) and ignored.

    return {"received": True}


# ── webhook handlers ───────────────────────────────────────────────────────────

def _handle_account_updated(account: dict, db: Session) -> None:
    user = db.query(User).filter(User.stripe_account_id == account["id"]).first()
    if not user:
        return
    user.stripe_payouts_enabled = bool(
        account.get("payouts_enabled") and account.get("charges_enabled")
    )
    db.commit()


def _handle_payment_succeeded(intent: dict, db: Session) -> None:
    txn_id = (intent.get("metadata") or {}).get("transaction_id")
    if not txn_id:
        return
    txn = db.query(Transaction).filter(Transaction.transaction_id == txn_id).first()
    if not txn or txn.payment_status == PaymentStatus.paid:
        return  # unknown txn, or already processed (idempotent)

    txn.payment_status           = PaymentStatus.paid
    txn.paid_at                  = datetime.now(timezone.utc)
    txn.stripe_payment_intent_id = intent["id"]
    txn.stripe_charge_id         = intent.get("latest_charge")
    # Escrow is funded — move the deal forward to the meet-up step.
    if txn.status == TxnStatus.price_locked:
        txn.status = TxnStatus.pending_delivery
    db.commit()


def _handle_charge_refunded(charge: dict, db: Session) -> None:
    txn = db.query(Transaction).filter(
        Transaction.stripe_charge_id == charge["id"]
    ).first()
    if not txn or txn.payment_status == PaymentStatus.refunded:
        return
    txn.payment_status = PaymentStatus.refunded
    db.commit()
