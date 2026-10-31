"""Inputs and structured output for the training coach."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

RaceDistance = Literal["5k", "10k", "half", "marathon"]
Weekday = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DayRole = Literal["rest", "run", "long", "race"]
WorkoutKind = Literal["rest", "easy", "long", "tempo", "intervals", "race"]


class AthleteProfile(BaseModel):
    """Inputs for one training plan. A personal best is optional."""

    race_distance: RaceDistance
    race_date: date
    weekly_km: float = Field(description="Current weekly distance. 0 means not running now.")
    pb_distance: RaceDistance | None = None
    pb_time: str | None = Field(default=None, description="Personal best as MM:SS or H:MM:SS.")
    pb_date: date | None = None
    run_days: list[Weekday]
    long_run_day: Weekday


class DaySlot(BaseModel):
    """One date in the calendar skeleton. Python builds this, not the coach."""

    date: date
    weekday: Weekday
    role: DayRole


class Workout(BaseModel):
    """One training day. Rest days are omitted. Paces are min/km (M:SS) or an effort cue."""

    date: date
    kind: WorkoutKind
    distance_km: float
    # pace_low is the faster end. On a quality day these are the work pace, not the warmup.
    pace_low: str = ""
    pace_high: str = ""
    structure: str = Field(
        default="",
        description=(
            "Tempo or intervals only, one line: total km, warmup, work, rest, cooldown. "
            "Empty for easy, long, and race days."
        ),
    )


class TrainingPlan(BaseModel):
    """Coach output. Warnings are added later by the manager."""

    short_summary: str = Field(description="A few sentences on the goal and the shape of the plan.")
    workouts: list[Workout]
