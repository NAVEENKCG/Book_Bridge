import os
from typing import Optional

import bcrypt as _bcrypt
from dotenv import load_dotenv
from fastapi import Request
from itsdangerous import BadSignature, SignatureExpired, TimestampSigner
from sqlalchemy.orm import Session

load_dotenv()

SECRET_KEY: str = os.getenv("SECRET_KEY", "insecure-default-change-me")
COOKIE_NAME: str = os.getenv("COOKIE_NAME", "bookbridge_session")
COOKIE_MAX_AGE: int = int(os.getenv("COOKIE_MAX_AGE", "86400"))

_signer = TimestampSigner(SECRET_KEY)


# ---------------------------------------------------------------------------
# Password helpers
# ---------------------------------------------------------------------------

def get_password_hash(password: str) -> str:
    return _bcrypt.hashpw(password.encode(), _bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Cookie helpers
# ---------------------------------------------------------------------------

def create_session_cookie(user_id: int) -> str:
    """Return a URL-safe signed token embedding the user_id."""
    return _signer.sign(str(user_id)).decode("utf-8")


def _parse_session_cookie(value: str) -> Optional[int]:
    try:
        raw = _signer.unsign(value, max_age=COOKIE_MAX_AGE)
        return int(raw.decode("utf-8"))
    except (SignatureExpired, BadSignature, ValueError):
        return None


# ---------------------------------------------------------------------------
# Current-user resolver (sync — used in middleware and route deps)
# ---------------------------------------------------------------------------

def get_current_user(request: Request):
    """
    Read the signed session cookie, verify it, and return the matching User
    ORM object. Returns None if unauthenticated or token invalid.
    """
    cookie = request.cookies.get(COOKIE_NAME)
    if not cookie:
        return None
    user_id = _parse_session_cookie(cookie)
    if user_id is None:
        return None

    # Import here to avoid circular imports at module level.
    from database import SessionLocal
    from models import User

    db: Session = SessionLocal()
    try:
        return db.query(User).filter(User.id == user_id).first()
    finally:
        db.close()
