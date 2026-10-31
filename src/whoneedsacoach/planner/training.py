"""Ask the coach for a plan, check it once, and shape it for the saved record."""

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from agents import Runner, trace

from whoneedsacoach.agent.training_coach import training_coach
from whoneedsacoach.models.training import AthleteProfile, DaySlot, TrainingPlan, Workout
from whoneedsacoach.planner.guardrails import (
    build_slots,
    check_plan,
    standing_warnings,
    validate_profile,
)
from whoneedsacoach.prompts.training import training_user_prompt
from whoneedsacoach.utils.config import ROOT
from whoneedsacoach.utils.log import note

PLANS_DIR = ROOT / "plans"

COACH_DISTANCE = {
    "5k": "5k",
    "10k": "10k",
    "half": "half",
    "half_marathon": "half",
    "marathon": "marathon",
}

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

# Fixed until the chat collects these. Weekly kilometres and the 10k best match the training sample.
PROFILE = AthleteProfile(
    race_distance="half",
    race_date=date(2027, 1, 29),
    weekly_km=20,
    pb_distance="10k",
    pb_time="49:04",
    pb_date=date(2026, 6, 1),
    run_days=["wed", "fri", "sun"],
    long_run_day="sun",
)


@dataclass
class TrainingResult:
    plan: TrainingPlan
    warnings: list[str]


def format_pb_time(seconds: int) -> str:
    """Seconds as MM:SS or H:MM:SS."""
    hours, rem = divmod(int(seconds), 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def athlete_profile(race: dict, schedule: dict, snapshot: dict) -> AthleteProfile:
    """Profile fields only. Weekly kilometres and an optional best. No Garmin run list."""
    distance = COACH_DISTANCE[race["distance"]]
    pr = snapshot.get("pr")
    pb_distance = None
    pb_time = None
    pb_date = None
    if pr:
        pb_distance = distance
        pb_time = format_pb_time(pr["time_seconds"])
        if pr.get("date"):
            pb_date = date.fromisoformat(pr["date"])
    return AthleteProfile(
        race_distance=distance,
        race_date=date.fromisoformat(race["date"]),
        weekly_km=float(snapshot["baseline_weekly_km"]),
        pb_distance=pb_distance,
        pb_time=pb_time,
        pb_date=pb_date,
        run_days=list(schedule["run_days"]),
        long_run_day=schedule["long_run_day"],
    )


def check_profile(profile: AthleteProfile, today: date) -> dict | None:
    """None when the profile can start a plan. Otherwise an error payload."""
    try:
        validate_profile(profile, today)
    except ValueError as exc:
        return {"error": str(exc)}
    return None


def plan_document(result: TrainingResult, today: date) -> dict:
    """Group workouts into Monday weeks for the chat tools."""
    buckets: dict[date, list[Workout]] = {}
    for workout in result.plan.workouts:
        monday = workout.date - timedelta(days=workout.date.weekday())
        buckets.setdefault(monday, []).append(workout)
    weeks = []
    for monday in sorted(buckets):
        sessions = []
        for workout in sorted(buckets[monday], key=lambda item: item.date):
            sessions.append(
                {
                    "date": workout.date.isoformat(),
                    "weekday": WEEKDAYS[workout.date.weekday()],
                    "type": workout.kind,
                    "distance_km": workout.distance_km,
                    "pace_low": workout.pace_low,
                    "pace_high": workout.pace_high,
                    "structure": workout.structure,
                }
            )
        weeks.append({"week_start": monday.isoformat(), "sessions": sessions})
    return {
        "plan_start": today.isoformat(),
        "short_summary": result.plan.short_summary,
        "warnings": result.warnings,
        "weeks": weeks,
    }


def plan_markdown(slots: list[DaySlot], plan: TrainingPlan, warnings: list[str]) -> str:
    """One compact line per training day. A week of only rest days is left out."""
    by_date = {workout.date: workout for workout in plan.workouts}
    lines: list[str] = []
    if warnings:
        lines.extend(["## Warnings", ""])
        lines.extend(f"- {warning}" for warning in warnings)
        lines.append("")
    lines.extend([plan.short_summary.strip(), ""])
    week_rows: list[str] = []
    week_header = ""
    for slot in slots:
        monday = slot.date - timedelta(days=slot.date.weekday())
        header = f"## Week of {monday.strftime('%d %b %Y')}"
        if header != week_header:
            if week_rows:
                lines.extend([week_header, "", *week_rows, ""])
            week_header = header
            week_rows = []
        row = _row(slot, by_date.get(slot.date))
        if row:
            week_rows.append(row)
    if week_rows:
        lines.extend([week_header, "", *week_rows, ""])
    return "\n".join(lines).rstrip() + "\n"


def write_plan(
    profile: AthleteProfile,
    result: TrainingResult,
    today: date,
    directory: Path | None = None,
) -> Path:
    """Write the readable plan next to the app, as training/output does."""
    out = directory or PLANS_DIR
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{profile.race_distance}-{profile.race_date.isoformat()}.md"
    slots = build_slots(profile, today)
    path.write_text(plan_markdown(slots, result.plan, result.warnings), encoding="utf-8")
    return path


def _row(slot: DaySlot, workout: Workout | None) -> str | None:
    """None for a rest day. Quality days print structure; other days print distance and pace."""
    if slot.role == "rest" or (workout is not None and workout.kind == "rest"):
        return None
    if workout is None:
        return f"- {slot.date.isoformat()} {slot.weekday}: missing"
    if workout.kind in {"tempo", "intervals"} and workout.structure.strip():
        detail = f"{workout.kind}, {workout.structure.strip()}"
    else:
        detail = f"{workout.kind}, {_km(workout.distance_km)} km, {_pace(workout.pace_low, workout.pace_high)}"
    return f"- {slot.date.isoformat()} {slot.weekday}: {detail}"


def _pace(low: str, high: str) -> str:
    low, high = low.strip(), high.strip()
    if not low and not high:
        return "no pace"
    if low.lower() in {"walk/run", "easy"}:
        return low
    if low == high:
        return f"{low}/km"
    return f"{low}–{high}/km"


def _km(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return f"{value:g}"


async def build_training_plan(profile: AthleteProfile, today: date | None = None) -> TrainingResult:
    """Return a plan. A second guardrail miss is a warning, not an exception."""
    today = today or date.today()
    validate_profile(profile, today)
    slots = build_slots(profile, today)
    warnings = standing_warnings(profile)

    to_fill = sum(1 for slot in slots if slot.role != "rest")
    note(f"training coach: {to_fill} days to fill, asking for the draft")
    with trace("training plan"):
        draft = await _ask(profile, slots, today)
        note(f"training coach: draft returned, {len(draft.workouts)} workouts, checking it")
        failures = check_plan(draft, profile, slots, today)
        plan = draft
        if failures:
            note(f"training coach: {len(failures)} checks failed, asking for one revision")
            plan = await _ask(profile, slots, today, failures, draft)
            note(f"training coach: revision returned, {len(plan.workouts)} workouts, checking it")
            failures = check_plan(plan, profile, slots, today)
            if failures:
                note(f"training coach: {len(failures)} checks still failing; keeping the revision")
            else:
                note("training coach: revision passed the checks")
        else:
            note("training coach: draft passed the checks")
        warnings = warnings + failures

    return TrainingResult(plan=plan, warnings=warnings)


async def _ask(
    profile: AthleteProfile,
    slots,
    today: date,
    failures: list[str] | None = None,
    previous: TrainingPlan | None = None,
) -> TrainingPlan:
    prompt = training_user_prompt(profile, slots, today, failures, previous)
    result = await Runner.run(training_coach, prompt)
    return result.final_output
