"""
migrate_add_stripe.py — Stripe payments migration.

Brings an EXISTING database up to the payments schema:

  1. Creates the `payment_status` ENUM type.
  2. Adds `stripe_account_id` + `stripe_payouts_enabled` to `users`.
  3. Adds the payment columns to `transactions`
     (payment_status, stripe_payment_intent_id, stripe_charge_id,
      stripe_transfer_id, paid_at, released_at) + an index on payment_status.

Idempotent: safe to run more than once. Postgres has no
`CREATE TYPE IF NOT EXISTS`, so the enum is created inside a DO block that
swallows the duplicate_object error; columns use `ADD COLUMN IF NOT EXISTS`.

    python -m db.migrate_add_stripe

Fresh databases created from schema.sql / `python -m db.init_db` already have
this shape and don't need it.
"""
from sqlalchemy import text

from db.database import engine


def main() -> None:
    print(f"Connecting to: {engine.url}")

    # A single transaction: either the whole migration applies or none of it.
    with engine.begin() as conn:
        # 1. payment_status enum type -----------------------------------------
        conn.execute(text("""
            DO $$ BEGIN
                CREATE TYPE payment_status AS ENUM (
                    'unpaid', 'processing', 'paid', 'released', 'refunded', 'failed'
                );
            EXCEPTION WHEN duplicate_object THEN NULL;
            END $$;
        """))

        # 2. users: seller Connect account ------------------------------------
        conn.execute(text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS stripe_account_id TEXT"
        ))
        conn.execute(text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS "
            "stripe_payouts_enabled BOOLEAN NOT NULL DEFAULT FALSE"
        ))

        # 3. transactions: escrow payment columns -----------------------------
        conn.execute(text(
            "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS "
            "payment_status payment_status NOT NULL DEFAULT 'unpaid'"
        ))
        for col in (
            "stripe_payment_intent_id TEXT",
            "stripe_charge_id TEXT",
            "stripe_transfer_id TEXT",
            "paid_at TIMESTAMPTZ",
            "released_at TIMESTAMPTZ",
        ):
            conn.execute(text(f"ALTER TABLE transactions ADD COLUMN IF NOT EXISTS {col}"))

        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_txns_payment_status "
            "ON transactions(payment_status)"
        ))

    print("Migration complete — Stripe payment columns added.")


if __name__ == "__main__":
    main()
