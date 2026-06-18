"""
create_database.py — Create the Bazaar database if it doesn't exist yet.

Postgres can't "CREATE DATABASE bazaar" from inside the bazaar database (it
doesn't exist yet), so this connects to the always-present "postgres"
maintenance database using the SAME credentials from your DATABASE_URL, then
creates the target database.

Credentials are parsed with SQLAlchemy's make_url so percent-encoded passwords
(e.g. a password containing % or [ ) are decoded exactly as the app decodes them.

Run once before init_db:
    py -m db.create_database
"""
import psycopg2
from psycopg2 import sql
from sqlalchemy.engine import make_url

from config import settings


def main() -> None:
    url = make_url(settings.database_url)   # unquotes username/password for us
    target_db = url.database
    if not target_db:
        raise SystemExit("DATABASE_URL has no database name.")

    print(f"Connecting as {url.username}@{url.host or 'localhost'}:{url.port or 5432} …")
    conn = psycopg2.connect(
        dbname="postgres",                  # maintenance DB that always exists
        user=url.username,
        password=url.password,
        host=url.host or "localhost",
        port=url.port or 5432,
    )
    conn.autocommit = True                  # CREATE DATABASE can't run in a transaction
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (target_db,))
            if cur.fetchone():
                print(f"Database '{target_db}' already exists — nothing to do.")
            else:
                cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(target_db)))
                print(f"Created database '{target_db}'.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
