from __future__ import annotations

import argparse

from app.config import get_settings
from app.database import create_session_factory
from app.seed import seed_demo_users


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed demo users for the assignment.")
    parser.add_argument("--reset", action="store_true", help="Reset local data before seeding.")
    args = parser.parse_args()

    settings = get_settings()
    session_factory = create_session_factory(settings.database_url)
    db = session_factory()
    try:
        created_users = seed_demo_users(db, reset=args.reset)
    finally:
        db.close()

    print("Seed completed.")
    if created_users:
        print("Created users:", ", ".join(created_users))
    else:
        print("No new users were created.")


if __name__ == "__main__":
    main()
