"""
stripe_client.py — thin wrapper around the Stripe SDK for Bazaar.

Centralizes Stripe configuration and the handful of operations the app needs so
the routers stay free of SDK details (mirrors storage.py / email.py).

Escrow model (Stripe Connect, separate charges & transfers):
  • Sellers onboard an Express connected account (KYC via a hosted Account Link).
  • The buyer's PaymentIntent is charged to the PLATFORM and held — no
    transfer_data, so funds are NOT auto-forwarded to the seller.
  • On delivery the held charge is released to the seller with a Transfer whose
    source_transaction is that charge; the platform keeps the commission.
  • A cancelled/disputed deal refunds the PaymentIntent.

All amounts crossing this boundary are integer CENTS (Stripe's unit). When
STRIPE_SECRET_KEY is unset, is_configured() is False and callers should return a
503 — Bazaar runs fine without payments configured.
"""
from decimal import Decimal
from typing import Optional

import stripe

from config import settings

stripe.api_key = settings.stripe_secret_key or None


def is_configured() -> bool:
    """True when a Stripe secret key is set (payments are usable)."""
    return bool(settings.stripe_secret_key)


def to_cents(amount: Decimal) -> int:
    """Convert a dollar Decimal to integer cents for the Stripe API."""
    return int((amount * 100).quantize(Decimal("1")))


# ── Connect onboarding (sellers) ───────────────────────────────────────────────

def create_express_account(email: str) -> str:
    """Create a Stripe Connect Express account and return its id."""
    account = stripe.Account.create(
        type="express",
        email=email,
        capabilities={"transfers": {"requested": True}},
        business_type="individual",
        metadata={"app": "bazaar"},
    )
    return account.id


def create_account_link(account_id: str) -> str:
    """Hosted onboarding/KYC URL for a connected account.

    Both URLs route back into the app; refresh_url is hit if the link expires
    before the seller finishes, return_url after they complete the flow.
    """
    base = settings.public_base_url.rstrip("/")
    link = stripe.AccountLink.create(
        account=account_id,
        refresh_url=f"{base}/?stripe_onboard=refresh",
        return_url=f"{base}/?stripe_onboard=done",
        type="account_onboarding",
    )
    return link.url


def account_payouts_enabled(account_id: str) -> bool:
    """Whether a connected account can receive transfers/payouts right now."""
    acct = stripe.Account.retrieve(account_id)
    return bool(acct.payouts_enabled and acct.charges_enabled)


# ── Buyer payment (escrow) ─────────────────────────────────────────────────────

def create_payment_intent(amount_cents: int, transaction_id: str) -> stripe.PaymentIntent:
    """Charge the buyer to the platform balance (held, not forwarded).

    Idempotency-keyed on the transaction so a retried request returns the same
    PaymentIntent rather than creating a duplicate charge.
    """
    return stripe.PaymentIntent.create(
        amount=amount_cents,
        currency="usd",
        automatic_payment_methods={"enabled": True},
        metadata={"transaction_id": transaction_id, "app": "bazaar"},
        idempotency_key=f"pi_{transaction_id}",
    )


# ── Release / refund ───────────────────────────────────────────────────────────

def create_transfer(amount_cents: int, destination: str, source_transaction: str,
                    transaction_id: str) -> stripe.Transfer:
    """Release held funds to the seller's connected account.

    source_transaction ties the transfer to the specific held charge, so it only
    draws from those funds (no reliance on aggregate platform balance/timing).
    """
    return stripe.Transfer.create(
        amount=amount_cents,
        currency="usd",
        destination=destination,
        source_transaction=source_transaction,
        metadata={"transaction_id": transaction_id, "app": "bazaar"},
        idempotency_key=f"tr_{transaction_id}",
    )


def create_refund(payment_intent_id: str, transaction_id: str) -> stripe.Refund:
    """Refund the buyer's held charge (deal cancelled/disputed)."""
    return stripe.Refund.create(
        payment_intent=payment_intent_id,
        metadata={"transaction_id": transaction_id, "app": "bazaar"},
        idempotency_key=f"rf_{transaction_id}",
    )


# ── Webhooks ───────────────────────────────────────────────────────────────────

def construct_event(payload: bytes, sig_header: Optional[str]) -> stripe.Event:
    """Verify a webhook's signature and return the parsed event.

    Raises stripe.error.SignatureVerificationError (or ValueError) on a bad/missing
    signature — callers turn that into a 400 so forged events are rejected.
    """
    return stripe.Webhook.construct_event(
        payload, sig_header, settings.stripe_webhook_secret
    )
