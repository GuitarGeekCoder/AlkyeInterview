from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class SeedUsersResponse(BaseModel):
    created_users: list[str]


class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    challenge_id: str
    message: str


class VerifyTwoFactorRequest(BaseModel):
    challenge_id: str
    code: str = Field(min_length=6, max_length=6)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class EmailLogResponse(BaseModel):
    to_email: str
    subject: str
    body: str
    code: str
    created_at: datetime


class TaskCreateRequest(BaseModel):
    title: str
    description: str = ""
    status: str = "todo"
    priority: str = "medium"


class TaskResponse(BaseModel):
    id: str
    title: str
    description: str
    status: str
    priority: str
    assigned_to: str | None


class TaskAssignRequest(BaseModel):
    task_ids: list[str]
    assignee_email: str


class TaskAssignResponse(BaseModel):
    assigned_task_ids: list[str]
    assignee_email: str


class CurrentUserResponse(BaseModel):
    email: str
    role: str


class TaskListSummary(BaseModel):
    total_assigned_tasks: int


class CacheMetadata(BaseModel):
    hit: bool


class ViewMyTasksResponse(BaseModel):
    user: CurrentUserResponse
    tasks: list[TaskResponse]
    summary: TaskListSummary
    cache: CacheMetadata


class ErrorResponse(BaseModel):
    detail: str | dict[str, Any]

