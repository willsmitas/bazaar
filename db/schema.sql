-- =============================================================
--  Bazaar — PostgreSQL Schema
--  Run against any Postgres instance:
--    psql $DATABASE_URL -f db/schema.sql
-- =============================================================

-- UUID generation
CREATE EXTENSION IF NOT EXISTS "pgcrypto";


-- =============================================================
--  ENUM TYPES
-- =============================================================

CREATE TYPE account_status AS ENUM (
    'active',
    'suspended',   -- temporary; check suspension_ends_at
    'banned'       -- permanent
);

CREATE TYPE listing_status AS ENUM (
    'active',
    'in_negotiation',
    'sold',
    'expired',
    'removed'
);

CREATE TYPE listing_type AS ENUM (
    'sell',     -- user has an item to sell
    'request'   -- user wants to buy something
);

CREATE TYPE item_condition AS ENUM (
    'new',
    'like_new',
    'good',
    'fair'
);

CREATE TYPE txn_status AS ENUM (
    'negotiating',
    'price_locked',       -- both parties agreed; awaiting delivery
    'pending_delivery',
    'completed',          -- item delivered, payment transferred
    'disputed',
    'cancelled'
);

CREATE TYPE report_status AS ENUM (
    'pending',
    'reviewed',
    'resolved',
    'dismissed'
);

CREATE TYPE payment_status AS ENUM (
    'unpaid',       -- buyer hasn't paid yet
    'processing',   -- PaymentIntent created / confirming
    'paid',         -- captured to the platform, held in escrow
    'released',     -- transferred to the seller (minus commission)
    'refunded',     -- returned to the buyer
    'failed'        -- the charge did not go through
);

CREATE TYPE admin_role AS ENUM (
    'school_admin',   -- can moderate within own school only
    'global_admin'    -- can moderate across all schools
);


-- =============================================================
--  SCHOOLS  (tenants)
--  Each school is an isolated marketplace. Users are matched to a
--  school by their email domain at registration.
-- =============================================================

CREATE TABLE schools (
    school_id      UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    name           VARCHAR(255) NOT NULL UNIQUE,          -- 'Brown University'
    slug           VARCHAR(63)  NOT NULL UNIQUE,          -- 'brown' (URLs/subdomains)
    email_domains  TEXT[]       NOT NULL,                 -- {'brown.edu'}
    primary_color  VARCHAR(9)   NOT NULL DEFAULT '#4E3629',
    accent_color   VARCHAR(9)   NOT NULL DEFAULT '#9E7E38',
    emoji          VARCHAR(16),                           -- '🐻'
    logo_url       TEXT,
    is_active      BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);


-- =============================================================
--  USERS
-- =============================================================

CREATE TABLE users (
    user_id               UUID         PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Identity
    email                 VARCHAR(255) NOT NULL UNIQUE,
    full_name             VARCHAR(255) NOT NULL,
    password_hash         VARCHAR(255) NOT NULL,
    profile_picture_url   TEXT,
    bio                   TEXT,
    university            VARCHAR(255),          -- display name; mirrors schools.name
    school_id             UUID         NOT NULL REFERENCES schools(school_id),
    email_verified        BOOLEAN      NOT NULL DEFAULT FALSE,
    admin_role            admin_role,                          -- NULL = regular user

    -- One-time codes (NULLed after use)
    verification_code       VARCHAR(6),
    verification_code_exp   TIMESTAMPTZ,
    password_reset_code     VARCHAR(6),
    password_reset_code_exp TIMESTAMPTZ,

    -- Reputation (cached; recomputed from ratings table)
    rating_avg            DECIMAL(3,2) NOT NULL DEFAULT 0.00
                              CHECK (rating_avg BETWEEN 0.00 AND 5.00),
    rating_count          INTEGER      NOT NULL DEFAULT 0,
    transactions_completed INTEGER     NOT NULL DEFAULT 0,

    -- Account moderation
    account_status        account_status NOT NULL DEFAULT 'active',
    suspension_ends_at    TIMESTAMPTZ,           -- NULL unless suspended
    ban_reason            TEXT,                  -- admin note

    -- Payments — seller's Stripe Connect (Express) account for receiving payouts.
    stripe_account_id      TEXT,
    stripe_payouts_enabled BOOLEAN NOT NULL DEFAULT FALSE,  -- mirrors Stripe; set by webhook

    -- Timestamps
    created_at            TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    last_active_at        TIMESTAMPTZ
);


-- =============================================================
--  LISTINGS
--  One row per item posted (either for sale or as a request).
-- =============================================================

CREATE TABLE listings (
    listing_id   UUID           PRIMARY KEY DEFAULT gen_random_uuid(),
    seller_id    UUID           NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    -- Denormalized from the seller's school so browse can scope in one indexed filter.
    school_id    UUID           NOT NULL REFERENCES schools(school_id),

    type         listing_type   NOT NULL DEFAULT 'sell',
    title        VARCHAR(255)   NOT NULL,
    description  TEXT,
    category     VARCHAR(100),
    condition    item_condition,

    -- Seller names a range; final price is agreed in chat
    price_min    DECIMAL(10,2)  CHECK (price_min >= 0),
    price_max    DECIMAL(10,2)  CHECK (price_max >= price_min),

    -- Images are stored as object-storage URLs only; binary data is never written to the DB.
    thumbnail_url TEXT,          -- primary display image (first shown in listing cards)
    image_urls    TEXT[],        -- full gallery (additional object-storage URLs)

    status       listing_status NOT NULL DEFAULT 'active',
    view_count   INTEGER        NOT NULL DEFAULT 0,

    created_at   TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
    expires_at   TIMESTAMPTZ    DEFAULT (NOW() + INTERVAL '30 days')
);


-- =============================================================
--  TRANSACTIONS
--  One row per deal, from first contact through delivery.
-- =============================================================

CREATE TABLE transactions (
    transaction_id    UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    listing_id        UUID         NOT NULL REFERENCES listings(listing_id),
    buyer_id          UUID         NOT NULL REFERENCES users(user_id),
    seller_id         UUID         NOT NULL REFERENCES users(user_id),

    agreed_price      DECIMAL(10,2) CHECK (agreed_price >= 0),
    commission_rate   DECIMAL(5,4)  NOT NULL DEFAULT 0.0500,  -- 5%; change as needed
    commission_amount DECIMAL(10,2),                          -- agreed_price * commission_rate

    status            txn_status    NOT NULL DEFAULT 'negotiating',
    price_locked_at   TIMESTAMPTZ,   -- set when both parties lock the price
    completed_at      TIMESTAMPTZ,   -- set on successful delivery

    -- Payments — escrow via Stripe Connect (separate charges & transfers).
    payment_status           payment_status NOT NULL DEFAULT 'unpaid',
    stripe_payment_intent_id TEXT,          -- buyer's charge, held on the platform
    stripe_charge_id         TEXT,          -- the charge backing the PaymentIntent (transfer source)
    stripe_transfer_id       TEXT,          -- payout to the seller on release
    paid_at                  TIMESTAMPTZ,   -- escrow funded
    released_at              TIMESTAMPTZ,   -- transferred to the seller

    created_at        TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ   NOT NULL DEFAULT NOW(),

    CHECK (buyer_id <> seller_id)
);


-- =============================================================
--  CHATS & MESSAGES
--  Each transaction has one chat thread.
-- =============================================================

CREATE TABLE chats (
    chat_id        UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    transaction_id UUID        REFERENCES transactions(transaction_id) ON DELETE SET NULL,
    listing_id     UUID        REFERENCES listings(listing_id),
    participant_1  UUID        NOT NULL REFERENCES users(user_id),
    participant_2  UUID        NOT NULL REFERENCES users(user_id),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CHECK (participant_1 <> participant_2)
);

CREATE TABLE messages (
    message_id UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    chat_id    UUID        NOT NULL REFERENCES chats(chat_id) ON DELETE CASCADE,
    sender_id  UUID        NOT NULL REFERENCES users(user_id),
    content    TEXT        NOT NULL,
    is_read    BOOLEAN     NOT NULL DEFAULT FALSE,
    sent_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


-- =============================================================
--  RATINGS
--  After a transaction completes, both sides can leave a rating.
-- =============================================================

CREATE TABLE ratings (
    rating_id      UUID    PRIMARY KEY DEFAULT gen_random_uuid(),
    transaction_id UUID    NOT NULL REFERENCES transactions(transaction_id),
    rater_id       UUID    NOT NULL REFERENCES users(user_id),
    ratee_id       UUID    NOT NULL REFERENCES users(user_id),
    score          INTEGER NOT NULL CHECK (score BETWEEN 1 AND 5),
    review         TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (transaction_id, rater_id),   -- one rating per side per deal
    CHECK  (rater_id <> ratee_id)
);


-- =============================================================
--  REPORTS  (moderation)
--  Users can report other users or individual listings.
-- =============================================================

CREATE TABLE reports (
    report_id           UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    reporter_id         UUID          NOT NULL REFERENCES users(user_id),
    reported_user_id    UUID          REFERENCES users(user_id),
    reported_listing_id UUID          REFERENCES listings(listing_id),
    reason              VARCHAR(100)  NOT NULL,
    description         TEXT,
    status              report_status NOT NULL DEFAULT 'pending',
    created_at          TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    resolved_at         TIMESTAMPTZ,

    -- Must target a user, a listing, or both
    CHECK (reported_user_id IS NOT NULL OR reported_listing_id IS NOT NULL)
);


-- =============================================================
--  BLOCKS
--  If A blocks B, neither sees the other's listings and neither
--  can initiate new transactions or send messages to the other.
-- =============================================================

CREATE TABLE blocks (
    block_id   UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    blocker_id UUID        NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    blocked_id UUID        NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (blocker_id, blocked_id),
    CHECK  (blocker_id <> blocked_id)
);


-- =============================================================
--  INDEXES
-- =============================================================

CREATE INDEX idx_schools_email_domains ON schools USING GIN (email_domains);

CREATE INDEX idx_users_email          ON users(email);
CREATE INDEX idx_users_university     ON users(university);
CREATE INDEX idx_users_status         ON users(account_status);
CREATE INDEX idx_users_school         ON users(school_id);

CREATE INDEX idx_listings_seller      ON listings(seller_id);
CREATE INDEX idx_listings_status      ON listings(status);
CREATE INDEX idx_listings_category    ON listings(category);
CREATE INDEX idx_listings_type        ON listings(type);
-- Primary browse query: active listings for one school, newest first.
CREATE INDEX idx_listings_school_status ON listings(school_id, status, created_at);

CREATE INDEX idx_txns_buyer           ON transactions(buyer_id);
CREATE INDEX idx_txns_seller          ON transactions(seller_id);
CREATE INDEX idx_txns_listing         ON transactions(listing_id);
CREATE INDEX idx_txns_status          ON transactions(status);
CREATE INDEX idx_txns_payment_status  ON transactions(payment_status);

CREATE INDEX idx_msgs_chat            ON messages(chat_id);
CREATE INDEX idx_msgs_sent_at         ON messages(sent_at DESC);
CREATE INDEX idx_msgs_unread          ON messages(chat_id) WHERE is_read = FALSE;

CREATE INDEX idx_ratings_ratee        ON ratings(ratee_id);

-- Both directions are queried: "who have I blocked" and "who has blocked me".
CREATE INDEX idx_blocks_blocker       ON blocks(blocker_id);
CREATE INDEX idx_blocks_blocked       ON blocks(blocked_id);
CREATE INDEX idx_reports_status       ON reports(status) WHERE status = 'pending';


-- =============================================================
--  AUTO-UPDATE updated_at
-- =============================================================

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_schools_updated_at
    BEFORE UPDATE ON schools
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_listings_updated_at
    BEFORE UPDATE ON listings
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_txns_updated_at
    BEFORE UPDATE ON transactions
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
