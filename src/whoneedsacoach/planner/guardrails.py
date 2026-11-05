"""Calendar and checks for a training plan. No model calls."""

import math
from datetime import date, timedelta

from whoneedsacoach.models.training import AthleteProfile, DaySlot, TrainingPlan, Workout

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
RACE_KM = {"5k": 5.0, "10k": 10.0, "half": 21.0975, "marathon": 42.195}
LONG_RUN_CAP_KM = {"5k": 12.0, "10k": 16.0, "half": 22.0, "marathon": 35.0}
# 5k and 10k stay at 40%. Half and marathon never exceed 50%; long_run_share_cap may be lower.
LONG_RUN_SHARE = {"5k": 0.40, "10k": 0.40, "half": 0.50, "marathon": 0.50}
LONG_RUN_SHARE_CEILING = 0.50
TAPER_WEEKS = {"5k": 1, "10k": 1, "half": 2, "marathon": 3}
LONG_RUN_TARGET_KM = {"half": 15.0, "marathon": 32.0}
CONSERVATIVE_LONG_STEP = 1.0
MAX_LONG_STEP = 3.0
# Fresh intervals may be 15 sec/km faster than 5k pace. A stale best slows both quality fences by 20.
FRESH_INTERVAL_MARGIN = 15
STALE_QUALITY_SLOWER = 20
PB_SECONDS = {
    "5k": (15 * 60, 50 * 60),
    "10k": (30 * 60, 100 * 60),
    "half": (75 * 60, 3 * 3600 + 30 * 60),
    "marathon": (2 * 3600 + 30 * 60, 7 * 3600),
}
EFFORT_CUES = {"walk/run", "easy"}
QUALITY = {"tempo", "intervals"}
SIX_MONTHS_DAYS = 183
# Float distances are compared with a small slack so 8.0 and 8.04 are the same.
KM_TOLERANCE = 0.05
RIEGEL_EXPONENT = 1.06


def validate_profile(profile: AthleteProfile, today: date) -> None:
    """Raise ValueError when the inputs cannot start a plan."""
    if profile.race_date < today + timedelta(days=56):
        raise ValueError("The race must be at least 8 weeks (56 days) after today.")
    if profile.weekly_km < 0 or profile.weekly_km > 120:
        raise ValueError("Weekly distance must be from 0 to 120 km.")
    if len(set(profile.run_days)) != len(profile.run_days):
        raise ValueError("Run days repeat.")
    if not 2 <= len(profile.run_days) <= 6:
        raise ValueError("Choose between 2 and 6 run days.")
    if any(day not in WEEKDAYS for day in profile.run_days):
        raise ValueError("Run days must be mon, tue, wed, thu, fri, sat, or sun.")
    if profile.long_run_day not in profile.run_days:
        raise ValueError("The long run must be one of the run days.")
    _validate_personal_best(profile, today)


def runner_mode(profile: AthleteProfile) -> str:
    """new (no running, no best), returning (no running, old best), or amateur."""
    if profile.weekly_km == 0 and profile.pb_distance is None:
        return "new"
    if profile.weekly_km == 0:
        return "returning"
    return "amateur"


def standing_warnings(profile: AthleteProfile) -> list[str]:
    """Warnings that do not ask the coach for a revision."""
    if profile.weekly_km == 0 and profile.race_distance in ("half", "marathon"):
        return [
            "Weekly distance is 0 for a half or marathon. This plan aims to finish, "
            "including by run/walk. It does not support a time goal."
        ]
    return []


def build_slots(profile: AthleteProfile, today: date) -> list[DaySlot]:
    """Every date from today through race day, with rest, run, long, or race.

    Race day wins when it falls on a usual run day. The coach is later shown
    only the run, long, and race slots.
    """
    slots: list[DaySlot] = []
    day = today
    run_days = set(profile.run_days)
    while day <= profile.race_date:
        weekday = WEEKDAYS[day.weekday()]
        if day == profile.race_date:
            role = "race"
        elif weekday == profile.long_run_day:
            role = "long"
        elif weekday in run_days:
            role = "run"
        else:
            role = "rest"
        slots.append(DaySlot(date=day, weekday=weekday, role=role))
        day += timedelta(days=1)
    return slots


def pace_limit_text(profile: AthleteProfile, today: date) -> str | None:
    """Min/km fences for the coach. None when there is no personal best."""
    limits = quality_pace_limits(profile, today)
    if limits is None:
        return None
    return (
        f"Easy and long runs slower than {format_pace(limits['half'])}/km. "
        f"Tempo no faster than {format_pace(limits['tempo'])}/km. "
        f"Intervals no faster than {format_pace(limits['intervals'])}/km."
    )


def quality_pace_limits(profile: AthleteProfile, today: date) -> dict[str, float] | None:
    """Work-pace fences. A stale personal best slows tempo and intervals by 20 sec/km."""
    limits = _pace_limits(profile)
    if limits is None:
        return None
    tempo = limits["10k"]
    intervals = limits["5k"] - FRESH_INTERVAL_MARGIN
    if personal_best_is_stale(profile, today):
        tempo += STALE_QUALITY_SLOWER
        intervals += STALE_QUALITY_SLOWER
    return {"half": limits["half"], "tempo": tempo, "intervals": intervals}


def first_long_ceiling(profile: AthleteProfile) -> float:
    """Highest conservative first long run. About 40% of current weekly distance."""
    cap = LONG_RUN_CAP_KM[profile.race_distance]
    if profile.weekly_km <= 0:
        return min(cap, 5.0)
    return min(cap, max(5.0, profile.weekly_km * 0.4))


def long_run_step_cap(profile: AthleteProfile, today: date) -> float:
    """Max kilometres a half or marathon long run may add.

    1 km when that still reaches the target twice before the taper. Larger when
    the race is too soon, and never above 3 km. A runner at 0 km stays at 1 km.
    """
    target = LONG_RUN_TARGET_KM.get(profile.race_distance)
    if target is None or profile.weekly_km <= 0:
        return CONSERVATIVE_LONG_STEP
    low_start = max(0.0, first_long_ceiling(profile) - 1)
    return _step_cap(low_start, _pre_taper_long_count(profile, today), target)


def long_run_share_cap(profile: AthleteProfile, today: date) -> float:
    """Share cap once a half or marathon long run has reached its target.

    Never above 50%. Lower, in 5% steps, when the other days can grow at the
    slow weekly rate and still leave the long run at its target. 5k and 10k
    stay at 40%. A runner at 0 km keeps the 50% ceiling.
    """
    if profile.race_distance not in LONG_RUN_TARGET_KM or profile.weekly_km <= 0:
        return LONG_RUN_SHARE[profile.race_distance]
    target = LONG_RUN_TARGET_KM[profile.race_distance]
    other = _projected_other_km(profile, today)
    natural = target / (target + other) if target + other > 0 else LONG_RUN_SHARE_CEILING
    share = math.ceil(natural * 20 - 1e-9) / 20
    floor = _share_floor(len(profile.run_days))
    return min(LONG_RUN_SHARE_CEILING, max(floor, share))


def personal_best_is_stale(profile: AthleteProfile, today: date) -> bool:
    """True when the best is older than six months. Intervals stay allowed, at slower paces."""
    if profile.pb_date is None:
        return False
    return (today - profile.pb_date).days > SIX_MONTHS_DAYS


def check_plan(
    plan: TrainingPlan,
    profile: AthleteProfile,
    slots: list[DaySlot],
    today: date,
) -> list[str]:
    """Return one message per unmet output check. An empty list means the plan passed."""
    mode = runner_mode(profile)
    by_date: dict[date, list[Workout]] = {}
    for workout in plan.workouts:
        by_date.setdefault(workout.date, []).append(workout)

    errors: list[str] = []
    chosen: dict[date, Workout] = {}
    slot_dates = {slot.date for slot in slots}
    for slot in slots:
        found = by_date.get(slot.date, [])
        # A missing rest day is the plan. A workout on one is not.
        if slot.role == "rest":
            if found:
                errors.append(f"{slot.date.isoformat()} is a rest day. Leave it out of the plan.")
            continue
        if not found:
            errors.append(f"Missing workout for {slot.date.isoformat()} ({slot.role}).")
            continue
        if len(found) > 1:
            errors.append(f"More than one workout on {slot.date.isoformat()}.")
        workout = found[0]
        chosen[slot.date] = workout
        errors.extend(_check_day(workout, slot.role, profile, mode, today))
    for day in by_date:
        if day not in slot_dates:
            errors.append(f"Unexpected workout on {day.isoformat()}.")

    errors.extend(_check_quality_count(chosen))
    errors.extend(_check_quality_alternation(chosen, profile, mode))
    errors.extend(_check_volume(chosen, slots, profile, mode, today))
    return errors


def format_pace(seconds: float) -> str:
    """Seconds per kilometre as M:SS."""
    total = int(round(seconds))
    return f"{total // 60}:{total % 60:02d}"


def _validate_personal_best(profile: AthleteProfile, today: date) -> None:
    present = (profile.pb_distance is not None, profile.pb_time is not None, profile.pb_date is not None)
    if not any(present):
        return
    if not all(present):
        raise ValueError("A personal best needs a distance, a time, and a date.")
    if profile.pb_date > today:
        raise ValueError("The personal best date is in the future.")
    seconds = parse_duration(profile.pb_time or "")
    if seconds is None:
        raise ValueError("Personal best time must be MM:SS or H:MM:SS.")
    low, high = PB_SECONDS[profile.pb_distance]
    if not low <= seconds <= high:
        raise ValueError("The personal best time is outside a plausible range for that distance.")


def parse_duration(text: str) -> int | None:
    """MM:SS or H:MM:SS to seconds."""
    parts = text.strip().split(":")
    if len(parts) == 2:
        hours, minutes, seconds = "0", parts[0], parts[1]
    elif len(parts) == 3:
        hours, minutes, seconds = parts
    else:
        return None
    if not (hours.isdigit() and minutes.isdigit() and seconds.isdigit()):
        return None
    if len(seconds) != 2 or (len(parts) == 3 and len(minutes) != 2):
        return None
    h, m, s = int(hours), int(minutes), int(seconds)
    if m >= 60 or s >= 60:
        return None
    return h * 3600 + m * 60 + s


def _check_day(
    workout: Workout,
    role: str,
    profile: AthleteProfile,
    mode: str,
    today: date,
) -> list[str]:
    """Kind, distance, structure, and pace for one run, long run, or race day."""
    errors = []
    day = workout.date.isoformat()
    if workout.distance_km < 0:
        errors.append(f"{day} has a negative distance.")
    if workout.distance_km <= KM_TOLERANCE:
        errors.append(f"{day} is a {role} day and needs a distance.")
    expected = _kinds_for(role)
    if workout.kind not in expected:
        allowed = ", ".join(sorted(expected))
        errors.append(f"{day} should be {allowed}, not {workout.kind}.")
    if workout.kind in QUALITY:
        errors.extend(_check_quality_day(workout, profile, mode, today))
    errors.extend(_check_structure(workout))
    errors.extend(_check_pace(workout, profile, today))
    return errors


def _kinds_for(role: str) -> set[str]:
    if role == "run":
        return {"easy", "tempo", "intervals"}
    if role == "long":
        return {"long"}
    return {"race"}


def _check_quality_day(
    workout: Workout,
    profile: AthleteProfile,
    mode: str,
    today: date,
) -> list[str]:
    day = workout.date.isoformat()
    if mode == "new":
        return [f"{day} is {workout.kind}. A new runner has no tempo or intervals."]
    monday = _monday(workout.date)
    if not _quality_week(monday, profile, today):
        return [
            f"{day} is {workout.kind}. Keep speed work out of the early weeks, deload weeks, and the taper."
        ]
    if workout.kind == "intervals" and profile.pb_date is None:
        return [f"{day} is intervals. Intervals need a personal best so the pace is not invented."]
    return []


def _check_structure(workout: Workout) -> list[str]:
    structure = workout.structure.strip().lower()
    day = workout.date.isoformat()
    if workout.kind in QUALITY:
        if not structure:
            return [f"{day} needs a structure: warmup, work, rest, and cooldown."]
        if "warmup" not in structure or "cooldown" not in structure:
            return [f"{day} structure should name the warmup and the cooldown."]
        return []
    if structure:
        return [f"{day} should leave structure empty."]
    return []


def _check_pace(workout: Workout, profile: AthleteProfile, today: date) -> list[str]:
    """Reject paces that are too fast. Matching the fence is allowed. Race pace is not fenced."""
    if workout.kind == "rest":
        return []
    day = workout.date.isoformat()
    if profile.pb_distance is None:
        low = workout.pace_low.strip().lower()
        high = workout.pace_high.strip().lower()
        if low not in EFFORT_CUES or high not in EFFORT_CUES:
            return [f"{day} should use the pace cues walk/run or easy."]
        return []
    low_sec = parse_pace(workout.pace_low)
    high_sec = parse_pace(workout.pace_high)
    if low_sec is None or high_sec is None:
        return [f"{day} needs paces in min/km, such as 6:00."]
    if low_sec > high_sec:
        return [
            f"{day} lists {workout.pace_low} then {workout.pace_high}. Put the faster pace in pace_low."
        ]
    limits = quality_pace_limits(profile, today)
    if limits is None or workout.kind == "race":
        return []
    # Easy and long must be strictly slower than half-marathon pace. Quality work may sit on its fence.
    if workout.kind in ("easy", "long") and low_sec <= limits["half"]:
        return [
            f"{day} {workout.kind} pace {workout.pace_low} is faster than the "
            f"half-marathon fence {format_pace(limits['half'])}/km."
        ]
    if workout.kind == "tempo" and low_sec < limits["tempo"]:
        return [
            f"{day} tempo pace {workout.pace_low} is faster than the "
            f"tempo fence {format_pace(limits['tempo'])}/km."
        ]
    if workout.kind == "intervals" and low_sec < limits["intervals"]:
        return [
            f"{day} intervals pace {workout.pace_low} is faster than the "
            f"intervals fence {format_pace(limits['intervals'])}/km."
        ]
    return []


def _check_quality_count(chosen: dict[date, Workout]) -> list[str]:
    """At most one tempo or intervals day in a Monday–Sunday week."""
    counts: dict[date, int] = {}
    for day, workout in chosen.items():
        if workout.kind in QUALITY:
            monday = _monday(day)
            counts[monday] = counts.get(monday, 0) + 1
    errors = []
    for monday, count in counts.items():
        if count > 1:
            errors.append(
                f"Week of {monday.isoformat()} has {count} tempo or intervals days. Keep it to one."
            )
    return errors


def _check_quality_alternation(
    chosen: dict[date, Workout],
    profile: AthleteProfile,
    mode: str,
) -> list[str]:
    """Tempo, then intervals, then tempo. Skipped when intervals are impossible."""
    if mode == "new" or profile.pb_date is None:
        return []
    quality = sorted(
        ((day, workout) for day, workout in chosen.items() if workout.kind in QUALITY),
        key=lambda item: item[0],
    )
    expected = "tempo"
    errors = []
    for day, workout in quality:
        if workout.kind != expected:
            errors.append(
                f"{day.isoformat()} is {workout.kind}. Quality weeks alternate, "
                f"starting with tempo. This one should be {expected}."
            )
        expected = "intervals" if expected == "tempo" else "tempo"
    return errors


def _check_volume(
    chosen: dict[date, Workout],
    slots: list[DaySlot],
    profile: AthleteProfile,
    mode: str,
    today: date,
) -> list[str]:
    weeks = _weeks(slots, chosen, profile, today)
    errors: list[str] = []
    full = [week for week in weeks if week["full"]]
    build = [week for week in full if not week["taper"]]
    if build:
        errors.extend(_check_build(build, profile, mode))
        errors.extend(_check_deload(build))
    errors.extend(_check_long_runs(weeks, profile, today))
    errors.extend(_check_target_long_runs(weeks, profile, today))
    errors.extend(_check_taper(weeks, full, profile.race_date))
    return errors


def _check_build(build: list[dict], profile: AthleteProfile, mode: str) -> list[str]:
    """First full week stays near current mileage. Later weeks may only creep up.

    An amateur half or marathon caps the easy and quality kilometres, not the
    weekly total, so the long run can reach its target. The other days still
    rise at the slow rate unless a faster rise is what keeps the long run at
    or under half the week. Deload weeks (every third full build week after the
    first) are allowed to drop and are not checked for upward creep.
    """
    errors = []
    first = build[0]
    label = first["monday"].isoformat()
    if mode == "amateur":
        low = profile.weekly_km * 0.8
        high = profile.weekly_km * 1.1
        if first["volume"] < low - KM_TOLERANCE or first["volume"] > high + KM_TOLERANCE:
            errors.append(
                f"Week of {label} is {_km(first['volume'])} km. The first full week should be "
                f"between {_km(low)} and {_km(high)} km."
            )
    else:
        cap = min(2 * len(profile.run_days), 8)
        if first["volume"] > cap + KM_TOLERANCE:
            errors.append(
                f"Week of {label} is {_km(first['volume'])} km. "
                f"The first full week from no running should be at most {cap} km."
            )
    for index, week in enumerate(build[1:], start=1):
        if _is_deload_index(index, len(build)):
            continue
        baseline, returning = _creep_baseline(build, index)
        if profile.weekly_km > 0 and profile.race_distance in LONG_RUN_TARGET_KM:
            before = _non_long_km(baseline)
            after = _non_long_km(week)
            allowance = 0.0 if returning else _non_long_allowance(baseline, week)
            if after > before + allowance + KM_TOLERANCE:
                errors.append(_creep_error(week, baseline, after, before, allowance, returning, outside=True))
            continue
        if returning:
            allowance = 0.0
        elif mode == "amateur":
            allowance = max(1.0, baseline["volume"] * 0.05)
        else:
            allowance = 1.0
        if week["volume"] > baseline["volume"] + allowance + KM_TOLERANCE:
            errors.append(
                _creep_error(week, baseline, week["volume"], baseline["volume"], allowance, returning, outside=False)
            )
    return errors


def _creep_baseline(build: list[dict], index: int) -> tuple[dict, bool]:
    """The week a build week is measured against. The week after a deload uses the week before it."""
    if index >= 2 and _is_deload_index(index - 1, len(build)):
        return build[index - 2], True
    return build[index - 1], False


def _creep_error(
    week: dict,
    baseline: dict,
    actual: float,
    before: float,
    allowance: float,
    returning: bool,
    outside: bool,
) -> str:
    label = week["monday"].isoformat()
    prior = baseline["monday"].isoformat()
    if returning:
        if outside:
            return (
                f"Week of {label} has {_km(actual)} km outside the long run. "
                f"The week after a deload may return to the week of {prior} "
                f"({_km(before)} km outside the long run), not past it."
            )
        return (
            f"Week of {label} is {_km(actual)} km. "
            f"The week after a deload may return to the week of {prior} "
            f"({_km(before)} km), not past it."
        )
    if outside:
        return (
            f"Week of {label} has {_km(actual)} km outside the long run, "
            f"more than {_km(allowance)} km above the previous full week "
            f"({_km(before)} km)."
        )
    return (
        f"Week of {label} is {_km(actual)} km, "
        f"more than {_km(allowance)} km above the previous full week "
        f"({_km(before)} km)."
    )


def _is_deload_index(index: int, build_count: int) -> bool:
    """True for every third full build week after the first, when three remain before taper."""
    # index is 1 for the second full build week (build[1]).
    return index >= 1 and index % 3 == 0 and index + 1 <= build_count - 2


def _check_deload(build: list[dict]) -> list[str]:
    """Every third full build week after the first drops volume and skips quality work."""
    errors = []
    for index, week in enumerate(build):
        if index == 0 or not _is_deload_index(index, len(build)):
            continue
        previous = build[index - 1]
        label = week["monday"].isoformat()
        cap = previous["volume"] * 0.8
        if week["volume"] > cap + KM_TOLERANCE:
            errors.append(
                f"Week of {label} is {_km(week['volume'])} km. "
                f"This deload week should be 20% less than the previous full week "
                f"({_km(previous['volume'])} km), so at most {_km(cap)} km."
            )
        quality = [
            workout
            for workout in week["workouts"]
            if workout.kind in ("tempo", "intervals")
        ]
        if quality:
            kinds = ", ".join(sorted({workout.kind for workout in quality}))
            errors.append(
                f"Week of {label} has {kinds}. Keep deload weeks to easy and long only."
            )
    return errors


def _check_long_runs(weeks: list[dict], profile: AthleteProfile, today: date) -> list[str]:
    """Absolute long-run cap, plus the share of that week's volume on a full week.

    Half and marathon weeks stay at or under 50%. After the first full week, a
    long run that has reached its target must also sit under the lower share
    this calendar can hold.
    """
    cap = LONG_RUN_CAP_KM[profile.race_distance]
    ceiling = LONG_RUN_SHARE[profile.race_distance]
    target = LONG_RUN_TARGET_KM.get(profile.race_distance) if profile.weekly_km > 0 else None
    tight = long_run_share_cap(profile, today) if target is not None else None
    seen_full = False
    errors = []
    for week in weeks:
        for workout in week["long_runs"]:
            day = workout.date.isoformat()
            if workout.distance_km > cap + KM_TOLERANCE:
                errors.append(f"{day} long run is {_km(workout.distance_km)} km. The cap is {cap:g} km.")
            # The opening week is often only the long run, so the share check waits for a full week.
            if not week["full"] or week["volume"] <= 0:
                continue
            share = ceiling
            if (
                tight is not None
                and target is not None
                and seen_full
                and workout.distance_km + KM_TOLERANCE >= target
            ):
                share = tight
            if workout.distance_km > week["volume"] * share + KM_TOLERANCE:
                errors.append(
                    f"{day} long run is {_km(workout.distance_km)} km, "
                    f"more than {round(share * 100)}% of the week's {_km(week['volume'])} km."
                )
        if week["full"]:
            seen_full = True
    return errors


def _check_target_long_runs(weeks: list[dict], profile: AthleteProfile, today: date) -> list[str]:
    """A half or marathon keeps the long-run step small, and an amateur still hits the target twice."""
    if profile.race_distance not in LONG_RUN_TARGET_KM:
        return []
    ordered = [workout for week in weeks for workout in week["long_runs"]]
    if not ordered:
        return ["The plan has no long run."]
    errors = []
    ceiling = first_long_ceiling(profile)
    first = ordered[0]
    day = first.date.isoformat()
    if first.distance_km > ceiling + KM_TOLERANCE or first.distance_km < ceiling - 1 - KM_TOLERANCE:
        errors.append(
            f"{day} long run is {_km(first.distance_km)} km. "
            f"Start within 1 km of {_km(ceiling)} km."
        )
    pre_taper = [workout for week in weeks if not week["taper"] for workout in week["long_runs"]]
    step = long_run_step_cap(profile, today)
    deload_mondays = _deload_mondays(weeks)
    previous = None
    anchor = None
    # A shorter long run is a cutback and is allowed. Only a jump past the step cap fails.
    # The long run after a deload is measured from the long run before that deload.
    for workout in ordered:
        reference = previous
        if previous is not None and _monday(previous.date) in deload_mondays and anchor is not None:
            reference = anchor
        if reference is not None and workout.distance_km > reference.distance_km + step + KM_TOLERANCE:
            errors.append(
                f"{workout.date.isoformat()} long run is {_km(workout.distance_km)} km, "
                f"more than {_km(step)} km above the long run on {reference.date.isoformat()} "
                f"({_km(reference.distance_km)} km)."
            )
        if _monday(workout.date) not in deload_mondays:
            anchor = workout
        previous = workout
    target = LONG_RUN_TARGET_KM[profile.race_distance] if profile.weekly_km > 0 else None
    if target is not None:
        hits = [workout for workout in pre_taper if workout.distance_km + KM_TOLERANCE >= target]
        if len(hits) < 2:
            race = "half marathon" if profile.race_distance == "half" else "marathon"
            errors.append(
                f"A {race} needs at least two long runs of {target:g} km "
                f"before the taper. This plan has {len(hits)}."
            )
    return errors


def _check_taper(weeks: list[dict], full: list[dict], race_date: date) -> list[str]:
    """Taper mileage leaves out the race itself, so a marathon does not fail by being 42 km."""
    errors = []
    earlier = [week["volume"] for week in full if not week["taper"]]
    peak = max(earlier) if earlier else None
    taper = [week for week in weeks if week["taper"]]

    def aside_from_race(week: dict) -> float:
        return sum(
            workout.distance_km for workout in week["workouts"] if workout.date != race_date
        )

    if peak is not None:
        for week in taper:
            volume = aside_from_race(week)
            if volume > peak * 0.85 + KM_TOLERANCE:
                errors.append(
                    f"Week of {week['monday'].isoformat()} is a taper week at {_km(volume)} km "
                    f"aside from the race. Taper weeks should be at most {_km(peak * 0.85)} km."
                )
    # The last taper week is race week. Its days before the race must be the lightest
    # non-deload week. A deload is allowed to sit under race week.
    race_week = taper[-1] if taper else None
    deload_mondays = _deload_mondays(weeks)
    if race_week is not None:
        race_volume = aside_from_race(race_week)
        for week in full:
            if week["monday"] == race_week["monday"] or week["monday"] in deload_mondays:
                continue
            if race_volume > week["volume"] + KM_TOLERANCE:
                errors.append(
                    f"Race week is {_km(race_volume)} km aside from the race, above the week of "
                    f"{week['monday'].isoformat()} ({_km(week['volume'])} km). "
                    "The days before the race should be the lightest week."
                )
                break
    return errors


def _weeks(
    slots: list[DaySlot],
    chosen: dict[date, Workout],
    profile: AthleteProfile,
    today: date,
) -> list[dict]:
    """Group the calendar by Monday. Rest days add no distance because they are not in chosen."""
    grouped: dict[date, list[DaySlot]] = {}
    for slot in slots:
        grouped.setdefault(_monday(slot.date), []).append(slot)
    taper = _taper_monday_set(profile, today)
    weeks = []
    for monday, days in grouped.items():
        workouts = [chosen[day.date] for day in days if day.date in chosen]
        weeks.append(
            {
                "monday": monday,
                "full": _is_full_week(monday, today, profile.race_date),
                "taper": monday in taper,
                "volume": sum(workout.distance_km for workout in workouts),
                "workouts": workouts,
                "long_runs": [workout for workout in workouts if workout.kind == "long"],
            }
        )
    return weeks


def _deload_mondays(weeks: list[dict]) -> set[date]:
    """Full build Mondays that are deloads. Taper weeks are not deloads."""
    build = [week for week in weeks if week["full"] and not week["taper"]]
    return {
        week["monday"]
        for index, week in enumerate(build)
        if _is_deload_index(index, len(build))
    }


def _quality_week(monday: date, profile: AthleteProfile, today: date) -> bool:
    """True on a full week after four easy full weeks, outside the taper and not a deload."""
    full_mondays = _full_mondays(today, profile.race_date)
    taper_start = _monday(profile.race_date) - timedelta(weeks=TAPER_WEEKS[profile.race_distance] - 1)
    if monday not in full_mondays[4:] or monday >= taper_start:
        return False
    build = [day for day in full_mondays if day < taper_start]
    index = build.index(monday)
    return not _is_deload_index(index, len(build))


def _full_mondays(today: date, race_date: date) -> list[date]:
    mondays = []
    monday = _monday(today)
    while monday <= race_date:
        if _is_full_week(monday, today, race_date):
            mondays.append(monday)
        monday += timedelta(weeks=1)
    return mondays


def _is_full_week(monday: date, today: date, race_date: date) -> bool:
    """Monday–Sunday sits entirely inside today through race day. Opening and race weeks often do not."""
    sunday = monday + timedelta(days=6)
    return monday >= today and sunday <= race_date


def _step_cap(start_km: float, count: int, target: float) -> float:
    """Smallest long-run step, in 0.5 km increments, that can still hit the target twice.

    The last two pre-taper long runs sit at the target, so the rise is spread
    over count - 2 steps. A long calendar stays at 1 km. A short one rounds up, to at most 3 km.
    """
    rises = count - 2
    if rises <= 0:
        return MAX_LONG_STEP
    if start_km >= target:
        return CONSERVATIVE_LONG_STEP
    needed = (target - start_km) / rises
    if needed <= CONSERVATIVE_LONG_STEP + 1e-9:
        return CONSERVATIVE_LONG_STEP
    return min(MAX_LONG_STEP, math.ceil(needed * 2 - 1e-9) / 2)


def _share_floor(run_days: int) -> float:
    """Lowest share that still leaves the long run at least as long as the average other day."""
    if run_days <= 1:
        return LONG_RUN_SHARE_CEILING
    return min(LONG_RUN_SHARE_CEILING, math.ceil((1 / run_days) * 20 - 1e-9) / 20)


def _projected_other_km(profile: AthleteProfile, today: date) -> float:
    """Other-day kilometres when the long run can first be required to sit on its target.

    The two target runs can wait until the last two pre-taper long runs. Until
    then the other days grow once per later full build week, at 1 km or 5%.
    """
    other = max(0.0, profile.weekly_km - first_long_ceiling(profile))
    for _ in range(_other_growth_steps(profile, today)):
        other += max(1.0, other * 0.05)
    return other


def _other_growth_steps(profile: AthleteProfile, today: date) -> int:
    """Full build weeks after the first, through the second-to-last pre-taper long run."""
    taper = _taper_monday_set(profile, today)
    long_mondays: list[date] = []
    for slot in build_slots(profile, today):
        if slot.role != "long":
            continue
        monday = _monday(slot.date)
        if monday in taper:
            continue
        if not long_mondays or long_mondays[-1] != monday:
            long_mondays.append(monday)
    if len(long_mondays) < 2:
        return 0
    target_monday = long_mondays[-2]
    full_build = [monday for monday in _full_mondays(today, profile.race_date) if monday not in taper]
    steps = 0
    for monday in full_build[1:]:
        if monday > target_monday:
            break
        steps += 1
    return steps


def _non_long_allowance(previous: dict, week: dict) -> float:
    """How far the other days may rise. The long-run's own increase counts only to stay under 50%."""
    before = _non_long_km(previous)
    slow = max(1.0, before * 0.05)
    this_long = _long_km(week)
    long_increase = max(0.0, this_long - _long_km(previous))
    other_if_slow = before + slow
    if this_long <= LONG_RUN_SHARE_CEILING * (this_long + other_if_slow) + KM_TOLERANCE:
        return slow
    needed = max(0.0, this_long - before)
    return max(slow, min(long_increase, needed))


def _long_km(week: dict) -> float:
    return sum(workout.distance_km for workout in week["long_runs"])


def _pre_taper_long_count(profile: AthleteProfile, today: date) -> int:
    taper = _taper_monday_set(profile, today)
    return sum(
        1
        for slot in build_slots(profile, today)
        if slot.role == "long" and _monday(slot.date) not in taper
    )


def _taper_monday_set(profile: AthleteProfile, today: date) -> set[date]:
    """The last one, two, or three Mondays, depending on the race distance."""
    mondays = _calendar_mondays(today, profile.race_date)
    return set(mondays[-TAPER_WEEKS[profile.race_distance] :])


def _calendar_mondays(today: date, race_date: date) -> list[date]:
    mondays = []
    monday = _monday(today)
    while monday <= race_date:
        mondays.append(monday)
        monday += timedelta(weeks=1)
    return mondays


def _non_long_km(week: dict) -> float:
    return sum(workout.distance_km for workout in week["workouts"] if workout.kind != "long")


def _pace_limits(profile: AthleteProfile) -> dict[str, float] | None:
    """Predicted sec/km for 5k, 10k, half, and marathon. None when there is no usable best."""
    if profile.pb_distance is None or profile.pb_time is None:
        return None
    pb_seconds = parse_duration(profile.pb_time)
    if pb_seconds is None:
        return None
    pb_km = RACE_KM[profile.pb_distance]
    return {name: round(_riegel_pace(pb_seconds, pb_km, km)) for name, km in RACE_KM.items()}


def _riegel_pace(pb_seconds: float, pb_km: float, target_km: float) -> float:
    """Equivalent sec/km at target_km from a result at pb_km. Riegel, exponent 1.06."""
    predicted = pb_seconds * (target_km / pb_km) ** RIEGEL_EXPONENT
    return predicted / target_km


def parse_pace(text: str) -> int | None:
    """M:SS per km to seconds. Accepts an optional /km."""
    cleaned = text.strip().lower().replace("/km", "").replace(" ", "")
    if not cleaned or ":" not in cleaned:
        return None
    minutes, seconds = cleaned.split(":", 1)
    if not (minutes.isdigit() and seconds.isdigit()) or len(seconds) != 2:
        return None
    if int(seconds) >= 60:
        return None
    return int(minutes) * 60 + int(seconds)


def _monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


def _km(value: float) -> str:
    if abs(value - round(value)) < 0.05:
        return str(int(round(value)))
    return f"{value:.1f}"
