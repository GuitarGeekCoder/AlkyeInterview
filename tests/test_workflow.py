from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.cache import InMemoryCache, create_cache
from app import models
from app.config import Settings
from app.main import create_app


@pytest.fixture()
def client(tmp_path):
    database_path = tmp_path / "test.db"
    settings = Settings(
        database_url=f"sqlite:///{database_path}",
        secret_key="test-secret",
        access_token_expire_minutes=60,
        login_code_ttl_seconds=300,
        cache_ttl_seconds=300,
        cache_backend="memory",
    )
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client


def seed_users(client: TestClient) -> None:
    response = client.post("/seed/users?reset=true")
    assert response.status_code == 200


def login_and_verify(client: TestClient, email: str, password: str) -> str:
    login_response = client.post(
        "/auth/login",
        json={"email": email, "password": password},
    )
    assert login_response.status_code == 200
    challenge_id = login_response.json()["challenge_id"]

    email_response = client.get("/dev/email-logs/latest", params={"email": email})
    assert email_response.status_code == 200
    code = email_response.json()["code"]

    verify_response = client.post(
        "/auth/verify-2fa",
        json={"challenge_id": challenge_id, "code": code},
    )
    assert verify_response.status_code == 200
    return verify_response.json()["access_token"]


def create_tasks(client: TestClient, token: str, count: int = 5) -> list[str]:
    task_ids: list[str] = []
    priorities = ["high", "medium", "low", "urgent", "medium"]
    for index in range(count):
        response = client.post(
            "/tasks",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "title": f"Task {index + 1}",
                "description": f"Description {index + 1}",
                "priority": priorities[index % len(priorities)],
            },
        )
        assert response.status_code == 201
        task_ids.append(response.json()["id"])
    return task_ids


def test_full_assignment_workflow_and_cache(client: TestClient) -> None:
    seed_users(client)

    admin_token = login_and_verify(client, "admin@example.com", "Password123!")
    task_ids = create_tasks(client, admin_token, count=5)

    assign_response = client.post(
        "/tasks/assign",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "task_ids": task_ids[:3],
            "assignee_email": "jamesbond@example.com",
        },
    )
    assert assign_response.status_code == 200
    assert len(assign_response.json()["assigned_task_ids"]) == 3

    james_token = login_and_verify(client, "jamesbond@example.com", "Password123!")

    forbidden_response = client.post(
        "/tasks",
        headers={"Authorization": f"Bearer {james_token}"},
        json={"title": "Unauthorized Task", "description": "Should fail"},
    )
    assert forbidden_response.status_code == 403

    first_view = client.get(
        "/tasks/view-my-tasks",
        headers={"Authorization": f"Bearer {james_token}"},
    )
    assert first_view.status_code == 200
    first_payload = first_view.json()
    assert first_payload["user"] == {
        "email": "jamesbond@example.com",
        "role": "staff",
    }
    assert len(first_payload["tasks"]) == 3
    assert first_payload["summary"]["total_assigned_tasks"] == 3
    assert first_payload["cache"]["hit"] is False

    second_view = client.get(
        "/tasks/view-my-tasks",
        headers={"Authorization": f"Bearer {james_token}"},
    )
    assert second_view.status_code == 200
    second_payload = second_view.json()
    assert len(second_payload["tasks"]) == 3
    assert second_payload["cache"]["hit"] is True
    assert [task["id"] for task in second_payload["tasks"]] == [
        task["id"] for task in first_payload["tasks"]
    ]


def test_2fa_rejects_invalid_expired_and_reused_codes(client: TestClient) -> None:
    seed_users(client)

    login_response = client.post(
        "/auth/login",
        json={"email": "admin@example.com", "password": "Password123!"},
    )
    assert login_response.status_code == 200
    challenge_id = login_response.json()["challenge_id"]

    wrong_code_response = client.post(
        "/auth/verify-2fa",
        json={"challenge_id": challenge_id, "code": "000000"},
    )
    assert wrong_code_response.status_code == 400

    email_response = client.get("/dev/email-logs/latest", params={"email": "admin@example.com"})
    code = email_response.json()["code"]

    verify_response = client.post(
        "/auth/verify-2fa",
        json={"challenge_id": challenge_id, "code": code},
    )
    assert verify_response.status_code == 200

    reused_response = client.post(
        "/auth/verify-2fa",
        json={"challenge_id": challenge_id, "code": code},
    )
    assert reused_response.status_code == 400

    expired_login_response = client.post(
        "/auth/login",
        json={"email": "admin@example.com", "password": "Password123!"},
    )
    expired_challenge_id = expired_login_response.json()["challenge_id"]
    session = client.app.state.SessionLocal()
    try:
        challenge = (
            session.query(models.LoginChallenge)
            .filter(models.LoginChallenge.id == expired_challenge_id)
            .first()
        )
        challenge.expires_at = datetime.utcnow() - timedelta(minutes=10)
        session.commit()
    finally:
        session.close()

    latest_code_response = client.get(
        "/dev/email-logs/latest",
        params={"email": "admin@example.com"},
    )
    expired_code = latest_code_response.json()["code"]

    expired_response = client.post(
        "/auth/verify-2fa",
        json={"challenge_id": expired_challenge_id, "code": expired_code},
    )
    assert expired_response.status_code == 400


def test_assignment_invalidates_cached_task_list(client: TestClient) -> None:
    seed_users(client)

    admin_token = login_and_verify(client, "admin@example.com", "Password123!")
    james_token = login_and_verify(client, "jamesbond@example.com", "Password123!")
    task_ids = create_tasks(client, admin_token, count=5)

    initial_assign = client.post(
        "/tasks/assign",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "task_ids": task_ids[:3],
            "assignee_email": "jamesbond@example.com",
        },
    )
    assert initial_assign.status_code == 200

    first_view = client.get(
        "/tasks/view-my-tasks",
        headers={"Authorization": f"Bearer {james_token}"},
    )
    assert first_view.json()["cache"]["hit"] is False

    second_view = client.get(
        "/tasks/view-my-tasks",
        headers={"Authorization": f"Bearer {james_token}"},
    )
    assert second_view.json()["cache"]["hit"] is True

    reassignment = client.post(
        "/tasks/assign",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "task_ids": [task_ids[3]],
            "assignee_email": "jamesbond@example.com",
        },
    )
    assert reassignment.status_code == 200

    refreshed_view = client.get(
        "/tasks/view-my-tasks",
        headers={"Authorization": f"Bearer {james_token}"},
    )
    refreshed_payload = refreshed_view.json()
    assert refreshed_payload["cache"]["hit"] is False
    assert refreshed_payload["summary"]["total_assigned_tasks"] == 4


def test_auto_cache_backend_falls_back_to_memory_without_redis(monkeypatch) -> None:
    import app.cache as cache_module

    monkeypatch.setattr(cache_module, "redis", None)

    cache = create_cache(
        cache_backend="auto",
        default_ttl_seconds=300,
        redis_url="redis://localhost:6379/0",
        redis_key_prefix="test:",
        redis_timeout_seconds=0.25,
    )

    assert isinstance(cache, InMemoryCache)
    assert cache.backend_name == "memory"
