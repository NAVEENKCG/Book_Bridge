"""
seed.py — Populates the database with demo users and listings for hackathon demos.
Run: python seed.py
"""
from __future__ import annotations

from database import Base, SessionLocal, engine
import models  # noqa: F401 — registers ORM models with Base

from auth import get_password_hash

Base.metadata.create_all(bind=engine)
db = SessionLocal()

try:
    priya_email = "priya@demo.ac.in"
    arjun_email = "arjun@demo.ac.in"

    if db.query(models.User).filter(models.User.email == priya_email).first():
        print("Demo data already seeded. Skipping.")
    else:
        # --- Users ---
        priya = models.User(
            name="Priya Sharma",
            email=priya_email,
            hashed_password=get_password_hash("demo1234"),
            college="Demo Engineering College",
            department="Computer Science",
            semester=3,
            bookcoin_bal=80,
            exchange_count=3,
            rating=5,
        )
        arjun = models.User(
            name="Arjun Mehta",
            email=arjun_email,
            hashed_password=get_password_hash("demo1234"),
            college="Demo Engineering College",
            department="Electronics",
            semester=4,
            bookcoin_bal=65,
            exchange_count=1,
            rating=4,
        )
        db.add_all([priya, arjun])
        db.commit()
        db.refresh(priya)
        db.refresh(arjun)

        # --- Listings ---
        listings = [
            models.Listing(
                seller_id=priya.id,
                isbn="9780262033848",
                title="Introduction to Algorithms",
                author="Cormen, Leiserson, Rivest, Stein",
                cover_url="https://books.google.com/books/content?id=aefUBQAAQBAJ&printsec=frontcover&img=1&zoom=5",
                publisher="MIT Press",
                edition="3rd Edition",
                condition="Good",
                price=350,
                is_exchange=False,
                course_code="CS301",
                semester=3,
                college="Demo Engineering College",
                department="Computer Science",
                description="A few pencil marks in chapters 1-3. Otherwise clean.",
                status="available",
            ),
            models.Listing(
                seller_id=priya.id,
                isbn="9780070634718",
                title="Signals and Systems",
                author="Oppenheim & Willsky",
                publisher="Pearson",
                edition="2nd Edition",
                condition="Like New",
                price=None,
                is_exchange=True,
                course_code="EC401",
                semester=4,
                college="Demo Engineering College",
                department="Electronics",
                description="Pristine copy. Open to swapping for a Networks book.",
                status="available",
            ),
            models.Listing(
                seller_id=arjun.id,
                isbn="9788177588583",
                title="Engineering Mathematics Vol 2",
                author="B.S. Grewal",
                publisher="Khanna Publishers",
                edition="43rd Edition",
                condition="Fair",
                price=180,
                is_exchange=False,
                course_code="MA201",
                semester=2,
                college="Demo Engineering College",
                description="Written notes on a few pages, very helpful actually.",
                status="available",
            ),
        ]
        db.add_all(listings)

        # --- Wanted posts ---
        db.add(models.Wishlist(
            user_id=arjun.id,
            book_title="Data Communication and Networking",
            course_code="CS401",
            max_price=250,
        ))

        db.commit()
        print("Seeding complete!")
        print(f"  Priya:  {priya_email}  / password: demo1234")
        print(f"  Arjun:  {arjun_email}  / password: demo1234")

finally:
    db.close()
