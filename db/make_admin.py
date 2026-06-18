"""
make_admin.py — Grant admin rights to a user by email.

    py -m db.make_admin you@brown.edu

Also performs an idempotent "ADD COLUMN IF NOT EXISTS" so it works on databases
created before the is_admin column existed (fresh databases get it from the model).
"""
import sys

from sqlalchemy import text

from db.database import SessionLocal, engine
from db.models import User


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: py -m db.make_admin <email>")
    email = sys.argv[1]

    # Bring an already-created database up to date (no-op if the column exists).
    with engine.begin() as conn:
        conn.execute(text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT FALSE"
        ))

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        if not user:
            raise SystemExit(f"No user found with email {email!r}")
        user.is_admin = True
        db.commit()
        print(f"{email} is now an admin.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
