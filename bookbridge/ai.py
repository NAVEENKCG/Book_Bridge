"""
ai.py — Google Books / Open Library ISBN lookup and Groq AI stubs.
All Groq calls use llama-3.1-8b-instant for speed.
"""
from __future__ import annotations

import os
from typing import Any

import httpx
from dotenv import load_dotenv

load_dotenv()

GOOGLE_BOOKS_KEY: str = os.getenv("GOOGLE_BOOKS_KEY", "")
GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")

_GROQ_ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"
_DEFAULT_MODEL = "llama-3.1-8b-instant"


# ---------------------------------------------------------------------------
# ISBN → metadata
# ---------------------------------------------------------------------------

async def fetch_isbn_metadata(isbn: str) -> dict[str, Any]:
    """
    Try Open Library first (no key required), fall back to Google Books.
    Always returns a dict — never raises.
    """
    result = await _fetch_open_library(isbn)
    if result:
        return result
    return await _fetch_google_books(isbn)


async def _fetch_open_library(isbn: str) -> dict[str, Any]:
    """
    Uses the Open Library Books API with jscmd=data — no key needed,
    returns resolved authors, cover images, publisher, and year in one shot.
    https://openlibrary.org/api/books?bibkeys=ISBN:XXX&format=json&jscmd=data
    """
    url = "https://openlibrary.org/api/books"
    params = {
        "bibkeys": f"ISBN:{isbn}",
        "format": "json",
        "jscmd": "data",
    }
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.get(url, params=params)
        if r.status_code != 200:
            return {}
        payload = r.json()
        data = payload.get(f"ISBN:{isbn}")
        if not data:
            return {}

        title = data.get("title", "")

        # Authors — already resolved as [{"name": "..."}, ...]
        authors = [a.get("name", "") for a in data.get("authors", []) if a.get("name")]

        # Cover — prefer "large", fall back to "medium"
        covers = data.get("cover", {})
        cover_url = covers.get("large") or covers.get("medium") or covers.get("small") or ""

        # Publisher — list of {"name": "..."} dicts
        publishers = data.get("publishers", [])
        publisher = publishers[0].get("name", "") if publishers else ""

        # Edition / year
        edition = data.get("edition_name", "")
        publish_date = data.get("publish_date", "")
        if not edition and publish_date:
            edition = publish_date  # e.g. "2009"

        # Number of pages (bonus field)
        num_pages = data.get("number_of_pages")

        return {
            "title": title,
            "authors": authors,
            "publisher": publisher,
            "edition": edition,
            "cover_url": cover_url,
            "num_pages": num_pages,
        }
    except Exception:
        return {}


async def _fetch_google_books(isbn: str) -> dict[str, Any]:
    params: dict = {"q": f"isbn:{isbn}"}
    if GOOGLE_BOOKS_KEY:
        params["key"] = GOOGLE_BOOKS_KEY
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.get("https://www.googleapis.com/books/v1/volumes", params=params)
        if r.status_code != 200:
            return {}
        items = r.json().get("items") or []
        if not items:
            return {}
        info = items[0].get("volumeInfo", {})
        cover_url = (info.get("imageLinks") or {}).get("thumbnail", "")
        return {
            "title": info.get("title", ""),
            "authors": info.get("authors", []),
            "publisher": info.get("publisher", ""),
            "edition": "",
            "cover_url": cover_url,
        }
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Groq helpers (async)
# ---------------------------------------------------------------------------

async def _groq_chat(prompt: str, system: str = "You are a helpful assistant.") -> str:
    """Post a single-turn chat to Groq and return the reply text."""
    if not GROQ_API_KEY:
        return ""
    payload = {
        "model": _DEFAULT_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": 256,
        "temperature": 0.4,
    }
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(_GROQ_ENDPOINT, json=payload, headers=headers)
        if r.status_code == 200:
            return r.json()["choices"][0]["message"]["content"].strip()
    except Exception:
        pass
    return ""


async def suggest_price_groq(title: str, edition: str, condition: str) -> dict[str, Any]:
    """
    Returns {min: int, max: int, reason: str} — either from Groq or a
    rule-based fallback so the UI always gets something useful.
    """
    # Rule-based fallback (always computed first as default)
    _factor = {"New": 1.0, "Like New": 0.8, "Good": 0.6, "Fair": 0.4, "Poor": 0.2}
    base = 250
    f = _factor.get(condition, 0.6)
    fallback = {"min": int(base * f * 0.8), "max": int(base * f * 1.3), "reason": "Rule-based estimate."}

    if not GROQ_API_KEY:
        return fallback

    prompt = (
        f"A student is selling '{title}' ({edition or 'unknown edition'}), condition: {condition}. "
        "Suggest a fair second-hand price range in Indian Rupees. "
        'Reply ONLY with valid JSON: {"min": <int>, "max": <int>, "reason": "<1 sentence>"}'
    )
    reply = await _groq_chat(prompt, system="You are a pricing expert for Indian college textbooks.")
    try:
        import json
        # strip potential markdown fences
        clean = reply.strip().lstrip("```json").rstrip("```").strip()
        data = json.loads(clean)
        return {
            "min": int(data.get("min", fallback["min"])),
            "max": int(data.get("max", fallback["max"])),
            "reason": str(data.get("reason", fallback["reason"])),
        }
    except Exception:
        return fallback


async def suggest_message_groq(book_title: str, action: str) -> str:
    """
    Returns a short, casual peer-to-peer message for a campus book exchange chat.
    action examples: 'ask if still available', 'suggest meeting at library', etc.
    """
    # Sensible no-key fallback keyed to common actions
    _fallbacks = {
        "ask if still available": f"Hey! Is '{book_title}' still available?",
        "suggest meeting at library": f"Hey, want to meet at the college library to exchange '{book_title}'? Works for me anytime this week!",
        "confirm meetup": f"Just checking — are we still on for the exchange? Let me know a time that suits you!",
        "ask for price": f"Hi! What's the final price for '{book_title}'? Any room to negotiate?",
    }
    fallback = _fallbacks.get(action, f"Hey! Wanted to follow up about '{book_title}'. Let me know when you're free!")

    if not GROQ_API_KEY:
        return fallback

    prompt = (
        f"You are writing a short WhatsApp-style message between two college students on a book-exchange app. "
        f"One student wants to {action} regarding the book '{book_title}'. "
        f"Rules: casual and friendly tone, 1-2 sentences max, no formal greetings like 'Dear' or 'Hi Professor', "
        f"no sign-off like 'Regards' or '[Your Name]', no markdown, just the plain message text."
    )
    reply = await _groq_chat(
        prompt,
        system=(
            "You write ultra-short, casual messages between Indian college students on a book-exchange platform. "
            "Output ONLY the message text — no subject line, no sign-off, no placeholders."
        ),
    )
    # Strip any residual placeholder patterns Groq might generate
    import re
    reply = re.sub(r"\[.*?\]", "", reply).strip(" \n,")
    return reply or fallback


async def stream_chatbot_groq(question: str, listings_context: str):
    """
    Async generator — yields Groq response tokens one by one for streaming.
    listings_context is a pre-built string of matching DB listings.
    Falls back to a single plain-text chunk when GROQ_API_KEY is not set.
    """
    import json as _json

    if not GROQ_API_KEY:
        if listings_context:
            yield (
                "I found some listings that might help! Check the results below "
                "and click on a listing to request the book. You can also post a "
                "Wanted request if you don't see what you need."
            )
        else:
            yield (
                "I couldn't find a matching listing right now. Try searching on "
                "the homepage or post a Wanted request so sellers can find you!"
            )
        return

    system = (
        "You are BookBot, a friendly assistant on BookBridge — a campus book-exchange platform for Indian college students. "
        "Students ask you if specific books are available or request recommendations. "
        "You have access to the real-time listings shown below. "
        "Rules: keep replies to 2-4 short sentences, be casual and helpful, "
        "if a matching listing exists mention its title and that they can click it, "
        "if nothing matches suggest posting a Wanted request. Never fabricate listing details."
    )
    user_prompt = (
        f"Currently available listings (may be partial):\n"
        f"{listings_context or 'None found matching the query.'}\n\n"
        f"Student asks: {question}"
    )

    payload = {
        "model": _DEFAULT_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": 200,
        "temperature": 0.65,
        "stream": True,
    }
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            async with client.stream("POST", _GROQ_ENDPOINT, json=payload, headers=headers) as r:
                async for line in r.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    chunk_str = line[6:].strip()
                    if chunk_str == "[DONE]":
                        break
                    try:
                        delta = _json.loads(chunk_str)["choices"][0]["delta"].get("content", "")
                        if delta:
                            yield delta
                    except Exception:
                        continue
    except Exception:
        yield " (BookBot is having trouble connecting — please try again shortly.)"


