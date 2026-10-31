from agents import RunContextWrapper, function_tool

from whoneedsacoach.agent.flow import (
    accept,
    accept_pending,
    decline_pr as mark_no_pr,
    reject_pending,
    save_baseline,
    save_pr,
    save_race,
    save_schedule,
    week_view,
)
from whoneedsacoach.agent.state import TOOLS, CoachContext


@function_tool
async def set_race(ctx: RunContextWrapper[CoachContext], distance: str, date: str) -> str:
    """Save the race distance and date. Distance is 5k, 10k, half_marathon, or marathon. Date is YYYY-MM-DD."""
    return await save_race(ctx.context, distance, date)


@function_tool
async def set_schedule(ctx: RunContextWrapper[CoachContext], run_days: list[str], long_run_day: str) -> str:
    """Save the weekdays the user will run, and which of those days is the long run."""
    return await save_schedule(ctx.context, run_days, long_run_day)


@function_tool
async def set_baseline(ctx: RunContextWrapper[CoachContext], weekly_km: float, long_run_km: float) -> str:
    """Save a weekly distance and recent long run when Garmin has no recent runs."""
    return await save_baseline(ctx.context, weekly_km, long_run_km)


@function_tool
async def set_pr(ctx: RunContextWrapper[CoachContext], time: str, date: str) -> str:
    """Save a best time (MM:SS or H:MM:SS) and the date of that effort when Garmin has no personal record."""
    return await save_pr(ctx.context, time, date)


@function_tool
async def decline_pr(ctx: RunContextWrapper[CoachContext]) -> str:
    """Continue without a personal best when the user has none."""
    return await mark_no_pr(ctx.context)


@function_tool
async def accept_plan(ctx: RunContextWrapper[CoachContext]) -> str:
    """Mark the proposed plan as the user's plan."""
    return accept(ctx.context)


@function_tool
async def show_week(ctx: RunContextWrapper[CoachContext], week_start: str) -> str:
    """Return one saved week. week_start is the Monday, YYYY-MM-DD."""
    return week_view(ctx.context, week_start)


@function_tool
async def accept_revision(ctx: RunContextWrapper[CoachContext]) -> str:
    """Apply the Monday proposal to the upcoming week."""
    return accept_pending(ctx.context)


@function_tool
async def reject_revision(ctx: RunContextWrapper[CoachContext]) -> str:
    """Drop the Monday proposal and keep the saved plan."""
    return reject_pending(ctx.context)


ALL_TOOLS = {
    "set_race": set_race,
    "set_schedule": set_schedule,
    "set_baseline": set_baseline,
    "set_pr": set_pr,
    "decline_pr": decline_pr,
    "accept_plan": accept_plan,
    "show_week": show_week,
    "accept_revision": accept_revision,
    "reject_revision": reject_revision,
}


def tools_for(status: str) -> list:
    return [ALL_TOOLS[name] for name in TOOLS[status]]
