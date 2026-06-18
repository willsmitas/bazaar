"""
init_db.py — Create all tables in the configured database.

Run once after setting DATABASE_URL in your .env:
    python -m db.init_db

To wipe and recreate from scratch (dev only!):
    python -m db.init_db --reset
"""
import sys
from db.database import Base, engine
import db.models  # noqa: F401 — registers all models with Base


def create_tables() -> None:
    print(f"Connecting to: {engine.url}")
    Base.metadata.create_all(bind=engine)
    print("All tables created.")


def drop_tables() -> None:
    print(f"Dropping all tables in: {engine.url}")
    Base.metadata.drop_all(bind=engine)
    print("Done.")


if __name__ == "__main__":
    if "--reset" in sys.argv:
        confirm = input("This will DELETE all data. Type 'yes' to continue: ")
        if confirm.strip().lower() != "yes":
            print("Aborted.")
            sys.exit(0)
        drop_tables()
    create_tables()
