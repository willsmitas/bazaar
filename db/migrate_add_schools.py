"""
migrate_add_schools.py — Multi-tenant migration (Path A, steps 1-3).

Brings an EXISTING database up to the multi-school schema:

  1. Creates the `schools` table (+ GIN index on email_domains).
  2. Seeds the Brown University school row.
  3. Adds `school_id` to `users` and `listings` (nullable at first).
  4. Backfills every existing user and listing to Brown.
  5. Enforces NOT NULL + creates the browse/lookup indexes.

Idempotent: safe to run more than once (uses IF NOT EXISTS / ON CONFLICT and
only sets NOT NULL once no NULLs remain). Fresh databases created from
schema.sql or `python -m db.init_db` already have this shape — for those, run
`python -m db.seed` (which seeds Brown) instead.

    python -m db.migrate_add_schools

Adjust the SEED_* values below before running for a different first school.
"""
from sqlalchemy import text

from db.database import engine

# The school every pre-existing row belongs to. Until now, registration was
# gated to brown.edu, so all existing users (and their listings) are Brown.
SEED_NAME          = "Brown University"
SEED_SLUG          = "brown"
SEED_EMAIL_DOMAINS = ["brown.edu"]
SEED_PRIMARY_COLOR = "#4E3629"
SEED_ACCENT_COLOR  = "#9E7E38"
SEED_EMOJI         = "🐻"


def main() -> None:
    print(f"Connecting to: {engine.url}")

    # A single transaction: either the whole migration applies or none of it.
    with engine.begin() as conn:
        # 1. schools table -----------------------------------------------------
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS schools (
                school_id      UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
                name           VARCHAR(255) NOT NULL UNIQUE,
                slug           VARCHAR(63)  NOT NULL UNIQUE,
                email_domains  TEXT[]       NOT NULL,
                primary_color  VARCHAR(9)   NOT NULL DEFAULT '#4E3629',
                accent_color   VARCHAR(9)   NOT NULL DEFAULT '#9E7E38',
                emoji          VARCHAR(16),
                logo_url       TEXT,
                is_active      BOOLEAN      NOT NULL DEFAULT TRUE,
                created_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
                updated_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW()
            )
        """))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_schools_email_domains "
            "ON schools USING GIN (email_domains)"
        ))

        # 2. seed the first school --------------------------------------------
        conn.execute(
            text("""
                INSERT INTO schools (name, slug, email_domains, primary_color, accent_color, emoji)
                VALUES (:name, :slug, :domains, :primary, :accent, :emoji)
                ON CONFLICT (slug) DO NOTHING
            """),
            {
                "name":    SEED_NAME,
                "slug":    SEED_SLUG,
                "domains": SEED_EMAIL_DOMAINS,
                "primary": SEED_PRIMARY_COLOR,
                "accent":  SEED_ACCENT_COLOR,
                "emoji":   SEED_EMOJI,
            },
        )

        # 3. add nullable school_id columns -----------------------------------
        conn.execute(text(
            "ALTER TABLE users    ADD COLUMN IF NOT EXISTS school_id UUID REFERENCES schools(school_id)"
        ))
        conn.execute(text(
            "ALTER TABLE listings ADD COLUMN IF NOT EXISTS school_id UUID REFERENCES schools(school_id)"
        ))

        # 4. backfill ----------------------------------------------------------
        # Every existing user → the seed school; every listing → its seller's school.
        conn.execute(
            text("UPDATE users SET school_id = (SELECT school_id FROM schools WHERE slug = :slug) "
                 "WHERE school_id IS NULL"),
            {"slug": SEED_SLUG},
        )
        conn.execute(text("""
            UPDATE listings l
               SET school_id = u.school_id
              FROM users u
             WHERE u.user_id = l.seller_id
               AND l.school_id IS NULL
        """))

        # 5. enforce NOT NULL + indexes (safe now that backfill is complete) ---
        conn.execute(text("ALTER TABLE users    ALTER COLUMN school_id SET NOT NULL"))
        conn.execute(text("ALTER TABLE listings ALTER COLUMN school_id SET NOT NULL"))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_users_school ON users(school_id)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_listings_school_status "
            "ON listings(school_id, status, created_at)"
        ))

    print(f"Migration complete — all existing rows assigned to {SEED_NAME!r}.")


if __name__ == "__main__":
    main()
