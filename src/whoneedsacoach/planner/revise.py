from whoneedsacoach.planner.build import _split, round_km


def _rescale(week: dict, new_target: float, new_long: float) -> dict:
    sessions = [dict(session) for session in week["sessions"]]
    race = [session for session in sessions if session["type"] == "race"]
    long_sessions = [session for session in sessions if session["type"] == "long"]
    others = [session for session in sessions if session["type"] in ("easy", "strides")]
    race_km = sum(session["distance_km"] for session in race)
    remaining = round_km(new_target - race_km)
    if remaining < 0:
        remaining = 0.0
    if long_sessions:
        long_km = min(round_km(new_long), remaining)
        long_sessions[0]["distance_km"] = long_km
        remaining = round_km(remaining - long_km)
    else:
        long_km = week["long_run_km"]
    shares = _split(remaining, len(others))
    for session, distance_km in zip(others, shares):
        session["distance_km"] = distance_km
    updated = dict(week)
    updated["sessions"] = [session for session in sessions if session["distance_km"] > 0]
    updated["target_distance_km"] = round_km(sum(session["distance_km"] for session in sessions))
    if long_sessions:
        updated["long_run_km"] = long_sessions[0]["distance_km"]
    else:
        updated["long_run_km"] = long_km
    return updated


def propose_next_week(
    plan: dict,
    week_reviewed: str,
    actual_distance_km: float,
    actual_long_run_km: float,
    activities: list[dict],
) -> dict | None:
    weeks = plan["weeks"]
    index = next((i for i, week in enumerate(weeks) if week["week_start"] == week_reviewed), None)
    if index is None or index + 1 >= len(weeks):
        return None
    reviewed = weeks[index]
    upcoming = weeks[index + 1]
    actual_distance_km = round_km(actual_distance_km)
    actual_long_run_km = round_km(actual_long_run_km)
    if actual_distance_km < reviewed["target_distance_km"]:
        new_target = min(upcoming["target_distance_km"], actual_distance_km)
        proposed = _rescale(upcoming, new_target, actual_long_run_km)
    else:
        proposed = upcoming
    changed = proposed["sessions"] != upcoming["sessions"] or proposed["target_distance_km"] != upcoming["target_distance_km"]
    return {
        "week_reviewed": week_reviewed,
        "planned_distance_km": reviewed["target_distance_km"],
        "actual_distance_km": actual_distance_km,
        "actual_long_run_km": actual_long_run_km,
        "activities": activities,
        "changed": changed,
        "week": proposed,
    }


def apply_revision(plan: dict, pending: dict) -> dict:
    updated = dict(plan)
    updated["weeks"] = []
    for week in plan["weeks"]:
        if week["week_start"] == pending["week"]["week_start"]:
            updated["weeks"].append(pending["week"])
        else:
            updated["weeks"].append(week)
    return updated
