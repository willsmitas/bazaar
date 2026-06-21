"""
schemas.py — Pydantic request/response models for every endpoint.

Response models never expose password_hash.
"""
import uuid
from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, EmailStr, ConfigDict, Field, field_validator

from db.models import (
    AccountStatus, AdminRole, ItemCondition, ListingStatus,
    ListingType, ReportStatus, TxnStatus,
)


# ── Auth ──────────────────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    email:      EmailStr
    full_name:  str
    password:   str
    university: Optional[str] = None


class LoginRequest(BaseModel):
    email:    EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token:  str
    refresh_token: str
    token_type:    str = "bearer"


class VerifyEmailRequest(BaseModel):
    code: str


class RefreshRequest(BaseModel):
    refresh_token: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    email:        EmailStr
    code:         str
    new_password: str


# ── School ────────────────────────────────────────────────────────────────────

class SchoolResponse(BaseModel):
    """Public-facing school record — drives per-school branding on the client."""
    model_config = ConfigDict(from_attributes=True)

    school_id:     uuid.UUID
    name:          str
    slug:          str
    email_domains: List[str]
    primary_color: str
    accent_color:  str
    emoji:         Optional[str]
    logo_url:      Optional[str]


# ── User ──────────────────────────────────────────────────────────────────────

class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id:                uuid.UUID
    email:                  str
    full_name:              str
    profile_picture_url:    Optional[str]
    bio:                    Optional[str]
    university:             Optional[str]
    school_id:              Optional[uuid.UUID] = None
    school:                 Optional[SchoolResponse] = None
    email_verified:         bool
    admin_role:             Optional[AdminRole] = None
    rating_avg:             Decimal
    rating_count:           int
    transactions_completed: int
    account_status:         AccountStatus
    created_at:             datetime


class PublicUserResponse(BaseModel):
    """Profile fields safe to expose to other users.

    Deliberately excludes email, is_admin, and account_status to preserve the
    app's anonymity model — identity beyond a display name is never public.
    """
    model_config = ConfigDict(from_attributes=True)

    user_id:                uuid.UUID
    full_name:              str
    profile_picture_url:    Optional[str]
    bio:                    Optional[str]
    university:             Optional[str]
    rating_avg:             Decimal
    rating_count:           int
    transactions_completed: int
    created_at:             datetime


class UpdateUserRequest(BaseModel):
    full_name:  Optional[str] = None
    bio:        Optional[str] = None
    # `university` is intentionally not editable — it mirrors the user's school
    # (set at registration) and must not drift from it.


# ── Listing ───────────────────────────────────────────────────────────────────

class CreateListingRequest(BaseModel):
    type:        ListingType             = ListingType.sell
    title:       str
    description: Optional[str]          = None
    category:    Optional[str]          = None
    condition:   Optional[ItemCondition] = None
    price_min:   Optional[Decimal]       = None
    price_max:   Optional[Decimal]       = None

    @field_validator("price_max")
    @classmethod
    def max_gte_min(cls, v: Optional[Decimal], info) -> Optional[Decimal]:
        mn = info.data.get("price_min")
        if v is not None and mn is not None and v < mn:
            raise ValueError("price_max must be >= price_min")
        return v


class UpdateListingRequest(BaseModel):
    title:       Optional[str]           = None
    description: Optional[str]           = None
    category:    Optional[str]           = None
    condition:   Optional[ItemCondition]  = None
    price_min:   Optional[Decimal]        = None
    price_max:   Optional[Decimal]        = None
    status:      Optional[ListingStatus]  = None


class ListingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    listing_id:    uuid.UUID
    seller_id:     uuid.UUID
    school_id:     Optional[uuid.UUID] = None
    type:          ListingType
    title:         str
    description:   Optional[str]
    category:      Optional[str]
    condition:     Optional[ItemCondition]
    price_min:     Optional[Decimal]
    price_max:     Optional[Decimal]
    thumbnail_url: Optional[str]
    image_urls:    Optional[List[str]]
    status:        ListingStatus
    view_count:    int
    created_at:    datetime
    expires_at:    Optional[datetime]


# ── Transaction ───────────────────────────────────────────────────────────────

class CreateTransactionRequest(BaseModel):
    listing_id: uuid.UUID


class UpdateTransactionRequest(BaseModel):
    agreed_price: Optional[Decimal]   = None
    status:       Optional[TxnStatus] = None


class TransactionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    transaction_id:    uuid.UUID
    listing_id:        uuid.UUID
    buyer_id:          uuid.UUID
    seller_id:         uuid.UUID
    agreed_price:      Optional[Decimal]
    commission_rate:   Decimal
    commission_amount: Optional[Decimal]
    status:            TxnStatus
    price_locked_at:   Optional[datetime]
    completed_at:      Optional[datetime]
    created_at:        datetime


# ── Chat & Messages ───────────────────────────────────────────────────────────

class ChatResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    chat_id:        uuid.UUID
    transaction_id: Optional[uuid.UUID]
    listing_id:     Optional[uuid.UUID]
    participant_1:  uuid.UUID
    participant_2:  uuid.UUID
    created_at:     datetime


class SendMessageRequest(BaseModel):
    content: str = Field(max_length=4000)

    @field_validator("content")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Message content cannot be empty")
        return v


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    message_id: uuid.UUID
    chat_id:    uuid.UUID
    sender_id:  uuid.UUID
    content:    str
    is_read:    bool
    sent_at:    datetime


# ── Rating ────────────────────────────────────────────────────────────────────

class CreateRatingRequest(BaseModel):
    transaction_id: uuid.UUID
    ratee_id:       uuid.UUID
    score:          int
    review:         Optional[str] = None

    @field_validator("score")
    @classmethod
    def score_range(cls, v: int) -> int:
        if not 1 <= v <= 5:
            raise ValueError("score must be between 1 and 5")
        return v


class RatingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    rating_id:      uuid.UUID
    transaction_id: uuid.UUID
    rater_id:       uuid.UUID
    ratee_id:       uuid.UUID
    score:          int
    review:         Optional[str]
    created_at:     datetime


# ── Report ────────────────────────────────────────────────────────────────────

class CreateReportRequest(BaseModel):
    reported_user_id:    Optional[uuid.UUID] = None
    reported_listing_id: Optional[uuid.UUID] = None
    reason:              str
    description:         Optional[str]       = None


class ReportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    report_id:           uuid.UUID
    reporter_id:         uuid.UUID
    reported_user_id:    Optional[uuid.UUID]
    reported_listing_id: Optional[uuid.UUID]
    reason:              str
    status:              ReportStatus
    created_at:          datetime


# ── Block ─────────────────────────────────────────────────────────────────────

class BlockResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    block_id:   uuid.UUID
    blocker_id: uuid.UUID
    blocked_id: uuid.UUID
    created_at: datetime


class BlockedUserResponse(BaseModel):
    """Block record with basic info about the blocked user."""
    model_config = ConfigDict(from_attributes=True)

    block_id:   uuid.UUID
    blocked_id: uuid.UUID
    created_at: datetime
    blocked_name: Optional[str] = None


# ── Admin / moderation ──────────────────────────────────────────────────────────

class ResolveReportRequest(BaseModel):
    status: ReportStatus   # reviewed | resolved | dismissed


class BanRequest(BaseModel):
    reason: Optional[str] = None


class SuspendRequest(BaseModel):
    days:   int = 7
    reason: Optional[str] = None

    @field_validator("days")
    @classmethod
    def _days_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("days must be >= 1")
        return v


class AdminUserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id:                uuid.UUID
    email:                  str
    full_name:              str
    school_id:              uuid.UUID
    account_status:         AccountStatus
    admin_role:             Optional[AdminRole] = None
    email_verified:         bool
    suspension_ends_at:     Optional[datetime]
    ban_reason:             Optional[str]
    transactions_completed: int
    created_at:             datetime
