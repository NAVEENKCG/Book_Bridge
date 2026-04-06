"""
routes/wanted.py — Wanted board: view, add, delete.
"""
from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from database import SessionLocal
from models import Wishlist

router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.get("/wanted")
def wanted_board(request: Request):
    db = SessionLocal()
    try:
        posts = db.query(Wishlist).order_by(Wishlist.created_at.desc()).all()
        return templates.TemplateResponse(
            "wanted.html", {"request": request, "posts": posts}
        )
    finally:
        db.close()


@router.post("/wanted/add")
def wanted_add(
    request: Request,
    book_title: str = Form(...),
    course_code: str = Form(None),
    max_price: int = Form(None),
):
    user = request.state.user
    if not user:
        return RedirectResponse("/login")

    db = SessionLocal()
    try:
        entry = Wishlist(
            user_id=user.id,
            book_title=book_title.strip(),
            course_code=(course_code or "").strip().upper() or None,
            max_price=max_price,
        )
        db.add(entry)
        db.commit()
    finally:
        db.close()

    return RedirectResponse("/wanted", status_code=302)


@router.post("/wanted/{wishlist_id}/delete")
def wanted_delete(request: Request, wishlist_id: int):
    user = request.state.user
    if not user:
        return RedirectResponse("/login")

    db = SessionLocal()
    try:
        entry = db.query(Wishlist).filter(Wishlist.id == wishlist_id).first()
        if entry and entry.user_id == user.id:
            db.delete(entry)
            db.commit()
    finally:
        db.close()

    return RedirectResponse("/wanted", status_code=302)
