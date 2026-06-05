from __future__ import annotations

from sqlalchemy.orm import Session

from app import models
from app.security import hash_secret


DEMO_USERS = [
    {
        "full_name": "Admin User",
        "email": "admin@example.com",
        "password": "Password123!",
        "role": "admin",
    },
    {
        "full_name": "James Bond",
        "email": "jamesbond@example.com",
        "password": "Password123!",
        "role": "staff",
    },
]


def reset_demo_data(db: Session) -> None:
    db.query(models.Task).delete()
    db.query(models.LoginChallenge).delete()
    db.query(models.EmailLog).delete()
    db.query(models.User).delete()
    db.commit()


def seed_demo_users(db: Session, reset: bool = False) -> list[str]:
    if reset:
        reset_demo_data(db)

    created_users: list[str] = []
    for user_data in DEMO_USERS:
        existing_user = db.query(models.User).filter(models.User.email == user_data["email"]).first()
        if existing_user:
            continue

        user = models.User(
            full_name=user_data["full_name"],
            email=user_data["email"],
            hashed_password=hash_secret(user_data["password"]),
            role=user_data["role"],
        )
        db.add(user)
        created_users.append(user.email)

    db.commit()
    return created_users

