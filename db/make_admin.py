"""
make_admin.py — Grant or change admin rights for a user.

    py -m db.make_admin you@brown.edu                  # school admin (default)
    py -m db.make_admin you@brown.edu --global         # global admin
    py -m db.make_admin you@brown.edu --revoke         # remove admin role

Also performs an idempotent column migration from the old `is_admin` boolean to
the new `admin_role` column (safe on databases that already have it).
"""
import sys

from sqlalchemy import text

from db.database import SessionLocal, engine
from db.models import AdminRole, User


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1].startswith("-"):
        raise SystemExit(
            "usage: py -m db.make_admin <email> [--global | --revoke]"
        )
    email = sys.argv[1]
    flags = set(sys.argv[2:])
    revoke     = "--revoke" in flags
    is_global  = "--global" in flags

    if revoke and is_global:
        raise SystemExit("--revoke and --global are mutually exclusive")

    # Bring an older database forward: add admin_role, migrate is_admin values.
    with engine.begin() as conn:
        conn.execute(text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS "
            "admin_role VARCHAR(20)"
        ))
        # One-time backfill from the old is_admin boolean (if the column still
        # exists — it's dropped by migrate_admin_roles.py and absent on fresh DBs).
        has_old_col = conn.execute(text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'users' AND column_name = 'is_admin'"
        )).first()
        if has_old_col:
            conn.execute(text("""
                UPDATE users
                   SET admin_role = 'global_admin'
                 WHERE admin_role IS NULL
                   AND is_admin = TRUE
            """))

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        if not user:
            raise SystemExit(f"No user found with email {email!r}")

        if revoke:
            user.admin_role = None
            db.commit()
            print(f"{email} is no longer an admin.")
        else:
            role = AdminRole.global_admin if is_global else AdminRole.school_admin
            user.admin_role = role
            db.commit()
            label = "global admin" if is_global else "school admin"
            print(f"{email} is now a {label}.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
