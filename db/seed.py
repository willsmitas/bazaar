"""
seed.py — Insert sample users and listings for local development.

Idempotent: running it more than once won't create duplicates. Every sample
account uses the password "testpass123" and is pre-verified.

    py -m db.seed
"""
from decimal import Decimal

from db.database import SessionLocal
from db.models import ItemCondition, Listing, ListingStatus, ListingType, User
from server.security import hash_password

PASSWORD = "testpass123"

USERS = [
    ("test@brown.edu",   "Test Student"),   # the account you log in as
    ("ava@brown.edu",    "Ava Chen"),
    ("marcus@brown.edu", "Marcus Lee"),
    ("priya@brown.edu",  "Priya Patel"),
]

# seller_email, type, title, description, category, condition, price_min, price_max
LISTINGS = [
    ("ava@brown.edu",    ListingType.sell, "TI-84 Plus Calculator",
     "Like new, only used for MATH 100. Comes with cover and batteries.",
     "Electronics", ItemCondition.like_new, 40, 55),
    ("ava@brown.edu",    ListingType.sell, "Mini Fridge (dorm-sized)",
     "Works perfectly, defrosted and clean. Great for a dorm room.",
     "Furniture", ItemCondition.good, 30, 80),
    ("marcus@brown.edu", ListingType.sell, "North Face Jester Backpack",
     "Navy, great condition. Barely used after switching to a tote bag.",
     "Clothing", ItemCondition.good, 35, 50),
    ("marcus@brown.edu", ListingType.sell, '27" HP Monitor (1080p)',
     "60Hz, no dead pixels. Power cable and HDMI included.",
     "Electronics", ItemCondition.good, 90, 130),
    ("priya@brown.edu",  ListingType.sell, "Organic Chem Textbook (8th ed.)",
     "Klein's Organic Chemistry, 8th edition. Light pencil marks, mostly erased.",
     "Books", ItemCondition.good, 40, 70),
    ("priya@brown.edu",  ListingType.sell, "Desk Lamp — IKEA Tertial",
     "Black. Works perfectly, just upgraded to a floor lamp.",
     "Furniture", ItemCondition.like_new, 8, 15),
    ("test@brown.edu",   ListingType.sell, "Physics 101 Notes Bundle",
     "A full semester of typed notes plus solved practice problems.",
     "Books", ItemCondition.good, 10, 20),
    ("marcus@brown.edu", ListingType.request, "Commuter Bike Wanted",
     "Any hybrid/commuter bike that works. Functional brakes a must.",
     "Other", None, 50, 120),
    ("priya@brown.edu",  ListingType.request, "Looking for a Desk Chair",
     "Ergonomic if possible. Can pick up anywhere on campus.",
     "Furniture", None, 20, 60),
]


def main() -> None:
    db = SessionLocal()
    try:
        users = {}
        for email, name in USERS:
            user = db.query(User).filter(User.email == email).first()
            if not user:
                user = User(
                    email=email,
                    full_name=name,
                    password_hash=hash_password(PASSWORD),
                    university="Brown University",
                    email_verified=True,
                )
                db.add(user)
                db.flush()            # assign user_id before listings reference it
                print(f"created user  {email}")
            users[email] = user

        created = 0
        for email, ltype, title, desc, cat, cond, pmin, pmax in LISTINGS:
            seller = users[email]
            already = (
                db.query(Listing)
                .filter(Listing.seller_id == seller.user_id, Listing.title == title)
                .first()
            )
            if already:
                continue
            db.add(Listing(
                seller_id=seller.user_id,
                type=ltype,
                title=title,
                description=desc,
                category=cat,
                condition=cond,
                price_min=Decimal(pmin),
                price_max=Decimal(pmax),
                status=ListingStatus.active,
            ))
            created += 1

        db.commit()
        print(f"created {created} listings")
        print(f"\nAll sample accounts use password: {PASSWORD}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
