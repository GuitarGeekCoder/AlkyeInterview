from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app import models, schemas
from app.cache import create_cache
from app.config import Settings, get_settings
from app.database import create_session_factory
from app.seed import seed_demo_users
from app.security import (
    create_access_token,
    decode_access_token,
    generate_login_code,
    hash_secret,
    verify_secret,
)


bearer_scheme = HTTPBearer(auto_error=False)


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or get_settings()
    session_factory = create_session_factory(app_settings.database_url)
    cache = create_cache(
        cache_backend=app_settings.cache_backend,
        default_ttl_seconds=app_settings.cache_ttl_seconds,
        redis_url=app_settings.redis_url,
        redis_key_prefix=app_settings.redis_key_prefix,
        redis_timeout_seconds=app_settings.redis_timeout_seconds,
    )

    app = FastAPI(title=app_settings.app_name)
    app.state.settings = app_settings
    app.state.SessionLocal = session_factory
    app.state.cache = cache

    def get_db(request: Request):
        db = request.app.state.SessionLocal()
        try:
            yield db
        finally:
            db.close()

    def get_current_user(
        request: Request,
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
        db: Session = Depends(get_db),
    ) -> models.User:
        if credentials is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
            )
        try:
            payload = decode_access_token(
                credentials.credentials,
                request.app.state.settings.secret_key,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=str(exc),
            ) from exc

        user = db.query(models.User).filter(models.User.id == payload["sub"]).first()
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found",
            )
        return user

    def require_admin(current_user: models.User = Depends(get_current_user)) -> models.User:
        if current_user.role != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorised",
            )
        return current_user

    @app.post("/seed/users", response_model=schemas.SeedUsersResponse)
    def seed_users(
        request: Request,
        reset: bool = Query(default=False),
        db: Session = Depends(get_db),
    ) -> schemas.SeedUsersResponse:
        created_users = seed_demo_users(db, reset=reset)
        request.app.state.cache.clear()
        return schemas.SeedUsersResponse(created_users=created_users)

    @app.post("/auth/login", response_model=schemas.LoginResponse)
    def login(
        payload: schemas.LoginRequest,
        request: Request,
        db: Session = Depends(get_db),
    ) -> schemas.LoginResponse:
        user = db.query(models.User).filter(models.User.email == payload.email.lower()).first()
        if user is None or not verify_secret(payload.password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials",
            )

        code = generate_login_code()
        challenge = models.LoginChallenge(
            user_id=user.id,
            hashed_code=hash_secret(code),
            expires_at=datetime.utcnow()
            + timedelta(seconds=request.app.state.settings.login_code_ttl_seconds),
            used=False,
        )
        email_log = models.EmailLog(
            to_email=user.email,
            subject="Your 2FA code",
            body=f"Your verification code is {code}",
            code=code,
        )
        db.add(challenge)
        db.add(email_log)
        db.commit()
        return schemas.LoginResponse(
            challenge_id=challenge.id,
            message="Two-factor verification required",
        )

    @app.get("/dev/email-logs/latest", response_model=schemas.EmailLogResponse)
    def latest_email_log(
        email: str | None = Query(default=None),
        db: Session = Depends(get_db),
    ) -> schemas.EmailLogResponse:
        query = db.query(models.EmailLog)
        if email:
            query = query.filter(models.EmailLog.to_email == email.lower())
        email_log = query.order_by(models.EmailLog.created_at.desc()).first()
        if email_log is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No email log found")
        return schemas.EmailLogResponse.model_validate(email_log, from_attributes=True)

    @app.post("/auth/verify-2fa", response_model=schemas.TokenResponse)
    def verify_2fa(
        payload: schemas.VerifyTwoFactorRequest,
        request: Request,
        db: Session = Depends(get_db),
    ) -> schemas.TokenResponse:
        challenge = (
            db.query(models.LoginChallenge)
            .filter(models.LoginChallenge.id == payload.challenge_id)
            .first()
        )
        if challenge is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Challenge not found")
        if challenge.used:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Code already used")
        if challenge.expires_at <= datetime.utcnow():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Code expired")
        if not verify_secret(payload.code, challenge.hashed_code):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid code")

        challenge.used = True
        user = db.query(models.User).filter(models.User.id == challenge.user_id).first()
        db.commit()
        token = create_access_token(
            secret_key=request.app.state.settings.secret_key,
            user_id=user.id,
            email=user.email,
            role=user.role,
            expires_minutes=request.app.state.settings.access_token_expire_minutes,
        )
        return schemas.TokenResponse(access_token=token)

    @app.post("/tasks", response_model=schemas.TaskResponse, status_code=status.HTTP_201_CREATED)
    def create_task(
        payload: schemas.TaskCreateRequest,
        admin_user: models.User = Depends(require_admin),
        db: Session = Depends(get_db),
    ) -> schemas.TaskResponse:
        task = models.Task(
            title=payload.title,
            description=payload.description,
            status=payload.status,
            priority=payload.priority,
            created_by_id=admin_user.id,
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        return schemas.TaskResponse(
            id=task.id,
            title=task.title,
            description=task.description,
            status=task.status,
            priority=task.priority,
            assigned_to=None,
        )

    @app.post("/tasks/assign", response_model=schemas.TaskAssignResponse)
    def assign_tasks(
        payload: schemas.TaskAssignRequest,
        request: Request,
        _: models.User = Depends(require_admin),
        db: Session = Depends(get_db),
    ) -> schemas.TaskAssignResponse:
        assignee = db.query(models.User).filter(models.User.email == payload.assignee_email.lower()).first()
        if assignee is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignee not found")
        if assignee.role != "staff":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Assignee must be staff")

        tasks = db.query(models.Task).filter(models.Task.id.in_(payload.task_ids)).all()
        if len(tasks) != len(payload.task_ids):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="One or more tasks not found")

        impacted_user_ids = {task.assigned_to_id for task in tasks if task.assigned_to_id}
        impacted_user_ids.add(assignee.id)
        for task in tasks:
            task.assigned_to_id = assignee.id

        db.commit()
        for user_id in impacted_user_ids:
            request.app.state.cache.delete(f"user_tasks:{user_id}")

        return schemas.TaskAssignResponse(
            assigned_task_ids=[task.id for task in tasks],
            assignee_email=assignee.email,
        )

    @app.get("/tasks/view-my-tasks", response_model=schemas.ViewMyTasksResponse)
    def view_my_tasks(
        request: Request,
        current_user: models.User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> schemas.ViewMyTasksResponse:
        cache_key = f"user_tasks:{current_user.id}"
        cached_value = request.app.state.cache.get(cache_key)
        if cached_value is not None:
            return schemas.ViewMyTasksResponse(
                **cached_value,
                cache=schemas.CacheMetadata(hit=True),
            )

        tasks = (
            db.query(models.Task)
            .filter(models.Task.assigned_to_id == current_user.id)
            .order_by(models.Task.created_at.asc())
            .all()
        )
        serialized_tasks = [
            schemas.TaskResponse(
                id=task.id,
                title=task.title,
                description=task.description,
                status=task.status,
                priority=task.priority,
                assigned_to=current_user.email,
            )
            for task in tasks
        ]
        response_payload = schemas.ViewMyTasksResponse(
            user=schemas.CurrentUserResponse(email=current_user.email, role=current_user.role),
            tasks=serialized_tasks,
            summary=schemas.TaskListSummary(total_assigned_tasks=len(serialized_tasks)),
            cache=schemas.CacheMetadata(hit=False),
        ).model_dump(mode="json")
        cached_payload = {key: value for key, value in response_payload.items() if key != "cache"}
        request.app.state.cache.set(cache_key, cached_payload)
        return schemas.ViewMyTasksResponse(**response_payload)

    @app.get("/health")
    def healthcheck(request: Request) -> dict[str, str]:
        return {
            "status": "ok",
            "cache_backend": request.app.state.cache.backend_name,
        }

    return app


app = create_app()
