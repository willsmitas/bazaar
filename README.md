# Bazaar 🐻

An anonymous, intra-university marketplace for **Brown University** students. Buyers and
sellers stay anonymous until a price is agreed, delivery is in person, and the platform
takes a small commission per transaction.

## Tech stack

- **Frontend:** single-file vanilla HTML/CSS/JS — no framework (`index.html`)
- **API:** FastAPI on Uvicorn (REST + WebSocket), Pydantic v2
- **Auth:** JWT access/refresh tokens + bcrypt + email OTP verification
- **Data:** SQLAlchemy 2.0 ORM → PostgreSQL 18
- **Storage / email:** local disk or S3 · SMTP or dev console

See **[ARCHITECTURE.md](ARCHITECTURE.md)** for the full design, request flows, and file map.

## Features

- Sign-up with university-email verification, login, and password reset
- Post items for sale or requests; browse and search
- Sellers stay anonymous until a buyer opens a chat
- **Real-time chat** over WebSockets, with a lock-in-price → transaction flow
- Ratings, reporting, and an **admin moderation** panel (ban / suspend / reinstate)

## Quick start (local)

Requires **Python 3.13** and a running **PostgreSQL 18**.
(`py` is the Windows launcher — use `python3` on macOS/Linux.)

```bash
py -m pip install -r requirements.txt
cp .env.example .env              # Windows: copy .env.example .env
#  then edit .env: set your Postgres password in DATABASE_URL + a SECRET_KEY

py -m db.create_database          # create the "bazaar" database
py -m db.init_db                  # create all tables
py -m db.seed                     # optional: sample users + listings
py -m db.make_admin you@brown.edu # optional: grant yourself admin

py -m uvicorn server.main:app --reload   # API → http://localhost:8000  (/docs in debug)
py -m http.server 5500                   # UI  → http://localhost:5500
```

With `DEBUG=true`, email verification codes print to the **API server console** (no SMTP
needed for local dev). Seeded accounts all use the password `testpass123`, and
`test@brown.edu` is seeded as an admin.

## Project layout

```
index.html        frontend (UI + API & WebSocket clients)
config.py         env-driven settings (pydantic-settings)
db/               schema.sql, ORM models, and setup scripts
server/           FastAPI app, routers, auth, storage, email
ARCHITECTURE.md   full architecture reference
.env.example      template for your local .env (never commit .env)
```

## Status

Active development. Not yet built: **payments** (Stripe Connect for commission) and
**push notifications**. See the limitations section of [ARCHITECTURE.md](ARCHITECTURE.md).
