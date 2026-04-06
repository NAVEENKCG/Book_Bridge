"""
routes/listings.py — Homepage browse/search, create/edit listing, detail, my-listings,
                     college isolation, listing rate-limit, 90-day expiry.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import or_

from ai import fetch_isbn_metadata
from database import SessionLocal
from models import ExchangeRequest, Listing, ListingWishlist, Notification, User, Wishlist

router = APIRouter()
templates = Jinja2Templates(directory="templates")

_CONDITIONS = ["New", "Like New", "Good", "Fair", "Poor"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.utcnow()


def _emit(db, user_id: int, message: str, link: str | None = None) -> None:
    db.add(Notification(user_id=user_id, message=message, link=link))


# ---------------------------------------------------------------------------
# Homepage — browse + search (with expiry filter + college isolation)
# ---------------------------------------------------------------------------

@router.get("/")
def index(
    request: Request,
    q: str = None,
    course: str = None,
    condition: str = None,
    max_price: Optional[int] = None,
    exchange_only: str = None,
):
    db = SessionLocal()
    try:
        now = _now()
        query = (
            db.query(Listing)
            .filter(Listing.status == "available")
            .filter(or_(Listing.expires_at == None, Listing.expires_at > now))  # noqa: E711
        )

        user = request.state.user
        if user and user.college_domain:
            query = query.filter(Listing.college_domain == user.college_domain)

        if q:
            query = query.filter(
                or_(Listing.title.ilike(f"%{q}%"), Listing.author.ilike(f"%{q}%"))
            )
        if course:
            query = query.filter(Listing.course_code.ilike(f"%{course}%"))
        if condition:
            query = query.filter(Listing.condition == condition)
        if max_price is not None:
            query = query.filter(Listing.price <= max_price)
        if exchange_only:
            query = query.filter(Listing.is_exchange.is_(True))

        listings = query.order_by(Listing.created_at.desc()).all()
        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "listings": listings,
                "conditions": _CONDITIONS,
                "q": q or "",
                "course": course or "",
                "condition": condition or "",
                "max_price": max_price or "",
                "exchange_only": exchange_only or "",
            },
        )
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Create listing (with rate-limit + expiry)
# ---------------------------------------------------------------------------

@router.get("/list")
def list_get(request: Request):
    if not request.state.user:
        return RedirectResponse("/login")
    return templates.TemplateResponse(
        "list_book.html", {"request": request, "conditions": _CONDITIONS}
    )


@router.post("/list")
async def list_post(
    request: Request,
    isbn: str = Form(None),
    title: str = Form(...),
    author: str = Form(None),
    publisher: str = Form(None),
    edition: str = Form(None),
    cover_url: str = Form(None),
    condition: str = Form(...),
    price: int = Form(None),
    is_exchange: str = Form(None),
    course_code: str = Form(None),
    semester: int = Form(None),
    description: str = Form(None),
):
    user = request.state.user
    if not user:
        return RedirectResponse("/login")

    db = SessionLocal()
    try:
        seller_row = db.query(User).filter(User.id == user.id).first()

        # ── 30-second listing rate-limit ──────────────────────────────────────
        if seller_row.last_listed_at:
            elapsed = (_now() - seller_row.last_listed_at).total_seconds()
            if elapsed < 30:
                wait = int(30 - elapsed)
                return templates.TemplateResponse(
                    "list_book.html",
                    {
                        "request": request,
                        "conditions": _CONDITIONS,
                        "error": f"Please wait {wait} more second(s) before listing again.",
                    },
                )

        # Cover URL server-side fallback
        _cover = (cover_url or "").strip() or None
        if not _cover and isbn:
            meta = await fetch_isbn_metadata(isbn.strip())
            _cover = meta.get("cover_url") or None

        listing = Listing(
            seller_id=user.id,
            isbn=(isbn or "").strip() or None,
            title=title.strip(),
            author=(author or "").strip() or None,
            publisher=(publisher or "").strip() or None,
            edition=(edition or "").strip() or None,
            cover_url=_cover,
            condition=condition,
            price=price,
            is_exchange=bool(is_exchange),
            course_code=(course_code or "").strip().upper() or None,
            semester=semester,
            college=user.college,
            department=user.department,
            college_domain=user.college_domain,  # authoritative isolation key
            description=(description or "").strip() or None,
            expires_at=_now() + timedelta(days=90),
        )
        db.add(listing)

        seller_row.bookcoin_bal = (seller_row.bookcoin_bal or 0) + 10
        seller_row.last_listed_at = _now()

        db.commit()
        db.refresh(listing)
        listing_id = listing.id
    finally:
        db.close()

    return RedirectResponse(f"/listing/{listing_id}", status_code=302)


# ---------------------------------------------------------------------------
# Listing detail (with college isolation)
# ---------------------------------------------------------------------------

@router.get("/listing/{listing_id}")
def listing_detail(request: Request, listing_id: int):
    db = SessionLocal()
    try:
        listing = db.query(Listing).filter(Listing.id == listing_id).first()
        if not listing:
            return templates.TemplateResponse(
                "error.html",
                {"request": request, "code": 404, "message": "Listing not found."},
                status_code=404,
            )

        user = request.state.user

        # ── College isolation (email-domain based) ─────────────────────────────────
        if (
            user
            and user.college_domain
            and listing.college_domain
            and user.college_domain != listing.college_domain
        ):
            return templates.TemplateResponse(
                "error.html",
                {
                    "request": request,
                    "code": 403,
                    "message": "This listing is from a different college and is not accessible to you.",
                },
                status_code=403,
            )

        existing_request = None
        wishlisted = False
        if user:
            existing_request = (
                db.query(ExchangeRequest)
                .filter(
                    ExchangeRequest.listing_id == listing_id,
                    ExchangeRequest.requester_id == user.id,
                )
                .first()
            )
            wishlisted = (
                db.query(ListingWishlist)
                .filter(
                    ListingWishlist.user_id == user.id,
                    ListingWishlist.listing_id == listing_id,
                )
                .first()
                is not None
            )

        wanted_count = (
            db.query(Wishlist)
            .filter(Wishlist.book_title.ilike(f"%{listing.title}%"))
            .count()
        )

        # ── Demand heat tier ───────────────────────────────────────────────
        if wanted_count >= 10:
            demand_heat = "critical"      # 🔥🔥 +25% price suggestion
            price_multiplier = 1.25
        elif wanted_count >= 5:
            demand_heat = "high"          # 🔥 +10% price suggestion
            price_multiplier = 1.10
        elif wanted_count >= 1:
            demand_heat = "medium"        # amber notice
            price_multiplier = None
        else:
            demand_heat = "low"
            price_multiplier = None

        price_suggestion = None
        if listing.price and price_multiplier:
            price_suggestion = round(listing.price * price_multiplier)

        seller = db.query(User).filter(User.id == listing.seller_id).first()

        # Days until expiry
        days_left = None
        if listing.expires_at:
            delta = listing.expires_at - _now()
            days_left = max(0, delta.days)

        return templates.TemplateResponse(
            "listing.html",
            {
                "request": request,
                "listing": listing,
                "seller": seller,
                "existing_request": existing_request,
                "wanted_count": wanted_count,
                "wishlisted": wishlisted,
                "days_left": days_left,
                "demand_heat": demand_heat,
                "price_suggestion": price_suggestion,
            },
        )
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Edit listing (owner only)
# ---------------------------------------------------------------------------

@router.get("/listing/{listing_id}/edit")
def listing_edit_get(request: Request, listing_id: int):
    user = request.state.user
    if not user:
        return RedirectResponse("/login")

    db = SessionLocal()
    try:
        listing = db.query(Listing).filter(Listing.id == listing_id).first()
        if not listing or listing.seller_id != user.id:
            return templates.TemplateResponse(
                "error.html",
                {"request": request, "code": 403, "message": "Access denied."},
                status_code=403,
            )
        return templates.TemplateResponse(
            "edit_listing.html",
            {"request": request, "listing": listing, "conditions": _CONDITIONS},
        )
    finally:
        db.close()


@router.post("/listing/{listing_id}/edit")
def listing_edit_post(
    request: Request,
    listing_id: int,
    title: str = Form(...),
    author: str = Form(None),
    condition: str = Form(...),
    price: int = Form(None),
    course_code: str = Form(None),
    semester: int = Form(None),
    description: str = Form(None),
    is_exchange: str = Form(None),
):
    user = request.state.user
    if not user:
        return RedirectResponse("/login")

    db = SessionLocal()
    try:
        listing = db.query(Listing).filter(Listing.id == listing_id).first()
        if not listing or listing.seller_id != user.id:
            return templates.TemplateResponse(
                "error.html",
                {"request": request, "code": 403, "message": "Access denied."},
                status_code=403,
            )
        listing.title       = title.strip()
        listing.author      = (author or "").strip() or None
        listing.condition   = condition
        listing.price       = price
        listing.course_code = (course_code or "").strip().upper() or None
        listing.semester    = semester
        listing.description = (description or "").strip() or None
        listing.is_exchange = bool(is_exchange)
        db.commit()
    finally:
        db.close()

    return RedirectResponse(f"/listing/{listing_id}", status_code=302)


# ---------------------------------------------------------------------------
# Soft delete listing
# ---------------------------------------------------------------------------

@router.post("/listing/{listing_id}/delete")
def listing_delete(request: Request, listing_id: int):
    user = request.state.user
    if not user:
        return RedirectResponse("/login")

    db = SessionLocal()
    try:
        listing = db.query(Listing).filter(Listing.id == listing_id).first()
        if listing and listing.seller_id == user.id:
            listing.status = "unavailable"
            db.commit()
    finally:
        db.close()

    return RedirectResponse("/my-listings", status_code=302)


# ---------------------------------------------------------------------------
# My listings
# ---------------------------------------------------------------------------

@router.get("/my-listings")
def my_listings(request: Request):
    user = request.state.user
    if not user:
        return RedirectResponse("/login")

    db = SessionLocal()
    try:
        listings = (
            db.query(Listing)
            .filter(Listing.seller_id == user.id)
            .order_by(Listing.created_at.desc())
            .all()
        )
        return templates.TemplateResponse(
            "my_listings.html", {"request": request, "listings": listings}
        )
    finally:
        db.close()
