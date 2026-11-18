from typing import Any, Literal

from pydantic import BaseModel, Field


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3)
    password: str = Field(min_length=8)
    display_name: str | None = None


class LoginRequest(BaseModel):
    email: str
    password: str


class AccessTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class RaceIn(BaseModel):
    distance: Literal["5k", "10k", "half_marathon", "marathon"]
    date: str


class ScheduleIn(BaseModel):
    run_days: list[str]
    long_run_day: str


class BaselineIn(BaseModel):
    weekly_km: float
    long_run_km: float


class PrIn(BaseModel):
    time: str
    date: str


class PlanCreateRequest(BaseModel):
    race: RaceIn
    schedule: ScheduleIn
    baseline: BaselineIn
    pr: PrIn | None = None


class ConnectRequest(BaseModel):
    provider: str
    email: str
    password: str


class ChallengeRequest(BaseModel):
    provider: str
    challenge_id: str
    code: str


class ProviderOut(BaseModel):
    provider: str
    status: str
    connected_at: str | None = None


class PlanOut(BaseModel):
    status: str
    race: dict[str, Any] | None = None
    schedule: dict[str, Any] | None = None
    snapshot: dict[str, Any] | None = None
    plan: dict[str, Any] | None = None
    error_message: str | None = None
    failed_at: str | None = None
    updated_at: str | None = None


class MeOut(BaseModel):
    id: int
    email: str
    display_name: str | None
    integrations: list[ProviderOut]
    plan_status: str | None
