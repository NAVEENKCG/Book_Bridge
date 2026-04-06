"""
routes/api.py — JSON API endpoints for ISBN lookup and Groq AI features.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import or_

from ai import fetch_isbn_metadata, stream_chatbot_groq, suggest_message_groq, suggest_price_groq
from database import SessionLocal
from models import Listing

router = APIRouter(prefix="/api")


# ---------------------------------------------------------------------------
# ISBN metadata proxy
# ---------------------------------------------------------------------------

@router.get("/isbn/{isbn}")
async def isbn_lookup(isbn: str):
    data = await fetch_isbn_metadata(isbn.strip())
    return JSONResponse(data or {})


# ---------------------------------------------------------------------------
# Price suggestion
# ---------------------------------------------------------------------------

class PriceSuggestBody(BaseModel):
    title: str
    edition: str = ""
    condition: str = "Good"


@router.post("/price-suggest")
async def price_suggest(body: PriceSuggestBody):
    result = await suggest_price_groq(body.title, body.edition, body.condition)
    return JSONResponse(result)


# ---------------------------------------------------------------------------
# Chat message suggestion
# ---------------------------------------------------------------------------

class SuggestMessageBody(BaseModel):
    book_title: str
    action: str = "confirm meetup"


@router.post("/suggest-message")
async def suggest_message(body: SuggestMessageBody):
    msg = await suggest_message_groq(body.book_title, body.action)
    return JSONResponse({"message": msg})


# ---------------------------------------------------------------------------
# Chat messages poll (used by JS instead of meta-refresh)
# ---------------------------------------------------------------------------

@router.get("/chat/{request_id}/messages")
def chat_messages_poll(request_id: int, request: Request):
    """Return messages for a chat thread as JSON. Only participants can access."""
    from models import ExchangeRequest, Message

    user = request.state.user
    if not user:
        return JSONResponse({"messages": []}, status_code=401)

    db = SessionLocal()
    try:
        ex = db.query(ExchangeRequest).filter(ExchangeRequest.id == request_id).first()
        if not ex or user.id not in (ex.requester_id, ex.seller_id):
            return JSONResponse({"messages": []}, status_code=403)

        msgs = (
            db.query(Message)
            .filter(Message.request_id == request_id)
            .order_by(Message.created_at)
            .all()
        )
        return JSONResponse({
            "messages": [
                {
                    "id": m.id,
                    "sender_id": m.sender_id,
                    "sender_name": m.sender.name,
                    "body": m.body,
                    "created_at": m.created_at.strftime("%H:%M") if m.created_at else "",
                }
                for m in msgs
            ]
        })
    finally:
        db.close()


# ---------------------------------------------------------------------------
# BookBot — streaming chatbot that searches live listings as context
# ---------------------------------------------------------------------------

@router.get("/chatbot/stream")
async def chatbot_stream(q: str, request: Request):
    """
    Streams a Groq-powered response for a student's book query.
    Searches ALL non-deleted listings (available + pending + completed)
    so the bot can still surface recently exchanged books.
    """
    q = (q or "").strip()[:300]  # sanitise

    # ── Search DB for matching listings ──────────────────────────────────
    db = SessionLocal()
    try:
        keywords = [w for w in q.split() if len(w) > 2][:8]

        # Exclude only hard-deleted/unavailable listings
        base = db.query(Listing).filter(Listing.status != "unavailable")

        if keywords:
            base = base.filter(
                or_(*[
                    or_(
                        Listing.title.ilike(f"%{kw}%"),
                        Listing.author.ilike(f"%{kw}%"),
                        Listing.course_code.ilike(f"%{kw}%"),
                    )
                    for kw in keywords
                ])
            )

        listings = base.order_by(Listing.created_at.desc()).limit(5).all()

        if listings:
            lines = []
            for lst in listings:
                price = f"₹{lst.price}" if lst.price else "Exchange only"
                status_label = {
                    "available": "Available ✅",
                    "pending":   "Pending exchange ⏳",
                    "completed": "Already exchanged ✔️",
                }.get(lst.status, lst.status)
                lines.append(
                    f"- '{lst.title}' by {lst.author or 'Unknown'} | "
                    f"{lst.condition} | {price} | {status_label} | /listing/{lst.id}"
                )
            context = "\n".join(lines)
        else:
            context = ""
    finally:
        db.close()

    # ── Stream Groq tokens back as plain text ─────────────────────────────
    async def generate():
        async for token in stream_chatbot_groq(q, context):
            yield token

    return StreamingResponse(generate(), media_type="text/plain; charset=utf-8")
