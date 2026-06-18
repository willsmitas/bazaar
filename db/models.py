"""
models.py — SQLAlchemy ORM models for Bazaar.

Each class maps 1-to-1 with a table in schema.sql.
"""
import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import (
    TIMESTAMP, Boolean, CheckConstraint, ForeignKey, Integer,
    Numeric, String, Text, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base

# SQLAlchemy has no "TIMESTAMPTZ" name; the generic TIMESTAMP with timezone=True
# compiles to "TIMESTAMP WITH TIME ZONE" (i.e. timestamptz) on PostgreSQL.
TIMESTAMPTZ = TIMESTAMP(timezone=True)


# =============================================================
#  Python enums (mirror the SQL ENUM types)
# =============================================================

class AccountStatus(str, enum.Enum):
    active    = "active"
    suspended = "suspended"
    banned    = "banned"


class ListingStatus(str, enum.Enum):
    active         = "active"
    in_negotiation = "in_negotiation"
    sold           = "sold"
    expired        = "expired"
    removed        = "removed"


class ListingType(str, enum.Enum):
    sell    = "sell"
    request = "request"


class ItemCondition(str, enum.Enum):
    new      = "new"
    like_new = "like_new"
    good     = "good"
    fair     = "fair"


class TxnStatus(str, enum.Enum):
    negotiating      = "negotiating"
    price_locked     = "price_locked"
    pending_delivery = "pending_delivery"
    completed        = "completed"
    disputed         = "disputed"
    cancelled        = "cancelled"


class ReportStatus(str, enum.Enum):
    pending   = "pending"
    reviewed  = "reviewed"
    resolved  = "resolved"
    dismissed = "dismissed"


# =============================================================
#  USER
# =============================================================

class User(Base):
    __tablename__ = "users"

    user_id               : Mapped[uuid.UUID]          = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Identity
    email                 : Mapped[str]                = mapped_column(String(255), nullable=False, unique=True)
    full_name             : Mapped[str]                = mapped_column(String(255), nullable=False)
    password_hash         : Mapped[str]                = mapped_column(String(255), nullable=False)
    profile_picture_url   : Mapped[Optional[str]]      = mapped_column(Text)
    bio                   : Mapped[Optional[str]]      = mapped_column(Text)
    university            : Mapped[Optional[str]]      = mapped_column(String(255))
    email_verified        : Mapped[bool]               = mapped_column(Boolean, nullable=False, default=False)
    is_admin              : Mapped[bool]               = mapped_column(Boolean, nullable=False, default=False)

    # One-time codes (cleared after use)
    verification_code     : Mapped[Optional[str]]      = mapped_column(String(6))
    verification_code_exp : Mapped[Optional[datetime]] = mapped_column(TIMESTAMPTZ)
    password_reset_code   : Mapped[Optional[str]]      = mapped_column(String(6))
    password_reset_code_exp: Mapped[Optional[datetime]] = mapped_column(TIMESTAMPTZ)

    # Reputation
    rating_avg            : Mapped[Decimal]            = mapped_column(Numeric(3, 2), nullable=False, default=Decimal("0.00"))
    rating_count          : Mapped[int]                = mapped_column(Integer, nullable=False, default=0)
    transactions_completed: Mapped[int]                = mapped_column(Integer, nullable=False, default=0)

    # Account moderation
    account_status        : Mapped[AccountStatus]      = mapped_column(
        String(20), nullable=False, default=AccountStatus.active
    )
    suspension_ends_at    : Mapped[Optional[datetime]] = mapped_column(TIMESTAMPTZ)
    ban_reason            : Mapped[Optional[str]]      = mapped_column(Text)

    # Timestamps
    created_at            : Mapped[datetime]           = mapped_column(TIMESTAMPTZ, nullable=False, server_default=func.now())
    updated_at            : Mapped[datetime]           = mapped_column(TIMESTAMPTZ, nullable=False, server_default=func.now(), onupdate=func.now())
    last_active_at        : Mapped[Optional[datetime]] = mapped_column(TIMESTAMPTZ)

    # Relationships
    listings         : Mapped[List["Listing"]] = relationship("Listing", back_populates="seller", cascade="all, delete-orphan")
    ratings_received : Mapped[List["Rating"]]  = relationship("Rating", foreign_keys="[Rating.ratee_id]", back_populates="ratee")

    @property
    def is_active(self) -> bool:
        return self.account_status == AccountStatus.active

    def __repr__(self) -> str:
        return f"<User {self.email!r}>"


# =============================================================
#  LISTING
# =============================================================

class Listing(Base):
    __tablename__ = "listings"

    listing_id  : Mapped[uuid.UUID]               = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    seller_id   : Mapped[uuid.UUID]               = mapped_column(ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False)

    type        : Mapped[ListingType]             = mapped_column(String(20), nullable=False, default=ListingType.sell)
    title       : Mapped[str]                     = mapped_column(String(255), nullable=False)
    description : Mapped[Optional[str]]           = mapped_column(Text)
    category    : Mapped[Optional[str]]           = mapped_column(String(100))
    condition   : Mapped[Optional[ItemCondition]] = mapped_column(String(20))

    price_min   : Mapped[Optional[Decimal]]       = mapped_column(Numeric(10, 2))
    price_max   : Mapped[Optional[Decimal]]       = mapped_column(Numeric(10, 2))
    thumbnail_url : Mapped[Optional[str]]           = mapped_column(Text)
    image_urls    : Mapped[Optional[List[str]]]     = mapped_column(ARRAY(Text))

    status      : Mapped[ListingStatus]           = mapped_column(String(25), nullable=False, default=ListingStatus.active)
    view_count  : Mapped[int]                     = mapped_column(Integer, nullable=False, default=0)

    created_at  : Mapped[datetime]                = mapped_column(TIMESTAMPTZ, nullable=False, server_default=func.now())
    updated_at  : Mapped[datetime]                = mapped_column(TIMESTAMPTZ, nullable=False, server_default=func.now(), onupdate=func.now())
    expires_at  : Mapped[Optional[datetime]]      = mapped_column(TIMESTAMPTZ)

    __table_args__ = (
        CheckConstraint("price_min >= 0",         name="ck_price_min_positive"),
        CheckConstraint("price_max >= price_min", name="ck_price_range_valid"),
    )

    seller       : Mapped["User"]             = relationship("User", back_populates="listings")
    transactions : Mapped[List["Transaction"]] = relationship("Transaction", back_populates="listing")

    def __repr__(self) -> str:
        return f"<Listing {self.title!r} ({self.status})>"


# =============================================================
#  TRANSACTION
# =============================================================

class Transaction(Base):
    __tablename__ = "transactions"

    transaction_id    : Mapped[uuid.UUID]          = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    listing_id        : Mapped[uuid.UUID]          = mapped_column(ForeignKey("listings.listing_id"), nullable=False)
    buyer_id          : Mapped[uuid.UUID]          = mapped_column(ForeignKey("users.user_id"), nullable=False)
    seller_id         : Mapped[uuid.UUID]          = mapped_column(ForeignKey("users.user_id"), nullable=False)

    agreed_price      : Mapped[Optional[Decimal]]  = mapped_column(Numeric(10, 2))
    commission_rate   : Mapped[Decimal]            = mapped_column(Numeric(5, 4), nullable=False, default=Decimal("0.0500"))
    commission_amount : Mapped[Optional[Decimal]]  = mapped_column(Numeric(10, 2))

    status            : Mapped[TxnStatus]          = mapped_column(String(25), nullable=False, default=TxnStatus.negotiating)
    price_locked_at   : Mapped[Optional[datetime]] = mapped_column(TIMESTAMPTZ)
    completed_at      : Mapped[Optional[datetime]] = mapped_column(TIMESTAMPTZ)

    created_at        : Mapped[datetime]           = mapped_column(TIMESTAMPTZ, nullable=False, server_default=func.now())
    updated_at        : Mapped[datetime]           = mapped_column(TIMESTAMPTZ, nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint("buyer_id <> seller_id", name="ck_buyer_ne_seller"),
        CheckConstraint("agreed_price >= 0",     name="ck_agreed_price_positive"),
    )

    listing : Mapped["Listing"]           = relationship("Listing", back_populates="transactions")
    buyer   : Mapped["User"]              = relationship("User", foreign_keys="[Transaction.buyer_id]")
    seller  : Mapped["User"]              = relationship("User", foreign_keys="[Transaction.seller_id]")
    chat    : Mapped[Optional["Chat"]]    = relationship("Chat", back_populates="transaction", uselist=False)
    ratings : Mapped[List["Rating"]]      = relationship("Rating", back_populates="transaction")

    def compute_commission(self) -> Optional[Decimal]:
        if self.agreed_price is not None:
            return (self.agreed_price * self.commission_rate).quantize(Decimal("0.01"))
        return None

    def __repr__(self) -> str:
        return f"<Transaction {self.transaction_id} ({self.status})>"


# =============================================================
#  CHAT & MESSAGES
# =============================================================

class Chat(Base):
    __tablename__ = "chats"

    chat_id        : Mapped[uuid.UUID]           = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    transaction_id : Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("transactions.transaction_id", ondelete="SET NULL"))
    listing_id     : Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("listings.listing_id"))
    participant_1  : Mapped[uuid.UUID]           = mapped_column(ForeignKey("users.user_id"), nullable=False)
    participant_2  : Mapped[uuid.UUID]           = mapped_column(ForeignKey("users.user_id"), nullable=False)
    created_at     : Mapped[datetime]            = mapped_column(TIMESTAMPTZ, nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint("participant_1 <> participant_2", name="ck_different_participants"),
    )

    transaction : Mapped[Optional["Transaction"]] = relationship("Transaction", back_populates="chat")
    messages    : Mapped[List["Message"]]         = relationship(
        "Message", back_populates="chat", cascade="all, delete-orphan",
        order_by="Message.sent_at",
    )

    def __repr__(self) -> str:
        return f"<Chat {self.chat_id}>"


class Message(Base):
    __tablename__ = "messages"

    message_id : Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    chat_id    : Mapped[uuid.UUID] = mapped_column(ForeignKey("chats.chat_id", ondelete="CASCADE"), nullable=False)
    sender_id  : Mapped[uuid.UUID] = mapped_column(ForeignKey("users.user_id"), nullable=False)
    content    : Mapped[str]       = mapped_column(Text, nullable=False)
    is_read    : Mapped[bool]      = mapped_column(Boolean, nullable=False, default=False)
    sent_at    : Mapped[datetime]  = mapped_column(TIMESTAMPTZ, nullable=False, server_default=func.now())

    chat   : Mapped["Chat"] = relationship("Chat", back_populates="messages")
    sender : Mapped["User"] = relationship("User", foreign_keys="[Message.sender_id]")

    def __repr__(self) -> str:
        return f"<Message {self.message_id} from {self.sender_id}>"


# =============================================================
#  RATINGS
# =============================================================

class Rating(Base):
    __tablename__ = "ratings"

    rating_id      : Mapped[uuid.UUID]     = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    transaction_id : Mapped[uuid.UUID]     = mapped_column(ForeignKey("transactions.transaction_id"), nullable=False)
    rater_id       : Mapped[uuid.UUID]     = mapped_column(ForeignKey("users.user_id"), nullable=False)
    ratee_id       : Mapped[uuid.UUID]     = mapped_column(ForeignKey("users.user_id"), nullable=False)
    score          : Mapped[int]           = mapped_column(Integer, nullable=False)
    review         : Mapped[Optional[str]] = mapped_column(Text)
    created_at     : Mapped[datetime]      = mapped_column(TIMESTAMPTZ, nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint("score BETWEEN 1 AND 5",  name="ck_score_range"),
        CheckConstraint("rater_id <> ratee_id",   name="ck_no_self_rating"),
        UniqueConstraint("transaction_id", "rater_id", name="uq_one_rating_per_txn"),
    )

    transaction : Mapped["Transaction"] = relationship("Transaction", back_populates="ratings")
    rater       : Mapped["User"]        = relationship("User", foreign_keys="[Rating.rater_id]")
    ratee       : Mapped["User"]        = relationship("User", foreign_keys="[Rating.ratee_id]", back_populates="ratings_received")

    def __repr__(self) -> str:
        return f"<Rating {self.score}/5 on txn {self.transaction_id}>"


# =============================================================
#  REPORTS  (moderation)
# =============================================================

class Report(Base):
    __tablename__ = "reports"

    report_id           : Mapped[uuid.UUID]           = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    reporter_id         : Mapped[uuid.UUID]           = mapped_column(ForeignKey("users.user_id"), nullable=False)
    reported_user_id    : Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.user_id"))
    reported_listing_id : Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("listings.listing_id"))
    reason              : Mapped[str]                 = mapped_column(String(100), nullable=False)
    description         : Mapped[Optional[str]]       = mapped_column(Text)
    status              : Mapped[ReportStatus]        = mapped_column(String(20), nullable=False, default=ReportStatus.pending)
    created_at          : Mapped[datetime]            = mapped_column(TIMESTAMPTZ, nullable=False, server_default=func.now())
    resolved_at         : Mapped[Optional[datetime]]  = mapped_column(TIMESTAMPTZ)

    __table_args__ = (
        CheckConstraint(
            "reported_user_id IS NOT NULL OR reported_listing_id IS NOT NULL",
            name="ck_report_has_target",
        ),
    )

    reporter      : Mapped["User"]          = relationship("User", foreign_keys="[Report.reporter_id]")
    reported_user : Mapped[Optional["User"]] = relationship("User", foreign_keys="[Report.reported_user_id]")

    def __repr__(self) -> str:
        return f"<Report {self.report_id} ({self.status})>"
