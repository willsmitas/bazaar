"""
migrate_admin_roles.py — Replace is_admin boolean with admin_role enum.

Brings an existing database forward from the single boolean `is_admin` to the
two-tier `admin_role` column ('school_admin' | 'global_admin' | NULL).

Existing admins (is_admin = TRUE) are migrated to 'global_admin', since the
previous single-school setup had no distinction — they were implicitly global.

Idempotent: safe to run more than once.

    python -m db.migrate_admin_roles
"""
from sqlalchemy import text

from db.database import engine


def main() -> None:
    print(f"Connecting to: {engine.url}")

    with engine.begin() as conn:
        # 1. Create the enum type if it doesn't exist.
        conn.execute(text("""
            DO $$ BEGIN
                CREATE TYPE admin_role AS ENUM ('school_admin', 'global_admin');
            EXCEPTION
                WHEN duplicate_object THEN NULL;
            END $$
        """))

        # 2. Add the new column (no-op if it already exists).
        conn.execute(text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS admin_role admin_role"
        ))

        # 3. Backfill: is_admin = TRUE → global_admin.
        result = conn.execute(text("""
            UPDATE users
               SET admin_role = 'global_admin'
             WHERE admin_role IS NULL
               AND is_admin = TRUE
        """))
        print(f"Migrated {result.rowcount} existing admin(s) to global_admin.")

        # 4. Drop the old boolean (safe now that all data is migrated).
        conn.execute(text(
            "ALTER TABLE users DROP COLUMN IF EXISTS is_admin"
        ))

    print("Migration complete — admin_role column is active, is_admin column removed.")


if __name__ == "__main__":
    main()
