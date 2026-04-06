"""
routes/exchange.py — Exchange requests, chat, accept/reject/complete,
                     college isolation, chat rate-limiting, rating, notifications.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func

from database import SessionLocal
from models import ExchangeRequest, Listing, Message, Notification, User

router = APIRouter()
templates = Jinja2Templates(directory="templates")


def _now() -> datetime:
    return datetime.utcnow()


def _emit(db, user_id: int, message: str, link: str | None = None) -> None:
    db.add(Notification(user_id=user_id, message=message, link=link))


# ---------------------------------------------------------------------------
# Create / redirect to existing request
# ---------------------------------------------------------------------------

@router.post("/request/{listing_id}")
def create_request(request: Request, listing_id: int):
    user = request.state.user
    if not user:
        return RedirectResponse("/login")

    db = SessionLocal()
    try:
        listing = db.query(Listing).filter(Listing.id == listing_id).first()
        if not listing or listing.seller_id == user.id:
            return RedirectResponse(f"/listing/{listing_id}")

        # ── College isolation (email-domain based) ───────────────────────────
        if user.college_domain and listing.college_domain and user.college_domain != listing.college_domain:
            return templates.TemplateResponse(
                "error.html",
                {
                    "request": request,
                    "code": 403,
                    "message": "Cross-college exchange requests are not allowed.",
                },
                status_code=403,
            )

        existing = (
            db.query(ExchangeRequest)
            .filter(
                ExchangeRequest.listing_id == listing_id,
                ExchangeRequest.requester_id == user.id,
            )
            .first()
        )
        if existing:
            return RedirectResponse(f"/chat/{existing.id}", status_code=302)

        ex = ExchangeRequest(
            listing_id=listing.id,
            requester_id=user.id,
            seller_id=listing.seller_id,
        )
        db.add(ex)
        db.flush()

        # Notify seller
        _emit(
            db,
            listing.seller_id,
            f"📥 {user.name} requested your book: {listing.title}",
            f"/chat/{ex.id}",
        )

        db.commit()
        db.refresh(ex)
        ex_id = ex.id
    finally:
        db.close()

    return RedirectResponse(f"/chat/{ex_id}", status_code=302)


# ---------------------------------------------------------------------------
# My requests dashboard
# ---------------------------------------------------------------------------

@router.get("/my-requests")
def my_requests(request: Request):
    user = request.state.user
    if not user:
        return RedirectResponse("/login")

    db = SessionLocal()
    try:
        # Defensive: also join Listing and filter by college_domain so a
        # cross-college request that somehow slipped through is never surfaced.
        incoming = (
            db.query(ExchangeRequest)
            .join(Listing, Listing.id == ExchangeRequest.listing_id)
            .filter(
                ExchangeRequest.seller_id == user.id,
                Listing.college_domain == user.college_domain,
            )
            .order_by(ExchangeRequest.created_at.desc())
            .all()
        )
        outgoing = (
            db.query(ExchangeRequest)
            .join(Listing, Listing.id == ExchangeRequest.listing_id)
            .filter(
                ExchangeRequest.requester_id == user.id,
                Listing.college_domain == user.college_domain,
            )
            .order_by(ExchangeRequest.created_at.desc())
            .all()
        )
        return templates.TemplateResponse(
            "my_requests.html",
            {"request": request, "incoming": incoming, "outgoing": outgoing},
        )
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Chat thread
# ---------------------------------------------------------------------------

@router.get("/chat/{request_id}")
def chat_get(request: Request, request_id: int):
    user = request.state.user
    if not user:
        return RedirectResponse("/login")

    db = SessionLocal()
    try:
        ex = db.query(ExchangeRequest).filter(ExchangeRequest.id == request_id).first()
        if not ex:
            return RedirectResponse("/my-requests")

        # Only participants can view
        if user.id not in (ex.requester_id, ex.seller_id):
            return templates.TemplateResponse(
                "error.html",
                {"request": request, "code": 403, "message": "Access denied."},
                status_code=403,
            )

        messages = (
            db.query(Message)
            .filter(Message.request_id == request_id)
            .order_by(Message.created_at)
            .all()
        )
        seller  = db.query(User).filter(User.id == ex.seller_id).first()
        buyer   = db.query(User).filter(User.id == ex.requester_id).first()
        listing = db.query(Listing).filter(Listing.id == ex.listing_id).first()

        # Has the current user already rated this exchange?
        already_rated = False
        if ex.status == "completed":
            if user.id == ex.requester_id:
                already_rated = ex.buyer_rating is not None
            else:
                already_rated = ex.seller_rating is not None

        return templates.TemplateResponse(
            "chat.html",
            {
                "request": request,
                "exchange": ex,
                "messages": messages,
                "seller": seller,
                "buyer": buyer,
                "listing": listing,
                "already_rated": already_rated,
            },
        )
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Send message (with 2-second cooldown)
# ---------------------------------------------------------------------------

@router.post("/chat/{request_id}/send")
def chat_send(request: Request, request_id: int, body: str = Form(...)):
    user = request.state.user
    if not user:
        return RedirectResponse("/login")

    db = SessionLocal()
    try:
        ex = db.query(ExchangeRequest).filter(ExchangeRequest.id == request_id).first()
        if ex and ex.status in ("pending", "accepted"):
            # ── 2-second anti-spam cooldown ───────────────────────────────────
            if ex.last_message_at:
                elapsed = (_now() - ex.last_message_at).total_seconds()
                if elapsed < 2:
                    return RedirectResponse(f"/chat/{request_id}", status_code=302)

            msg = Message(request_id=request_id, sender_id=user.id, body=body.strip())
            db.add(msg)
            ex.last_message_at = _now()
            db.commit()
    finally:
        db.close()

    return RedirectResponse(f"/chat/{request_id}", status_code=302)


# ---------------------------------------------------------------------------
# Accept request
# ---------------------------------------------------------------------------

@router.post("/chat/{request_id}/accept")
def chat_accept(request: Request, request_id: int):
    user = request.state.user
    if not user:
        return RedirectResponse("/login")

    db = SessionLocal()
    try:
        ex = db.query(ExchangeRequest).filter(ExchangeRequest.id == request_id).first()
        if ex and ex.seller_id == user.id and ex.status == "pending":
            ex.status = "accepted"
            listing = db.query(Listing).filter(Listing.id == ex.listing_id).first()
            title = listing.title if listing else "your request"
            _emit(db, ex.requester_id, f"✅ Your request for '{title}' was accepted!", f"/chat/{request_id}")
            db.commit()
    finally:
        db.close()

    return RedirectResponse(f"/chat/{request_id}", status_code=302)


# ---------------------------------------------------------------------------
# Reject request
# ---------------------------------------------------------------------------

@router.post("/chat/{request_id}/reject")
def chat_reject(request: Request, request_id: int):
    user = request.state.user
    if not user:
        return RedirectResponse("/login")

    db = SessionLocal()
    try:
        ex = db.query(ExchangeRequest).filter(ExchangeRequest.id == request_id).first()
        if ex and ex.seller_id == user.id and ex.status == "pending":
            ex.status = "rejected"
            listing = db.query(Listing).filter(Listing.id == ex.listing_id).first()
            title = listing.title if listing else "your request"
            _emit(db, ex.requester_id, f"❌ Your request for '{title}' was declined.", f"/chat/{request_id}")
            db.commit()
    finally:
        db.close()

    return RedirectResponse(f"/chat/{request_id}", status_code=302)


# ---------------------------------------------------------------------------
# Complete exchange
# ---------------------------------------------------------------------------

@router.post("/chat/{request_id}/complete")
def chat_complete(request: Request, request_id: int):
    user = request.state.user
    if not user:
        return RedirectResponse("/login")

    db = SessionLocal()
    try:
        ex = db.query(ExchangeRequest).filter(ExchangeRequest.id == request_id).first()
        if not ex or ex.status != "accepted":
            return RedirectResponse(f"/chat/{request_id}")

        if user.id not in (ex.seller_id, ex.requester_id):
            return RedirectResponse(f"/chat/{request_id}")

        seller_row = db.query(User).filter(User.id == ex.seller_id).first()
        buyer_row  = db.query(User).filter(User.id == ex.requester_id).first()

        # ── All mutations happen before commit ────────────────────────────────
        seller_row.bookcoin_bal   = (seller_row.bookcoin_bal or 0) + 15
        buyer_row.bookcoin_bal    = (buyer_row.bookcoin_bal or 0) + 5
        seller_row.exchange_count = (seller_row.exchange_count or 0) + 1
        buyer_row.exchange_count  = (buyer_row.exchange_count or 0) + 1
        ex.status = "completed"

        listing = db.query(Listing).filter(Listing.id == ex.listing_id).first()
        if listing:
            listing.status = "completed"
            _emit(db, ex.seller_id,    f"🎉 Exchange for '{listing.title}' completed! +15 BookCoins", f"/chat/{request_id}")
            _emit(db, ex.requester_id, f"🎉 Exchange for '{listing.title}' completed! +5 BookCoins",  f"/chat/{request_id}")

        # Single atomic commit — if this fails, nothing above is persisted
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    return RedirectResponse(f"/chat/{request_id}", status_code=302)


# ---------------------------------------------------------------------------
# Update meetup details
# ---------------------------------------------------------------------------

@router.post("/chat/{request_id}/meetup")
def chat_meetup(
    request: Request,
    request_id: int,
    meetup_location: str = Form(None),
    meetup_time: str = Form(None),
):
    user = request.state.user
    if not user:
        return RedirectResponse("/login")

    db = SessionLocal()
    try:
        ex = db.query(ExchangeRequest).filter(ExchangeRequest.id == request_id).first()
        if ex and user.id in (ex.seller_id, ex.requester_id) and ex.status == "accepted":
            if meetup_location:
                ex.meetup_location = meetup_location.strip()
            if meetup_time:
                ex.meetup_time = meetup_time.strip()

            # Notify the OTHER participant
            other_id = ex.requester_id if user.id == ex.seller_id else ex.seller_id
            listing = db.query(Listing).filter(Listing.id == ex.listing_id).first()
            title = listing.title if listing else "the book"
            loc = meetup_location or ex.meetup_location or ""
            time_str = meetup_time or ex.meetup_time or ""
            _emit(
                db, other_id,
                f"📍 Meetup set for '{title}': {loc} @ {time_str}",
                f"/chat/{request_id}",
            )
            db.commit()
    finally:
        db.close()

    return RedirectResponse(f"/chat/{request_id}", status_code=302)


# ---------------------------------------------------------------------------
# Submit rating (post-completion)
# ---------------------------------------------------------------------------

@router.post("/chat/{request_id}/rate")
def chat_rate(request: Request, request_id: int, rating: int = Form(...)):
    user = request.state.user
    if not user:
        return RedirectResponse("/login")

    rating = max(1, min(5, rating))  # clamp 1–5

    db = SessionLocal()
    try:
        ex = db.query(ExchangeRequest).filter(ExchangeRequest.id == request_id).first()
        if not ex or ex.status != "completed":
            return RedirectResponse(f"/chat/{request_id}")

        if user.id == ex.requester_id and ex.buyer_rating is None:
            # Buyer rates seller
            ex.buyer_rating = rating
            rated_user = db.query(User).filter(User.id == ex.seller_id).first()
        elif user.id == ex.seller_id and ex.seller_rating is None:
            # Seller rates buyer
            ex.seller_rating = rating
            rated_user = db.query(User).filter(User.id == ex.requester_id).first()
        else:
            return RedirectResponse(f"/chat/{request_id}")

        # Recompute average using DB aggregates — avoids N+1 Python loop
        if rated_user:
            # Average of ratings received AS SELLER (buyer_rating on their exchanges)
            avg_as_seller = (
                db.query(func.avg(ExchangeRequest.buyer_rating))
                .filter(
                    ExchangeRequest.seller_id == rated_user.id,
                    ExchangeRequest.buyer_rating.isnot(None),
                    ExchangeRequest.status == "completed",
                )
                .scalar()
            )
            # Average of ratings received AS BUYER (seller_rating on their exchanges)
            avg_as_buyer = (
                db.query(func.avg(ExchangeRequest.seller_rating))
                .filter(
                    ExchangeRequest.requester_id == rated_user.id,
                    ExchangeRequest.seller_rating.isnot(None),
                    ExchangeRequest.status == "completed",
                )
                .scalar()
            )
            combined = [v for v in (avg_as_seller, avg_as_buyer) if v is not None]
            if combined:
                rated_user.rating = round(sum(combined) / len(combined))

            # Reputation penalty: if new rating is <3, subtract 1 point
            if rating < 3 and rated_user.rating > 1:
                rated_user.rating = max(1, rated_user.rating - 1)

            _emit(
                db, rated_user.id,
                f"⭐ You received a {rating}-star rating!",
                f"/profile/{rated_user.id}",
            )

        db.commit()
    finally:
        db.close()

    return RedirectResponse(f"/chat/{request_id}", status_code=302)
