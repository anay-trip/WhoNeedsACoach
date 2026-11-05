"""Place the current week on Garmin and store workouts Garmin marked complete."""

from datetime import date, timedelta

from whoneedsacoach.planner.build import round_km
from whoneedsacoach.planner.garmin_workouts import workout_json


def sessions_due(plan: dict, today: date) -> list[dict]:
    """Sessions to put on the calendar: the rest of this week, or the next week if this one is finished."""
    weeks = plan.get("weeks") or []
    if not weeks:
        return []
    monday = (today - timedelta(days=today.weekday())).isoformat()
    current = next((week for week in weeks if week["week_start"] == monday), None)
    if current is None:
        upcoming = [week for week in weeks if week["week_start"] > monday]
        current = upcoming[0] if upcoming else None
        if current is None:
            return []
        return [session for session in current["sessions"] if session["date"] >= today.isoformat()]
    due = [session for session in current["sessions"] if session["date"] >= today.isoformat()]
    if due:
        return due
    later = [week for week in weeks if week["week_start"] > monday]
    if not later:
        return []
    return list(later[0]["sessions"])


def ensure_week_totals(plan: dict) -> None:
    for week in plan.get("weeks") or []:
        if "target_distance_km" in week and "long_run_km" in week:
            continue
        sessions = week.get("sessions") or []
        week["target_distance_km"] = round_km(sum(session["distance_km"] for session in sessions))
        longs = [session["distance_km"] for session in sessions if session["type"] == "long"]
        week["long_run_km"] = longs[0] if longs else 0


def week_actuals(rows: list[dict], week: dict) -> tuple[float, float]:
    actual = round_km(sum(row["distance_km"] for row in rows))
    long_dates = {session["date"] for session in week.get("sessions") or [] if session["type"] == "long"}
    longs = [row["distance_km"] for row in rows if row["session_date"] in long_dates]
    return actual, round_km(longs[0]) if longs else 0.0


def sessions_changed(left: dict, right: dict) -> bool:
    def signature(week: dict) -> list[tuple]:
        return [(session["date"], session.get("type"), session.get("distance_km")) for session in week["sessions"]]

    return signature(left) != signature(right)


async def schedule_current_week(garmin, plan: dict, today: date) -> None:
    pending = [session for session in sessions_due(plan, today) if not session.get("workout_id")]
    if not pending:
        return
    schedules = [
        {"calendar_date": session["date"], "workout_data": workout_json(session)}
        for session in pending
    ]
    result = await garmin.schedule_workouts(schedules)
    results = result.get("results", [])
    failures = [item for item in results if item.get("status") != "success"]
    start = date.fromisoformat(min(session["date"] for session in pending))
    end = date.fromisoformat(max(session["date"] for session in pending))
    listed = await garmin.scheduled_workouts(start, end)
    for session, item in zip(pending, results):
        if item.get("status") != "success" or item.get("workout_id") is None:
            continue
        session["workout_id"] = item["workout_id"]
        match = next(
            (
                row
                for row in listed
                if row.get("date") == session["date"] and row.get("workout_id") == item["workout_id"]
            ),
            None,
        )
        if match and match.get("scheduled_workout_id") is not None:
            session["scheduled_workout_id"] = match["scheduled_workout_id"]
    if failures:
        message = failures[0].get("message") or "Garmin did not schedule a workout"
        raise RuntimeError(message)


async def reschedule_changed_week(garmin, plan: dict, old_week: dict, today: date) -> None:
    new_week = next((week for week in plan["weeks"] if week["week_start"] == old_week["week_start"]), None)
    if new_week is None:
        return
    scheduled_ids = [
        session["scheduled_workout_id"]
        for session in old_week["sessions"]
        if session.get("scheduled_workout_id") is not None
    ]
    if sessions_changed(old_week, new_week) and scheduled_ids:
        for scheduled_id in scheduled_ids:
            await garmin.unschedule_workout(scheduled_id)
        for session in new_week["sessions"]:
            session.pop("workout_id", None)
            session.pop("scheduled_workout_id", None)
    await schedule_current_week(garmin, plan, today)


async def sync_completed(garmin, repo, user_id: int, plan: dict, today: date) -> None:
    document = plan.get("plan") or {}
    sessions = [
        session
        for week in document.get("weeks") or []
        for session in week["sessions"]
        if session.get("workout_id") is not None and session["date"] <= today.isoformat()
    ]
    if not sessions:
        return
    start = date.fromisoformat(min(session["date"] for session in sessions))
    end = date.fromisoformat(max(session["date"] for session in sessions))
    listed = await garmin.scheduled_workouts(start, end)
    by_slot = {
        (row.get("date"), row.get("workout_id")): row
        for row in listed
        if row.get("completed") and row.get("activity_id") is not None
    }
    if not by_slot:
        return
    runs = await garmin.runs_between(start, end)
    by_id = {run["id"]: run for run in runs}
    for session in sessions:
        row = by_slot.get((session["date"], session["workout_id"]))
        if row is None:
            continue
        run = by_id.get(row["activity_id"])
        if run is None:
            continue
        repo.upsert_activity(
            {
                "user_id": user_id,
                "plan_id": plan["id"],
                "session_date": session["date"],
                "garmin_activity_id": row["activity_id"],
                "distance_km": run["distance_km"],
                "duration_seconds": run.get("duration_seconds"),
                "workout_id": session["workout_id"],
            }
        )
