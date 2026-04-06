from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey,
    Integer, String, Text, func, UniqueConstraint,
)
from sqlalchemy.orm import relationship
from database import Base


def _expire_default():
    """90-day expiry from now — used as Python-level default."""
    return datetime.utcnow() + timedelta(days=90)


class User(Base):
    __tablename__ = "users"

    id                = Column(Integer, primary_key=True, index=True)
    name              = Column(String(128), nullable=False)
    email             = Column(String(256), unique=True, index=True, nullable=False)
    hashed_password   = Column(String(256), nullable=False)
    college           = Column(String(128), nullable=True)
    department        = Column(String(128), nullable=True)
    semester          = Column(Integer, nullable=True)
    bookcoin_bal      = Column(Integer, default=50, nullable=False)
    exchange_count    = Column(Integer, default=0, nullable=False)
    rating            = Column(Integer, default=5, nullable=False)
    # Anti-spam: track when a user last created a listing
    last_listed_at    = Column(DateTime, nullable=True)
    # Tamper-proof institutional isolation — derived from email, never user-input
    college_domain    = Column(String(128), index=True, nullable=True)
    created_at        = Column(DateTime(timezone=True), server_default=func.now())

    listings          = relationship("Listing", back_populates="seller", foreign_keys="Listing.seller_id")
    sent_requests     = relationship("ExchangeRequest", back_populates="requester", foreign_keys="ExchangeRequest.requester_id")
    wishlists         = relationship("Wishlist", back_populates="user")
    listing_wishlists = relationship("ListingWishlist", back_populates="user")
    notifications     = relationship("Notification", back_populates="user", order_by="Notification.created_at.desc()")


class Listing(Base):
    __tablename__ = "listings"

    id          = Column(Integer, primary_key=True, index=True)
    seller_id   = Column(Integer, ForeignKey("users.id"), nullable=False)
    isbn        = Column(String(64), nullable=True, index=True)
    title       = Column(String(512), nullable=False)
    author      = Column(String(512), nullable=True)
    cover_url   = Column(String(1024), nullable=True)
    publisher   = Column(String(256), nullable=True)
    edition     = Column(String(128), nullable=True)
    condition   = Column(String(64), nullable=False)
    price       = Column(Integer, nullable=True)
    is_exchange = Column(Boolean, default=False)
    course_code = Column(String(64), index=True, nullable=True)
    semester    = Column(Integer, nullable=True)
    college     = Column(String(128), nullable=True)
    department  = Column(String(128), nullable=True)
    description = Column(Text, nullable=True)
    # Derived from seller's email domain — used for tamper-proof campus isolation
    college_domain = Column(String(128), index=True, nullable=True)
    # available / pending / completed / unavailable
    status      = Column(String(32), default="available", nullable=False)
    # Lifecycle: auto-expire after 90 days
    expires_at  = Column(DateTime, nullable=True, default=_expire_default)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())

    seller             = relationship("User", back_populates="listings", foreign_keys=[seller_id])
    requests           = relationship("ExchangeRequest", back_populates="listing")
    listing_wishlists  = relationship("ListingWishlist", back_populates="listing")


class ExchangeRequest(Base):
    __tablename__ = "exchange_requests"

    id               = Column(Integer, primary_key=True, index=True)
    listing_id       = Column(Integer, ForeignKey("listings.id"), nullable=False)
    requester_id     = Column(Integer, ForeignKey("users.id"), nullable=False)
    seller_id        = Column(Integer, ForeignKey("users.id"), nullable=False)
    # pending / accepted / rejected / completed
    status           = Column(String(32), default="pending", nullable=False)
    meetup_location  = Column(String(256), nullable=True)
    meetup_time      = Column(String(128), nullable=True)
    buyer_rating     = Column(Integer, nullable=True)   # rating given TO seller by buyer
    seller_rating    = Column(Integer, nullable=True)   # rating given TO buyer by seller
    # Anti-spam: track last message timestamp
    last_message_at  = Column(DateTime, nullable=True)
    created_at       = Column(DateTime(timezone=True), server_default=func.now())

    listing      = relationship("Listing", back_populates="requests")
    requester    = relationship("User", back_populates="sent_requests", foreign_keys=[requester_id])
    seller       = relationship("User", foreign_keys=[seller_id])
    messages     = relationship("Message", back_populates="exchange_request", order_by="Message.created_at")


class Message(Base):
    __tablename__ = "messages"

    id         = Column(Integer, primary_key=True, index=True)
    request_id = Column(Integer, ForeignKey("exchange_requests.id"), nullable=False)
    sender_id  = Column(Integer, ForeignKey("users.id"), nullable=False)
    body       = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    exchange_request = relationship("ExchangeRequest", back_populates="messages")
    sender           = relationship("User")


class Wishlist(Base):
    """Wanted-board post: user wants a book by title (not tied to a specific listing)."""
    __tablename__ = "wishlists"

    id         = Column(Integer, primary_key=True, index=True)
    user_id    = Column(Integer, ForeignKey("users.id"), nullable=False)
    book_title = Column(String(512), nullable=False)
    course_code = Column(String(64), nullable=True)
    max_price  = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="wishlists")


class ListingWishlist(Base):
    """Heart/save a specific listing — personal bookmark."""
    __tablename__ = "listing_wishlists"

    id         = Column(Integer, primary_key=True, index=True)
    user_id    = Column(Integer, ForeignKey("users.id"), nullable=False)
    listing_id = Column(Integer, ForeignKey("listings.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("user_id", "listing_id", name="uq_user_listing_wishlist"),)

    user    = relationship("User", back_populates="listing_wishlists")
    listing = relationship("Listing", back_populates="listing_wishlists")


class Notification(Base):
    """In-app notification for a user."""
    __tablename__ = "notifications"

    id         = Column(Integer, primary_key=True, index=True)
    user_id    = Column(Integer, ForeignKey("users.id"), nullable=False)
    message    = Column(String(512), nullable=False)
    link       = Column(String(256), nullable=True)
    is_read    = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="notifications")
