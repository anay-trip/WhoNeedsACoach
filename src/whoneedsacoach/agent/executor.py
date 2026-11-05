import asyncio
from datetime import date, timedelta
from pathlib import Path

from whoneedsacoach.models.llm import model
from whoneedsacoach.models.training import AthleteProfile
from whoneedsacoach.planner.build import complete_week_totals, four_complete_weeks, median_weekly_km, monday_of
from whoneedsacoach.planner.revise import propose_next_week
from whoneedsacoach.planner.schedule import (
    ensure_week_totals,
    schedule_current_week,
    sync_completed,
    week_actuals,
)
from whoneedsacoach.planner.training import PROFILE, TrainingResult, build_training_plan, plan_document, write_plan
from whoneedsacoach.store.repo import Repo
from whoneedsacoach.tools.garmin import garmin_session
from whoneedsacoach.utils.config import ANAY_NAME, DB_PATH, LOG_PATH
from whoneedsacoach.utils.log import note, show

# The same directory garmin-mcp uses when no per-user path has been saved yet.
DEFAULT_TOKENS = Path.home() / ".garminconnect"
RACE_STORED = {"half": "half_marathon"}


async def generate() -> None:
    print(f"Plan progress is appended to {LOG_PATH}", flush=True)
    today = date.today()
    repo = Repo(DB_PATH)
    token_dir = str(DEFAULT_TOKENS) if DEFAULT_TOKENS.exists() else None
    user = repo.get_or_create_user(ANAY_NAME, token_dir)
    note(f"using model {model.model}")
    weeks = four_complete_weeks(today)
    note(f"fetching Garmin runs from {weeks[0].isoformat()} to {(weeks[-1] + timedelta(days=6)).isoformat()}")
    async with garmin_session(user["garmin_token_dir"]) as garmin:
        runs = await garmin.runs_between(weeks[0], weeks[-1] + timedelta(days=6))
        totals = complete_week_totals(runs, today)
        weekly_km = median_weekly_km(runs, today)
        profile = PROFILE.model_copy(update={"weekly_km": weekly_km})
        volumes = ", ".join(f"{week['distance_km']:g}" for week in totals)
        note(f"last 4 weeks: {volumes} km; median {weekly_km:g} km")
        note(
            f"building training plan for {profile.race_distance} on {profile.race_date.isoformat()} "
            f"at {weekly_km:g} km/week"
        )
        result = await build_training_plan(profile)
        written = write_plan(profile, result, today)
        await store_and_schedule(repo, user, profile, result, garmin, today)
    show("plan written", str(written))
    print(result.plan.short_summary, flush=True)


async def store_and_schedule(repo, user, profile: AthleteProfile, result: TrainingResult, garmin, today: date) -> dict:
    """Save the target plan and place this week's remaining sessions on Garmin."""
    document = plan_document(result, today)
    plan = repo.get_plan(user["id"])
    if plan is None:
        plan = repo.create_plan(user["id"])
    plan["race"] = {
        "distance": RACE_STORED.get(profile.race_distance, profile.race_distance),
        "date": profile.race_date.isoformat(),
    }
    plan["schedule"] = {"run_days": list(profile.run_days), "long_run_day": profile.long_run_day}
    plan["plan"] = document
    plan["pending"] = None
    note("scheduling this week's remaining sessions on Garmin")
    try:
        await schedule_current_week(garmin, document, today)
        plan["status"] = "active"
    except Exception as exc:
        plan["status"] = "review"
        repo.save_plan(plan)
        raise
    repo.save_plan(plan)
    scheduled = [
        session
        for week in document["weeks"]
        for session in week["sessions"]
        if session.get("workout_id")
    ]
    show("scheduled on Garmin", scheduled)
    return plan


def run_plan() -> None:
    asyncio.run(generate())


async def checkin() -> None:
    repo = Repo(DB_PATH)
    reviewed = monday_of(date.today()) - timedelta(days=7)
    reviewed_key = reviewed.isoformat()
    pairs = repo.plans_with_status("active")
    if not pairs:
        print("no active plans")
        return
    for user, plan in pairs:
        document = plan["plan"] or {}
        ensure_week_totals(document)
        weeks = document.get("weeks", [])
        index = next((i for i, week in enumerate(weeks) if week["week_start"] == reviewed_key), None)
        if index is None or index + 1 >= len(weeks):
            print(f"{user['name']}: no week to revise")
            continue
        if not user.get("garmin_token_dir"):
            print(f"{user['name']}: log in to Garmin before check-in")
            continue
        note(f"{user['name']}: reading completed Garmin workouts for the week of {reviewed_key}")
        async with garmin_session(user["garmin_token_dir"]) as garmin:
            await sync_completed(garmin, repo, user["id"], plan, date.today())
        reviewed_week = weeks[index]
        rows = repo.activities_between(user["id"], reviewed, reviewed + timedelta(days=6))
        actual, actual_long = week_actuals(rows, reviewed_week)
        show(f"garmin data for {user['name']} week {reviewed_key}", rows)
        pending = propose_next_week(plan["plan"], reviewed_key, actual, actual_long, rows)
        plan["pending"] = pending
        plan["status"] = "review_revision"
        repo.save_plan(plan)
        label = "changed" if pending["changed"] else "unchanged"
        print(f"{user['name']}: {pending['week']['week_start']} {label}")


def run_checkin() -> None:
    asyncio.run(checkin())
