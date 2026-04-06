"""
routes/auth.py — Register, login, logout, profile, edit profile, change password.
"""
from __future__ import annotations

import os

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from auth import (
    COOKIE_MAX_AGE,
    COOKIE_NAME,
    create_session_cookie,
    get_password_hash,
    verify_password,
)
from database import SessionLocal
from models import Listing, User

router = APIRouter()
templates = Jinja2Templates(directory="templates")

_ALLOWED_DOMAINS = (".ac.in", ".edu")


def _is_academic_email(email: str) -> bool:
    return any(email.lower().endswith(d) for d in _ALLOWED_DOMAINS)


def _set_cookie(response, user_id: int) -> None:
    response.set_cookie(
        key=COOKIE_NAME,
        value=create_session_cookie(user_id),
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
    )


# ---------------------------------------------------------------------------
# Register
# ---------------------------------------------------------------------------

@router.get("/register")
def register_get(request: Request):
    if request.state.user:
        return RedirectResponse("/")
    return templates.TemplateResponse("register.html", {"request": request})


@router.post("/register")
def register_post(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    college: str = Form(None),
    department: str = Form(None),
    semester: int = Form(None),
):
    email = email.strip().lower()
    if not _is_academic_email(email):
        return templates.TemplateResponse(
            "register.html",
            {"request": request, "error": "Please use an institutional email (.ac.in or .edu)."},
        )

    db = SessionLocal()
    try:
        if db.query(User).filter(User.email == email).first():
            return templates.TemplateResponse(
                "register.html",
                {"request": request, "error": "An account with that email already exists."},
            )
        user = User(
            name=name.strip(),
            email=email,
            hashed_password=get_password_hash(password),
            college=(college or "").strip() or None,
            department=(department or "").strip() or None,
            semester=semester,
            bookcoin_bal=50,
            college_domain=email.split("@")[1].lower(),  # tamper-proof isolation key
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    finally:
        db.close()

    response = RedirectResponse("/", status_code=302)
    _set_cookie(response, user.id)
    return response


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

@router.get("/login")
def login_get(request: Request):
    if request.state.user:
        return RedirectResponse("/")
    return templates.TemplateResponse("login.html", {"request": request})


@router.post("/login")
def login_post(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
):
    email = email.strip().lower()
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
    finally:
        db.close()

    if not user or not verify_password(password, user.hashed_password):
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Invalid email or password."},
        )

    response = RedirectResponse("/", status_code=302)
    _set_cookie(response, user.id)
    return response


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------

@router.get("/logout")
def logout():
    response = RedirectResponse("/login", status_code=302)
    response.delete_cookie(key=COOKIE_NAME)
    return response


# ---------------------------------------------------------------------------
# Profile — redirect self to /profile/{id}
# ---------------------------------------------------------------------------

@router.get("/profile")
def profile_self(request: Request):
    user = request.state.user
    if not user:
        return RedirectResponse("/login")
    return RedirectResponse(f"/profile/{user.id}")


# ---------------------------------------------------------------------------
# Edit profile  ← MUST come before /profile/{user_id} to avoid int parse error
# ---------------------------------------------------------------------------

@router.get("/profile/edit")
def profile_edit_get(request: Request):
    user = request.state.user
    if not user:
        return RedirectResponse("/login")
    db = SessionLocal()
    try:
        target = db.query(User).filter(User.id == user.id).first()
        return templates.TemplateResponse("edit_profile.html", {"request": request, "target": target})
    finally:
        db.close()


@router.post("/profile/edit")
def profile_edit_post(
    request: Request,
    name: str = Form(...),
    college: str = Form(None),
    department: str = Form(None),
    semester: int = Form(None),
):
    user = request.state.user
    if not user:
        return RedirectResponse("/login")

    db = SessionLocal()
    try:
        u = db.query(User).filter(User.id == user.id).first()
        if u:
            u.name       = name.strip()
            u.college    = (college or "").strip() or None
            u.department = (department or "").strip() or None
            u.semester   = semester
            db.commit()
    finally:
        db.close()

    return RedirectResponse(f"/profile/{user.id}", status_code=302)


# ---------------------------------------------------------------------------
# Change password  ← also before /{user_id} for safety
# ---------------------------------------------------------------------------

@router.get("/change-password")
def change_password_get(request: Request):
    user = request.state.user
    if not user:
        return RedirectResponse("/login")
    return templates.TemplateResponse("change_password.html", {"request": request})


@router.post("/change-password")
def change_password_post(
    request: Request,
    old_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
):
    user = request.state.user
    if not user:
        return RedirectResponse("/login")

    if new_password != confirm_password:
        return templates.TemplateResponse(
            "change_password.html",
            {"request": request, "error": "New passwords do not match."},
        )
    if len(new_password) < 8:
        return templates.TemplateResponse(
            "change_password.html",
            {"request": request, "error": "New password must be at least 8 characters."},
        )

    db = SessionLocal()
    try:
        u = db.query(User).filter(User.id == user.id).first()
        if not u or not verify_password(old_password, u.hashed_password):
            return templates.TemplateResponse(
                "change_password.html",
                {"request": request, "error": "Current password is incorrect."},
            )
        u.hashed_password = get_password_hash(new_password)
        db.commit()
    finally:
        db.close()

    return RedirectResponse(f"/profile/{user.id}", status_code=302)


# ---------------------------------------------------------------------------
# Profile — public view  ← wildcard LAST to avoid eating static sub-paths
# ---------------------------------------------------------------------------

@router.get("/profile/{user_id}")
def profile_public(request: Request, user_id: int):
    db = SessionLocal()
    try:
        target = db.query(User).filter(User.id == user_id).first()
        if not target:
            return templates.TemplateResponse(
                "error.html",
                {"request": request, "code": 404, "message": "User not found."},
                status_code=404,
            )
        listings = (
            db.query(Listing)
            .filter(Listing.seller_id == user_id, Listing.status == "available")
            .order_by(Listing.created_at.desc())
            .limit(6)
            .all()
        )
        is_own = request.state.user and request.state.user.id == user_id
        return templates.TemplateResponse(
            "profile.html",
            {"request": request, "target": target, "listings": listings, "is_own": is_own},
        )
    finally:
        db.close()
