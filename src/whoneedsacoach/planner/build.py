from datetime import date, timedelta
from statistics import median

DISTANCES = ("5k", "10k", "half_marathon", "marathon")

RACE_KM = {
    "5k": 5.0,
    "10k": 10.0,
    "half_marathon": 21.1,
    "marathon": 42.2,
}

PEAKS = {
    "5k": (30.0, 10.0),
    "10k": (40.0, 14.0),
    "half_marathon": (50.0, 18.0),
    "marathon": (60.0, 28.0),
}

PACE_OFFSET = {
    "5k": 90,
    "10k": 75,
    "half_marathon": 50,
    "marathon": 40,
}

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def monday_of(day: date) -> date:
    return day - timedelta(days=day.weekday())


def plan_start(today: date) -> date:
    return monday_of(today)


def round_km(value: float) -> float:
    return round(value, 1)


def parse_pace_time(value: str) -> int:
    parts = value.strip().split(":")
    if len(parts) == 1:
        return int(parts[0])
    numbers = [int(part) for part in parts]
    if len(numbers) == 2:
        return numbers[0] * 60 + numbers[1]
    return numbers[0] * 3600 + numbers[1] * 60 + numbers[2]


def weekday_name(day: date) -> str:
    return WEEKDAYS[day.weekday()]


def normalize_day(name: str) -> str:
    key = name.strip().lower()
    aliases = {
        "mon": "mon",
        "monday": "mon",
        "tue": "tue",
        "tues": "tue",
        "tuesday": "tue",
        "wed": "wed",
        "wednesday": "wed",
        "thu": "thu",
        "thur": "thu",
        "thurs": "thu",
        "thursday": "thu",
        "fri": "fri",
        "friday": "fri",
        "sat": "sat",
        "saturday": "sat",
        "sun": "sun",
        "sunday": "sun",
    }
    if key not in aliases:
        raise ValueError(f"unknown day: {name}")
    return aliases[key]


def _split(total: float, count: int) -> list[float]:
    if count <= 0:
        return []
    tenths = int(round(total * 10))
    base, extra = divmod(tenths, count)
    return [(base + (1 if i < extra else 0)) / 10 for i in range(count)]


def progression(
    baseline_weekly: float,
    baseline_long: float,
    week_count: int,
    peak_weekly: float,
    peak_long: float,
) -> list[dict]:
    """Week rows before sessions are attached. The last week is race week when week_count > 1."""
    weekly_ceiling = max(peak_weekly, baseline_weekly)
    long_ceiling = max(peak_long, baseline_long)
    weekly = baseline_weekly
    long_km = min(baseline_long, baseline_weekly)
    rows = []
    build_i = 0
    for index in range(week_count):
        is_race = index == week_count - 1 and week_count > 1
        if index == 0 and not is_race:
            rows.append(
                {
                    "target_distance_km": round_km(weekly),
                    "long_run_km": round_km(long_km),
                    "cutback": False,
                    "phase": "build",
                }
            )
            continue
        if is_race:
            rows.append(
                {
                    "target_distance_km": round_km(rows[-1]["target_distance_km"] / 2),
                    "long_run_km": rows[-1]["long_run_km"],
                    "cutback": False,
                    "phase": "race",
                }
            )
            continue
        build_i += 1
        cutback = build_i % 3 == 0
        if cutback:
            weekly = max(0.0, weekly - 2)
        else:
            weekly = min(weekly + 2, weekly_ceiling)
            if build_i % 2 == 0:
                long_km = min(long_km + 1, long_ceiling)
        long_km = min(long_km, weekly)
        rows.append(
            {
                "target_distance_km": round_km(weekly),
                "long_run_km": round_km(long_km),
                "cutback": cutback,
                "phase": "build",
            }
        )
    if week_count == 1:
        rows[0]["phase"] = "race"
        rows[0]["target_distance_km"] = round_km(baseline_weekly / 2)
    return rows


def _sessions_for_week(
    monday: date,
    row: dict,
    run_days: list[str],
    long_run_day: str,
    easy_pace: int | None,
    race_pace: int | None,
    race_date: date | None,
    race_km: float,
    strides: bool,
) -> list[dict]:
    race_week = row["phase"] == "race"
    days = list(run_days)
    if race_week and race_date is not None:
        race_day = weekday_name(race_date)
        if race_day not in days:
            days.append(race_day)
    days.sort(key=WEEKDAYS.index)

    training_days = []
    for day in days:
        session_date = monday + timedelta(days=WEEKDAYS.index(day))
        if race_week and race_date is not None and session_date == race_date:
            continue
        training_days.append(day)

    if race_week:
        budget = row["target_distance_km"]
        if race_km >= budget:
            training_budget = 0.0
            week_total = race_km
        else:
            training_budget = round_km(budget - race_km)
            week_total = budget
    else:
        training_budget = row["target_distance_km"]
        week_total = training_budget

    long_days = [day for day in training_days if day == long_run_day]
    other_days = [day for day in training_days if day != long_run_day]
    if long_days and not other_days:
        long_km = training_budget
        other_budget = 0.0
    elif long_days:
        long_km = min(row["long_run_km"], training_budget)
        other_budget = round_km(training_budget - long_km)
    else:
        long_km = 0.0
        other_budget = training_budget
    row["long_run_km"] = round_km(long_km) if long_days else row["long_run_km"]
    other_shares = _split(other_budget, len(other_days))
    stride_day = other_days[0] if strides and other_days else None

    sessions = []
    other_index = 0
    for day in days:
        session_date = monday + timedelta(days=WEEKDAYS.index(day))
        if race_week and race_date is not None and session_date == race_date:
            sessions.append(
                {
                    "date": session_date.isoformat(),
                    "weekday": day,
                    "type": "race",
                    "distance_km": race_km,
                    "pace_sec_per_km": race_pace,
                    "note": None,
                }
            )
            continue
        if day == long_run_day and long_days:
            sessions.append(
                {
                    "date": session_date.isoformat(),
                    "weekday": day,
                    "type": "long",
                    "distance_km": round_km(long_km),
                    "pace_sec_per_km": easy_pace,
                    "note": None,
                }
            )
            continue
        kind = "strides" if day == stride_day else "easy"
        sessions.append(
            {
                "date": session_date.isoformat(),
                "weekday": day,
                "type": kind,
                "distance_km": other_shares[other_index],
                "pace_sec_per_km": easy_pace,
                "note": "fast and relaxed, 4 x 20s" if kind == "strides" else None,
            }
        )
        other_index += 1

    row["target_distance_km"] = round_km(week_total)
    row["sessions"] = [session for session in sessions if session["distance_km"] > 0]
    return sessions


def build_plan(
    baseline_weekly_km: float,
    baseline_long_run_km: float,
    distance: str,
    start: date,
    race_date: date,
    run_days: list[str],
    long_run_day: str,
    pr_time_seconds: int,
) -> dict:
    peak_weekly, peak_long = PEAKS[distance]
    race_km = RACE_KM[distance]
    race_pace = int(pr_time_seconds / race_km)
    easy_pace = race_pace + PACE_OFFSET[distance]
    mondays = []
    current = start
    race_monday = monday_of(race_date)
    while current <= race_monday:
        mondays.append(current)
        current += timedelta(days=7)
    rows = progression(
        baseline_weekly_km,
        baseline_long_run_km,
        len(mondays),
        peak_weekly,
        peak_long,
    )
    halfway = len(mondays) // 2
    weeks = []
    for index, (monday, row) in enumerate(zip(mondays, rows)):
        strides = (
            row["phase"] != "race"
            and index >= halfway
            and len(run_days) >= 3
        )
        _sessions_for_week(
            monday,
            row,
            run_days,
            long_run_day,
            easy_pace,
            race_pace,
            race_date,
            race_km,
            strides,
        )
        weeks.append(
            {
                "week_start": monday.isoformat(),
                "phase": row["phase"],
                "cutback": row["cutback"],
                "target_distance_km": row["target_distance_km"],
                "long_run_km": row["long_run_km"],
                "sessions": row["sessions"],
            }
        )
    return {"plan_start": start.isoformat(), "weeks": weeks}


def four_complete_weeks(today: date) -> list[date]:
    this_monday = monday_of(today)
    return [this_monday - timedelta(days=7 * (4 - offset)) for offset in range(4)]


def snapshot_from_runs(runs: list[dict], today: date, pr: dict | None, distance: str) -> dict:
    weeks = []
    for monday in four_complete_weeks(today):
        sunday = monday + timedelta(days=6)
        in_week = []
        for run in runs:
            run_day = date.fromisoformat(run["date"])
            if monday <= run_day <= sunday:
                in_week.append(run["distance_km"])
        weeks.append(
            {
                "week_start": monday.isoformat(),
                "distance_km": round_km(sum(in_week)),
                "long_run_km": round_km(max(in_week, default=0)),
            }
        )
    distances = [week["distance_km"] for week in weeks]
    has_runs = any(distance_km > 0 for distance_km in distances)
    pr_block = None
    if pr is not None:
        pace = int(pr["time_seconds"] / RACE_KM[distance])
        pr_block = {
            "time_seconds": pr["time_seconds"],
            "date": pr["date"],
            "pace_sec_per_km": pace,
        }
    return {
        "weeks": weeks,
        "baseline_weekly_km": round_km(median(distances)) if has_runs else None,
        "baseline_long_run_km": round_km(max(week["long_run_km"] for week in weeks)) if has_runs else None,
        "pr": pr_block,
        "need_baseline": not has_runs,
        "need_pr": pr_block is None,
    }
