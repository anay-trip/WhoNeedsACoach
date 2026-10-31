import asyncio
from datetime import date, timedelta

from whoneedsacoach.models.llm import model
from whoneedsacoach.planner.build import complete_week_totals, four_complete_weeks, median_weekly_km, monday_of
from whoneedsacoach.planner.revise import propose_next_week
from whoneedsacoach.planner.training import PROFILE, build_training_plan, write_plan
from whoneedsacoach.store.repo import Repo
from whoneedsacoach.tools.garmin import garmin_session
from whoneedsacoach.utils.config import DB_PATH, LOG_PATH
from whoneedsacoach.utils.log import note, show


async def generate() -> None:
    print(f"Plan progress is appended to {LOG_PATH}", flush=True)
    today = date.today()
    note(f"using model {model.model}")
    weeks = four_complete_weeks(today)
    note(f"fetching Garmin runs from {weeks[0].isoformat()} to {(weeks[-1] + timedelta(days=6)).isoformat()}")
    async with garmin_session(None) as garmin:
        runs = await garmin.runs_between(weeks[0], weeks[-1] + timedelta(days=6))
    totals = complete_week_totals(runs, today)
    weekly_km = median_weekly_km(runs, today)
    profile = PROFILE.model_copy(update={"weekly_km": weekly_km})
    volumes = ", ".join(f"{week['distance_km']:g}" for week in totals)
    note(f"last 4 weeks: {volumes} km; median {weekly_km:g} km")
    note(f"building training plan for {profile.race_distance} on {profile.race_date.isoformat()} at {weekly_km:g} km/week")
    result = await build_training_plan(profile)
    written = write_plan(profile, result, today)
    show("plan written", str(written))
    print(result.plan.short_summary, flush=True)


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
        weeks = (plan["plan"] or {}).get("weeks", [])
        if weeks and "target_distance_km" not in weeks[0]:
            print(f"{user['name']}: weekly revision waits until Garmin actuals are wired")
            continue
        index = next((i for i, week in enumerate(weeks) if week["week_start"] == reviewed_key), None)
        if index is None or index + 1 >= len(weeks):
            print(f"{user['name']}: no week to revise")
            continue
        note(f"{user['name']}: fetching Garmin runs for the week of {reviewed_key}")
        async with garmin_session(user["garmin_token_dir"]) as garmin:
            runs = await garmin.runs_between(reviewed, reviewed + timedelta(days=6))
        show(f"garmin data for {user['name']} week {reviewed_key}", runs)
        actual = sum(run["distance_km"] for run in runs)
        actual_long = max((run["distance_km"] for run in runs), default=0)
        pending = propose_next_week(plan["plan"], reviewed_key, actual, actual_long, runs)
        plan["pending"] = pending
        plan["status"] = "review_revision"
        repo.save_plan(plan)
        label = "changed" if pending["changed"] else "unchanged"
        print(f"{user['name']}: {pending['week']['week_start']} {label}")


def run_checkin() -> None:
    asyncio.run(checkin())
