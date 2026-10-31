import json
from datetime import date, timedelta

from whoneedsacoach.agent.state import CoachContext
from whoneedsacoach.planner.build import (
    DISTANCES,
    RACE_KM,
    build_plan,
    four_complete_weeks,
    normalize_day,
    parse_pace_time,
    plan_start,
    snapshot_from_runs,
)
from whoneedsacoach.planner.revise import apply_revision
from whoneedsacoach.utils.log import show


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
        plan["snapshot"] = snapshot
        show("snapshot passed to the model", snapshot)
    snapshot = plan["snapshot"]
    if snapshot.get("need_baseline") or snapshot.get("need_pr") or snapshot.get("pr") is None:
        plan["status"] = "intake"
        plan["plan"] = None
        ctx.repo.save_plan(plan)
        return json.dumps({"status": "intake", "snapshot": snapshot})
    if snapshot.get("baseline_weekly_km") is None:
        plan["status"] = "intake"
        plan["plan"] = None
        ctx.repo.save_plan(plan)
        return json.dumps({"status": "intake", "snapshot": snapshot})
    start = plan_start(date.today())
    plan["plan"] = build_plan(
        baseline_weekly_km=snapshot["baseline_weekly_km"],
        baseline_long_run_km=snapshot["baseline_long_run_km"],
        distance=plan["race"]["distance"],
        start=start,
        race_date=date.fromisoformat(plan["race"]["date"]),
        run_days=plan["schedule"]["run_days"],
        long_run_day=plan["schedule"]["long_run_day"],
        pr_time_seconds=snapshot["pr"]["time_seconds"],
    )
    plan["status"] = "review"
    plan["pending"] = None
    ctx.repo.save_plan(plan)
    payload = {"status": "review", "snapshot": snapshot, "plan": plan["plan"]}
    show("plan passed to the model", payload)
    return json.dumps(payload)


def accept(ctx: CoachContext) -> str:
    plan = _plan(ctx)
    plan["status"] = "active"
    ctx.repo.save_plan(plan)
    return json.dumps({"status": "active", "plan_start": plan["plan"]["plan_start"]})


def week_view(ctx: CoachContext, week_start: str) -> str:
    plan = _plan(ctx)
    for week in plan["plan"]["weeks"]:
        if week["week_start"] == week_start:
            return json.dumps(week)
    return _error(f"no week starting {week_start}")


def accept_pending(ctx: CoachContext) -> str:
    plan = _plan(ctx)
    plan["plan"] = apply_revision(plan["plan"], plan["pending"])
    plan["pending"] = None
    plan["status"] = "active"
    ctx.repo.save_plan(plan)
    return json.dumps({"status": "active"})


def reject_pending(ctx: CoachContext) -> str:
    plan = _plan(ctx)
    plan["pending"] = None
    plan["status"] = "active"
    ctx.repo.save_plan(plan)
    return json.dumps({"status": "active", "pending": None})
