import asyncio
from datetime import date, timedelta

from whoneedsacoach.models.llm import model
from whoneedsacoach.planner.build import monday_of
from whoneedsacoach.planner.revise import propose_next_week
from whoneedsacoach.planner.training import PROFILE, build_training_plan, write_plan
from whoneedsacoach.store.repo import Repo
from whoneedsacoach.tools.garmin import garmin_session
from whoneedsacoach.utils.config import DB_PATH, LOG_PATH
from whoneedsacoach.utils.log import note, show


async def generate() -> None:
    print(f"Plan progress is appended to {LOG_PATH}", flush=True)
    note(f"using model {model.model}")
    note(f"building training plan for {PROFILE.race_distance} on {PROFILE.race_date.isoformat()}")
    result = await build_training_plan(PROFILE)
    written = write_plan(PROFILE, result, date.today())
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
