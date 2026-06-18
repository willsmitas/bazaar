# Bazaar — Architecture

Bazaar is an anonymous, intra-university marketplace for Brown University students:
buyers and sellers stay anonymous until a price is agreed, delivery is in person, and
the app takes a commission per transaction.

This document describes the full stack the app runs on and how the pieces fit together.

---

## Stack at a glance

| Layer            | Technology                                              |
|------------------|---------------------------------------------------------|
| Client           | Single-file HTML / CSS / **vanilla JS** (no framework)  |
| API server       | **FastAPI** on **Uvicorn** (ASGI) — REST + WebSocket    |
| Validation       | **Pydantic v2**                                         |
| Auth             | **JWT** (`python-jose`, HS256) · **bcrypt** · 6-digit OTP |
| ORM / driver     | **SQLAlchemy 2.0** + **psycopg2**                       |
| Database         | **PostgreSQL 18**                                       |
| File storage     | Local disk (dev) / **S3** (prod), behind one abstraction |
| Email            | **SMTP** (prod) / console (dev)                         |
| Config           | **pydantic-settings** + `.env`                          |
| Language / runtime | Python 3.13 (backend), HTML/CSS/JS (frontend), SQL    |

---

## Layer diagram

```
              Browser  —  index.html  (vanilla HTML/CSS/JS)
              API client (fetch + JWT)   WebSocket client
                    │                          │
        REST / JSON (Bearer JWT)        WebSocket (live chat)
                    ▼                          ▼
        ┌─────────────────────────────────────────────┐        cross-cutting
        │        FastAPI  on  Uvicorn  (ASGI)          │   ┌──────────────────────┐
        │  routers: auth users listings transactions   │───│ Auth   JWT/bcrypt/OTP │
        │           chats ratings reports admin ws     │   │ Config pydantic/.env  │
        │  Pydantic v2 validation · CORS middleware    │   │ Storage local / S3    │
        └─────────────────────────────────────────────┘   │ Email  SMTP / console │
                    │                                      └──────────────────────┘
                    ▼
            SQLAlchemy 2.0 ORM  →  psycopg2 driver
                    ▼
            PostgreSQL 18   (database "bazaar", 7 tables)
```

---

## Components

### 1. Client — `index.html`
The entire frontend is one file with **no framework and no build step**. Its `<script>` contains:

- An **API client** (`fetch`-based) that stores access + refresh JWTs in `localStorage`,
  attaches the access token as a `Bearer` header, and transparently refreshes it on a `401`.
- A **WebSocket client** that opens one socket per open chat for live messaging.
- The base URL is `http://localhost:8000` by default and is overridable at runtime via
  `localStorage.setItem('bazaar_api', '<url>')`.

In development it is served as a static file (see [Local development](#local-development)).

### 2. API server — FastAPI on Uvicorn
[`server/main.py`](server/main.py) builds the FastAPI app, configures CORS, conditionally
mounts `/uploads` (local storage only), and includes every router. Uvicorn (an ASGI server)
runs it and also terminates WebSocket connections.

Routers live in [`server/routers/`](server/routers/):

| Router            | Prefix          | Responsibility |
|-------------------|-----------------|----------------|
| `auth`            | `/auth`         | register, verify-email, login, refresh, forgot/reset password |
| `users`           | `/users`        | `me` profile, avatar upload, public user lookup |
| `listings`        | `/listings`     | browse/search, CRUD, `me`, image upload |
| `transactions`    | `/transactions` | open a deal (creates a chat), status machine, commission |
| `chats`           | `/chats`        | list chats, fetch + send messages (REST) |
| `ratings`         | `/ratings`      | post a rating, recompute averages |
| `reports`         | `/reports`      | file a moderation report |
| `admin`           | `/admin`        | review reports, ban/suspend/reinstate users, remove listings (admin-only) |
| `ws`              | `/ws/chats/...` | **WebSocket** real-time chat |

[`server/schemas.py`](server/schemas.py) holds the Pydantic v2 request/response models —
the typed contract between client and server. Response models never expose `password_hash`.

### 3. Auth & security — cross-cutting
- [`server/security.py`](server/security.py): bcrypt password hashing, JWT access/refresh
  tokens (HS256, signed with `SECRET_KEY`, type-checked on decode), and OTP generation.
- [`server/dependencies.py`](server/dependencies.py): `get_db` (per-request session),
  `get_current_user` (decodes the JWT, enforces ban/suspension, auto-reinstates expired
  suspensions), and `get_current_admin` (requires `is_admin`).
- Tokens are sent as `Authorization: Bearer <token>` on REST calls and as a `?token=`
  query parameter on the WebSocket handshake (browsers can't set headers there).

### 4. ORM / data access — SQLAlchemy + psycopg2
[`db/models.py`](db/models.py) maps each table to a SQLAlchemy 2.0 ORM class
(`Mapped` / `mapped_column`). SQLAlchemy generates SQL and talks to Postgres through the
psycopg2 driver ([`db/database.py`](db/database.py) builds the engine + session factory
from `settings.database_url`). Handlers query via the models — no raw SQL in the routers.

### 5. Database — PostgreSQL 18
A local PostgreSQL 18 server holds the `bazaar` database. Schema:
`users`, `listings`, `transactions`, `chats`, `messages`, `ratings`, `reports` — with UUID
primary keys, enum-backed status columns, check constraints, and `updated_at` triggers.
The canonical raw schema is [`db/schema.sql`](db/schema.sql); the ORM models mirror it.

### 6. File storage & email — cross-cutting
- [`server/storage.py`](server/storage.py): `save_image()` writes to local `uploads/`
  (served by FastAPI `StaticFiles`) in dev, or to **S3** in prod — selected by
  `STORAGE_BACKEND`.
- [`server/email.py`](server/email.py): prints verification / reset codes to the server
  console when `DEBUG=true`; sends real email over SMTP otherwise.

### 7. Configuration — the dev↔prod seam
[`config.py`](config.py) (pydantic-settings) loads all settings from environment variables
or [`.env`](.env). The *same code* runs locally or in the cloud — only the values change.
Key variables: `DATABASE_URL`, `SECRET_KEY`, `STORAGE_BACKEND`, `CORS_ORIGINS`, `DEBUG`,
the `SMTP_*` group, and token TTLs. See [`.env.example`](.env.example) for the full list.

---

## Request flows

**REST (e.g. post a listing):**
```
fetch POST /listings (Bearer JWT)
  → CORS middleware → route match
  → get_current_user (decode JWT, check account status)
  → Pydantic validates body
  → handler builds a Listing ORM object
  → SQLAlchemy INSERT via psycopg2 → PostgreSQL
  → response serialized to JSON
```

**WebSocket (live chat):** the browser sends a message over the open socket; the server
authenticates the `?token=`, verifies the sender is a chat participant, **persists** the
message, then **broadcasts** it to every socket connected to that chat. Connections are
tracked in memory by a `ConnectionManager` in [`server/routers/ws.py`](server/routers/ws.py).

---

## Repository layout

```
Bazaar/
├── index.html              # entire frontend (UI + API client + WebSocket client)
├── config.py               # pydantic-settings — all env-driven config
├── requirements.txt        # Python dependencies
├── Procfile                # production start command
├── .env / .env.example     # local secrets / documented template
├── db/
│   ├── schema.sql          # canonical raw PostgreSQL schema
│   ├── models.py           # SQLAlchemy 2.0 ORM models
│   ├── database.py         # engine + session factory + Base
│   ├── init_db.py          # create all tables (py -m db.init_db)
│   ├── create_database.py  # create the "bazaar" database (py -m db.create_database)
│   ├── seed.py             # sample users + listings (py -m db.seed)
│   └── make_admin.py       # promote a user to admin (py -m db.make_admin <email>)
└── server/
    ├── main.py             # FastAPI app: CORS, static mount, routers
    ├── schemas.py          # Pydantic v2 request/response models
    ├── security.py         # bcrypt, JWT, OTP
    ├── dependencies.py     # get_db, get_current_user, get_current_admin
    ├── storage.py          # local / S3 image storage
    ├── email.py            # SMTP / console email
    └── routers/            # auth, users, listings, transactions,
                            # chats, ratings, reports, admin, ws
```

---

## Local development

Requires Python 3.13 and a running PostgreSQL 18 instance. (`py` is the Windows launcher;
use `python3` on macOS/Linux.)

```bash
py -m pip install -r requirements.txt   # install dependencies
#  edit .env so DATABASE_URL has your Postgres password (URL-encode special chars)
py -m db.create_database                # create the "bazaar" database
py -m db.init_db                        # create all tables
py -m db.seed                           # (optional) sample users + listings
py -m db.make_admin you@brown.edu       # (optional) grant yourself admin

py -m uvicorn server.main:app --reload  # API  →  http://localhost:8000  (/docs in debug)
py -m http.server 5500                  # UI   →  http://localhost:5500
```

With `DEBUG=true`, verification / password-reset codes print to the **API server console**
instead of being emailed. Seeded accounts all use the password `testpass123`;
`test@brown.edu` is seeded as an admin.

---

## Dev → production

Nothing structural changes — only configuration:

- `DATABASE_URL` → a managed Postgres (Supabase / Neon / RDS).
- `STORAGE_BACKEND=s3` (+ bucket / region / AWS keys).
- `CORS_ORIGINS` → your real domain(s); `DEBUG=false` (hides `/docs`).
- `SMTP_*` → a real email provider.
- Start via the [`Procfile`](Procfile) (Railway / Render / Heroku / Fly).

### Known limitations / future work
- **WebSocket scaling:** connections are tracked in-memory, so real-time chat assumes a
  single Uvicorn worker. Multi-worker deployments need a shared pub/sub (e.g. Redis).
- **Per-chat sockets:** only the open conversation updates live; the chat *list* (unread
  counts) does not. A per-user socket would fix that.
- **WS token in query string** is fine for dev; production should use a short-lived ticket.
- **Payments** (Stripe Connect for commission collection) and **push notifications** are
  not yet built.
