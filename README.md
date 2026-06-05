# FastAPI Developer Assignment

This repository implements the required backend workflow from `Python Developer Assignment.pdf` using FastAPI, SQLAlchemy, SQLite, JWT-style bearer tokens, email-based 2FA, and Redis-backed task caching with a documented in-memory fallback for local development.

## Tech choices

- FastAPI for the HTTP API
- SQLAlchemy ORM with SQLite for local development
- Custom HS256 token signing for JWT-compatible bearer tokens
- PBKDF2 password/code hashing using the Python standard library
- Redis for `/tasks/view-my-tasks` caching
- Pytest for workflow validation

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

To use Redis caching locally, start Redis and set `REDIS_URL` if you are not using the default `redis://localhost:6379/0`.

Optional cache-related environment variables:

- `CACHE_BACKEND=auto|redis|memory` (`auto` tries Redis first and falls back to memory)
- `REDIS_URL=redis://localhost:6379/0`
- `REDIS_KEY_PREFIX=fastapi_assignment:`
- `REDIS_TIMEOUT_SECONDS=0.25`

## Run the API

```bash
uvicorn app.main:app --reload
```

The app uses `sqlite:///./app.db` by default. You can override it with `DATABASE_URL`.

## Seed demo users

Preferred repeatable local setup:

```bash
python scripts/seed_demo.py --reset
```

This creates:

- `admin@example.com` / `Password123!` / `admin`
- `jamesbond@example.com` / `Password123!` / `staff`

There is also a local seed endpoint:

```bash
POST /seed/users?reset=true
```

## Required API routes

- `POST /seed/users`
- `POST /auth/login`
- `GET /dev/email-logs/latest`
- `POST /auth/verify-2fa`
- `POST /tasks`
- `POST /tasks/assign`
- `GET /tasks/view-my-tasks`

## Validation workflow

1. Seed users with `python scripts/seed_demo.py --reset` or `POST /seed/users?reset=true`.
2. Login as admin with `POST /auth/login`.
3. Read the latest admin 2FA code from `GET /dev/email-logs/latest?email=admin@example.com`.
4. Exchange the code at `POST /auth/verify-2fa` to receive a bearer token.
5. Create exactly five tasks using `POST /tasks`.
6. Assign exactly three tasks to James Bond using `POST /tasks/assign`.
7. Repeat the login + 2FA flow for `jamesbond@example.com`.
8. Attempting `POST /tasks` as James Bond returns `403`.
9. Call `GET /tasks/view-my-tasks` and confirm exactly three tasks are returned.
10. Call the same endpoint again and confirm `cache.hit` changes from `false` to `true`.

## Example final response

```json
{
  "user": {
    "email": "jamesbond@example.com",
    "role": "staff"
  },
  "tasks": [
    {
      "id": "8cb6557a-4cab-4745-8dbc-d581a2d4ac93",
      "title": "Task 1",
      "description": "Description 1",
      "status": "todo",
      "priority": "high",
      "assigned_to": "jamesbond@example.com"
    },
    {
      "id": "06bb56e2-e8ca-46cb-b509-c5f8af81f83e",
      "title": "Task 2",
      "description": "Description 2",
      "status": "todo",
      "priority": "medium",
      "assigned_to": "jamesbond@example.com"
    },
    {
      "id": "d53750a1-2cad-4d29-9f7d-c63828ee4c62",
      "title": "Task 3",
      "description": "Description 3",
      "status": "todo",
      "priority": "low",
      "assigned_to": "jamesbond@example.com"
    }
  ],
  "summary": {
    "total_assigned_tasks": 3
  },
  "cache": {
    "hit": false
  }
}
```

## Test suite

```bash
pytest
```

The tests cover:

- User seeding
- Login starting 2FA without returning a token immediately
- Incorrect, expired, and reused 2FA code rejection
- Admin-only task creation
- Admin task assignment to James Bond
- Staff forbidden from creating tasks
- James Bond viewing assigned tasks
- Cache miss on first read and hit on second read
- Cache invalidation after reassignment

## Limitations documented for local development

- SQLite is used instead of PostgreSQL for a simpler local setup.
- `CACHE_BACKEND=auto` falls back to process-local in-memory caching when Redis is unavailable, which means cache state is not shared across multiple API workers.
- `/dev/email-logs/latest` is intentionally development-only and exposes the latest one-time code for validation.
- Schema creation is automatic at application startup instead of being driven by migrations.
