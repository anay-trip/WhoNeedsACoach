import json
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import date, timedelta

from whoneedsacoach.agent.state import CoachContext
from whoneedsacoach.planner.build import (
    DISTANCES,
    RACE_KM,
    four_complete_weeks,
    normalize_day,
    parse_pace_time,
    snapshot_from_runs,
)
from whoneedsacoach.planner.revise import apply_revision
from whoneedsacoach.planner.schedule import reschedule_changed_week, schedule_current_week
from whoneedsacoach.tools.garmin import garmin_session
from whoneedsacoach.planner.training import (
    athlete_profile,
    build_training_plan,
    check_profile,
    plan_document,
    write_plan,
)
from whoneedsacoach.utils.log import note, show


def _plan(ctx: CoachContext) -> dict:
    return ctx.repo.get_plan(ctx.user_id)


def _error(message: str) -> str:
    return json.dumps({"error": message})


async def save_race(ctx: CoachContext, distance: str, race_date: str) -> str:
    if distance not in DISTANCES:
        return _error("distance must be 5k, 10k, half_marathon, or marathon")
    try:
        parsed = date.fromisoformat(race_date)
    except ValueError:
        return _error("date must be YYYY-MM-DD")
    start = plan_start(date.today())
    if parsed < start:
        return _error(f"race date is before the plan start {start.isoformat()}")
    plan = _plan(ctx)
    plan["race"] = {"distance": distance, "date": race_date}
    ctx.repo.save_plan(plan)
    return await finish(ctx, refetch_snapshot=True)


async def save_schedule(ctx: CoachContext, run_days: list[str], long_run_day: str) -> str:
    try:
        days = [normalize_day(day) for day in run_days]
        long_day = normalize_day(long_run_day)
    except ValueError as exc:
        return _error(str(exc))
    if long_day not in days:
        return _error("long run day must be one of the run days")
    plan = _plan(ctx)
    plan["schedule"] = {"run_days": days, "long_run_day": long_day}
    ctx.repo.save_plan(plan)
    return await finish(ctx, refetch_snapshot=True)


async def save_baseline(ctx: CoachContext, weekly_km: float, long_run_km: float) -> str:
    plan = _plan(ctx)
    snapshot = plan["snapshot"] or {}
    snapshot["baseline_weekly_km"] = weekly_km
    snapshot["baseline_long_run_km"] = long_run_km
    snapshot["need_baseline"] = False
    plan["snapshot"] = snapshot
    ctx.repo.save_plan(plan)
    return await finish(ctx, refetch_snapshot=False)


async def decline_pr(ctx: CoachContext) -> str:
    plan = _plan(ctx)
    snapshot = plan["snapshot"] or {}
    snapshot["pr"] = None
    snapshot["need_pr"] = False
    snapshot["pr_declined"] = True
    plan["snapshot"] = snapshot
    ctx.repo.save_plan(plan)
    return await finish(ctx, refetch_snapshot=False)


async def save_pr(ctx: CoachContext, time: str, pr_date: str) -> str:
    plan = _plan(ctx)
    if not plan["race"]:
        return _error("set the race first")
    try:
        seconds = parse_pace_time(time)
        date.fromisoformat(pr_date)
    except ValueError:
        return _error("time should look like 25:00 or 1:45:00, and date like YYYY-MM-DD")
    snapshot = plan["snapshot"] or {}
    snapshot["pr"] = {
        "time_seconds": seconds,
        "date": pr_date,
        "pace_sec_per_km": int(seconds / RACE_KM[plan["race"]["distance"]]),
    }
    snapshot["need_pr"] = False
    snapshot["pr_declined"] = False
    plan["snapshot"] = snapshot
    ctx.repo.save_plan(plan)
    return await finish(ctx, refetch_snapshot=False)


async def finish(ctx: CoachContext, refetch_snapshot: bool) -> str:
    plan = _plan(ctx)
    if not plan["race"] or not plan["schedule"]:
        return json.dumps({"status": plan["status"], "race": plan["race"], "schedule": plan["schedule"]})
    if refetch_snapshot or plan["snapshot"] is None:
        today = date.today()
        weeks = four_complete_weeks(today)
        note(
            "fetching Garmin runs and personal record "
            f"from {weeks[0].isoformat()} to {(weeks[-1] + timedelta(days=6)).isoformat()}"
        )
        runs = await ctx.garmin.runs_between(weeks[0], weeks[-1] + timedelta(days=6))
        record = await ctx.garmin.personal_record(plan["race"]["distance"])
        show(
            "garmin data used for the plan",
            {
                "window": {"start": weeks[0].isoformat(), "end": (weeks[-1] + timedelta(days=6)).isoformat()},
                "runs": runs,
                "personal_record": record,
            },
        )
        kept = plan["snapshot"] or {}
        snapshot = snapshot_from_runs(runs, today, record, plan["race"]["distance"])
        if kept.get("baseline_weekly_km") is not None and snapshot["need_baseline"]:
            snapshot["baseline_weekly_km"] = kept["baseline_weekly_km"]
            snapshot["baseline_long_run_km"] = kept["baseline_long_run_km"]
            snapshot["need_baseline"] = False
        if kept.get("pr") is not None and snapshot["need_pr"]:
            snapshot["pr"] = kept["pr"]
            snapshot["need_pr"] = False
        if kept.get("pr_declined") and kept.get("pr") is None:
            snapshot["pr"] = None
            snapshot["need_pr"] = False
            snapshot["pr_declined"] = True
        plan["snapshot"] = snapshot
        show("snapshot passed to the model", snapshot)
    snapshot = plan["snapshot"]
    waiting_for_baseline = snapshot.get("need_baseline") or snapshot.get("baseline_weekly_km") is None
    waiting_for_pr = snapshot.get("need_pr") and snapshot.get("pr") is None and not snapshot.get("pr_declined")
    if waiting_for_baseline or waiting_for_pr:
        missing = []
        if waiting_for_baseline:
            missing.append("weekly kilometres")
        if waiting_for_pr:
            missing.append("a personal best or a decline")
        note("plan waiting on " + " and ".join(missing))
        plan["status"] = "intake"
        plan["plan"] = None
        ctx.repo.save_plan(plan)
        return json.dumps({"status": "intake", "snapshot": snapshot})
    today = date.today()
    try:
        profile = athlete_profile(plan["race"], plan["schedule"], snapshot)
    except (KeyError, ValueError) as exc:
        return _error(str(exc))
    failed = check_profile(profile, today)
    if failed:
        note(f"plan stopped: {failed['error']}")
        return json.dumps(failed)
    note(f"building training plan for {profile.race_distance} on {profile.race_date.isoformat()}")
    result = await build_training_plan(profile, today)
    plan["plan"] = plan_document(result, today)
    written = write_plan(profile, result, today)
    plan["status"] = "review"
    plan["pending"] = None
    ctx.repo.save_plan(plan)
    payload = {
        "status": "review",
        "snapshot": snapshot,
        "plan": plan["plan"],
        "markdown_path": str(written),
    }
    show("plan written", str(written))
    show("plan passed to the model", payload)
    return json.dumps(payload)


async def accept_plan(ctx: CoachContext, today: date | None = None) -> str:
    today = today or date.today()
    plan = _plan(ctx)
    if not plan.get("plan"):
        return _error("there is no plan to accept")
    try:
        async with open_garmin(ctx) as garmin:
            await schedule_current_week(garmin, plan["plan"], today)
    except Exception as exc:
        ctx.repo.save_plan(plan)
        return _error(str(exc))
    plan["status"] = "active"
    ctx.repo.save_plan(plan)
    return json.dumps({"status": "active", "plan_start": plan["plan"]["plan_start"]})


def week_view(ctx: CoachContext, week_start: str) -> str:
    plan = _plan(ctx)
    for week in plan["plan"]["weeks"]:
        if week["week_start"] == week_start:
            return json.dumps(week)
    return _error(f"no week starting {week_start}")


async def accept_pending(ctx: CoachContext, today: date | None = None) -> str:
    today = today or date.today()
    plan = _plan(ctx)
    if not plan.get("pending"):
        return _error("there is no revision to accept")
    week_start = plan["pending"]["week"]["week_start"]
    old_week = deepcopy(next(week for week in plan["plan"]["weeks"] if week["week_start"] == week_start))
    plan["plan"] = apply_revision(plan["plan"], plan["pending"])
    try:
        async with open_garmin(ctx) as garmin:
            await reschedule_changed_week(garmin, plan["plan"], old_week, today)
    except Exception as exc:
        ctx.repo.save_plan(plan)
        return _error(str(exc))
    plan["pending"] = None
    plan["status"] = "active"
    ctx.repo.save_plan(plan)
    return json.dumps({"status": "active"})


async def reject_pending(ctx: CoachContext, today: date | None = None) -> str:
    today = today or date.today()
    plan = _plan(ctx)
    try:
        async with open_garmin(ctx) as garmin:
            await schedule_current_week(garmin, plan["plan"], today)
    except Exception as exc:
        ctx.repo.save_plan(plan)
        return _error(str(exc))
    plan["pending"] = None
    plan["status"] = "active"
    ctx.repo.save_plan(plan)
    return json.dumps({"status": "active", "pending": None})


@asynccontextmanager
async def open_garmin(ctx: CoachContext):
    user = ctx.repo.get_user(ctx.user_id)
    if user is None or not user.get("garmin_token_dir"):
        raise RuntimeError("log in to Garmin before scheduling")
    if ctx.garmin is not None:
        yield ctx.garmin
        return
    async with garmin_session(user["garmin_token_dir"]) as garmin:
        yield garmin
