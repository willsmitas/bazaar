"""
main.py — Bazaar API entry point.

Local dev:
    uvicorn server.main:app --reload

Production (started by Procfile):
    uvicorn server.main:app --host 0.0.0.0 --port $PORT

Interactive API docs: http://localhost:8000/docs
"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from config import settings
from server.routers import admin, auth, blocks, chats, listings, payments, ratings, reports, schools, transactions, users, ws

app = FastAPI(
    title="Bazaar API",
    version="0.1.0",
    debug=settings.debug,
    # Hide /docs and /redoc in production
    docs_url="/docs" if settings.debug else None,
    redoc_url=None,
)

# CORS — parse the comma-separated CORS_ORIGINS setting
_origins = ["*"] if settings.cors_origins.strip() == "*" else [
    o.strip() for o in settings.cors_origins.split(",") if o.strip()
]
# A wildcard origin with credentials is rejected by browsers and disallowed by
# the CORS spec. Bazaar authenticates with Bearer tokens (not cookies), so we
# only enable credentials when origins are explicitly listed.
_allow_credentials = _origins != ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve local uploads only when running the local storage backend.
# In production (s3), files are served directly from the bucket.
if settings.storage_backend == "local":
    Path("uploads").mkdir(exist_ok=True)
    app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(blocks.router)
app.include_router(schools.router)
app.include_router(listings.router)
app.include_router(transactions.router)
app.include_router(payments.router)
app.include_router(chats.router)
app.include_router(ratings.router)
app.include_router(reports.router)
app.include_router(admin.router)
app.include_router(ws.router)


@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok"}


@app.get("/{full_path:path}")
async def serve_frontend(full_path: str):
    try:
        # Force UTF-8 — the file contains emoji/box-drawing chars, and the
        # platform default (cp1252 on Windows) can't decode them.
        with open("index.html", encoding="utf-8") as f:
            return HTMLResponse(f.read())
    except FileNotFoundError:
        return {"detail": "Not Found"}, 404
