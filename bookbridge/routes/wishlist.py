"""
routes/wishlist.py — Save/unsave specific listings (ListingWishlist), view wishlist.
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import IntegrityError

from database import SessionLocal
from models import Listing, ListingWishlist

router = APIRouter()
templates = Jinja2Templates(directory="templates")


# ---------------------------------------------------------------------------
# View wishlist
# ---------------------------------------------------------------------------

@router.get("/wishlist")
def wishlist_page(request: Request):
    user = request.state.user
    if not user:
        return RedirectResponse("/login")

    db = SessionLocal()
    try:
        rows = (
            db.query(ListingWishlist)
            .filter(ListingWishlist.user_id == user.id)
            .order_by(ListingWishlist.created_at.desc())
            .all()
        )
        listings = [r.listing for r in rows if r.listing]
        return templates.TemplateResponse(
            "wishlist.html", {"request": request, "listings": listings}
        )
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Toggle wishlist (add if not saved, remove if already saved)
# ---------------------------------------------------------------------------

@router.post("/wishlist/{listing_id}")
def wishlist_toggle(request: Request, listing_id: int):
    user = request.state.user
    if not user:
        return RedirectResponse("/login")

    db = SessionLocal()
    try:
        existing = (
            db.query(ListingWishlist)
            .filter(
                ListingWishlist.user_id == user.id,
                ListingWishlist.listing_id == listing_id,
            )
            .first()
        )
        if existing:
            db.delete(existing)
        else:
            db.add(ListingWishlist(user_id=user.id, listing_id=listing_id))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
    finally:
        db.close()

    return RedirectResponse(f"/listing/{listing_id}", status_code=302)


# ---------------------------------------------------------------------------
# Remove from wishlist (separate form action)
# ---------------------------------------------------------------------------

@router.post("/wishlist/{listing_id}/remove")
def wishlist_remove(request: Request, listing_id: int):
    user = request.state.user
    if not user:
        return RedirectResponse("/login")

    db = SessionLocal()
    try:
        row = (
            db.query(ListingWishlist)
            .filter(
                ListingWishlist.user_id == user.id,
                ListingWishlist.listing_id == listing_id,
            )
            .first()
        )
        if row:
            db.delete(row)
            db.commit()
    finally:
        db.close()

    return RedirectResponse("/wishlist", status_code=302)
