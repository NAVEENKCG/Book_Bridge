"""
routes/notifications.py — In-app notification list, mark-read, API count endpoint.
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from database import SessionLocal
from models import Notification

router = APIRouter()
templates = Jinja2Templates(directory="templates")


# ---------------------------------------------------------------------------
# Notification page
# ---------------------------------------------------------------------------

@router.get("/notifications")
def notifications_page(request: Request):
    user = request.state.user
    if not user:
        return RedirectResponse("/login")

    db = SessionLocal()
    try:
        notifs = (
            db.query(Notification)
            .filter(Notification.user_id == user.id)
            .order_by(Notification.created_at.desc())
            .limit(50)
            .all()
        )
        return templates.TemplateResponse(
            "notifications.html", {"request": request, "notifs": notifs}
        )
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Mark one notification as read
# ---------------------------------------------------------------------------

@router.post("/notifications/{notif_id}/read")
def notification_read(request: Request, notif_id: int):
    user = request.state.user
    if not user:
        return RedirectResponse("/login")

    db = SessionLocal()
    try:
        n = db.query(Notification).filter(
            Notification.id == notif_id, Notification.user_id == user.id
        ).first()
        if n:
            n.is_read = True
            db.commit()
    finally:
        db.close()

    return RedirectResponse("/notifications", status_code=302)


# ---------------------------------------------------------------------------
# Mark all notifications as read
# ---------------------------------------------------------------------------

@router.post("/notifications/read-all")
def notifications_read_all(request: Request):
    user = request.state.user
    if not user:
        return RedirectResponse("/login")

    db = SessionLocal()
    try:
        db.query(Notification).filter(
            Notification.user_id == user.id,
            Notification.is_read == False,  # noqa: E712
        ).update({"is_read": True})
        db.commit()
    finally:
        db.close()

    return RedirectResponse("/notifications", status_code=302)


# ---------------------------------------------------------------------------
# JSON API — unread count (for navbar badge polling)
# ---------------------------------------------------------------------------

@router.get("/api/notifications/count")
def notifications_count(request: Request):
    user = request.state.user
    if not user:
        return JSONResponse({"unread": 0})

    db = SessionLocal()
    try:
        count = (
            db.query(Notification)
            .filter(Notification.user_id == user.id, Notification.is_read == False)  # noqa: E712
            .count()
        )
        return JSONResponse({"unread": count})
    finally:
        db.close()
