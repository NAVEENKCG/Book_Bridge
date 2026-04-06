"""
main.py — FastAPI application entry point.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

load_dotenv()

# ---------------------------------------------------------------------------
# Import after env is loaded so database URL is resolved correctly.
# ---------------------------------------------------------------------------
from database import Base, engine  # noqa: E402
import models  # noqa: F401, E402 — must import so models register with Base

from routes import auth as auth_router
from routes import listings as listings_router
from routes import exchange as exchange_router
from routes import wanted as wanted_router
from routes import api as api_router
from routes import wishlist as wishlist_router
from routes import notifications as notifications_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create all tables on startup (SQLite convenience — Alembic for migrations)
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="BookBridge", lifespan=lifespan)

templates = Jinja2Templates(directory="templates")


# ---------------------------------------------------------------------------
# Middleware — attach current_user to every request state.
# ---------------------------------------------------------------------------
@app.middleware("http")
async def attach_user(request: Request, call_next):
    from auth import get_current_user

    request.state.user = get_current_user(request)
    return await call_next(request)


# ---------------------------------------------------------------------------
# Global exception handlers
# ---------------------------------------------------------------------------
@app.exception_handler(404)
async def not_found(request: Request, _exc):
    return templates.TemplateResponse(
        "error.html",
        {"request": request, "code": 404, "message": "Page not found."},
        status_code=404,
    )


@app.exception_handler(403)
async def forbidden(request: Request, _exc):
    return templates.TemplateResponse(
        "error.html",
        {"request": request, "code": 403, "message": "You do not have permission to do that."},
        status_code=403,
    )


@app.exception_handler(500)
async def server_error(request: Request, _exc):
    return templates.TemplateResponse(
        "error.html",
        {"request": request, "code": 500, "message": "Something went wrong on our end."},
        status_code=500,
    )


# ---------------------------------------------------------------------------
# Router registration
# ---------------------------------------------------------------------------
app.include_router(auth_router.router)
app.include_router(listings_router.router)
app.include_router(exchange_router.router)
app.include_router(wanted_router.router)
app.include_router(api_router.router)
app.include_router(wishlist_router.router)
app.include_router(notifications_router.router)
