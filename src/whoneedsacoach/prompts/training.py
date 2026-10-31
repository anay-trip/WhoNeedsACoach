"""Prompt text for the training coach."""

from datetime import date

from whoneedsacoach.models.training import AthleteProfile, TrainingPlan
from whoneedsacoach.planner.guardrails import (
    LONG_RUN_CAP_KM,
    LONG_RUN_SHARE,
    LONG_RUN_TARGET_KM,
    TAPER_WEEKS,
    first_long_ceiling,
    long_run_share_cap,
    long_run_step_cap,
    pace_limit_text,
    personal_best_is_stale,
    runner_mode,
)

# Standing rules. training_user_prompt adds this runner's dates, fences, and distances.
COACH_INSTRUCTIONS = (
    "You are a conservative coach for amateur runners and complete beginners. "
    "This is amateur guidance, not medical advice. Do not invent injuries. "
    "Write a workout only for the dates you are given. A day you omit is a rest day. "
    "A run day is easy, tempo, or intervals. A long day is long. Race day is race. "
    "Prefer easy running. Raise distance as slowly as the calendar allows. "
    "When the race is soon, increase the long run sooner so it still reaches its target. "
    "A new runner uses walk/run and easy running only, with those words as both paces, "
    "and never tempo or intervals. "
    "When there is no personal best, use the cues walk/run or easy. Do not invent a min/km pace. "
    "When a personal best exists, paces are min/km as M:SS, such as 6:00. "
    "pace_low is the faster end. Use the same value for both ends when there is one pace. "
    "A stale personal best still allows tempo and intervals, at the slower paces you are given. "
    "At most one tempo or intervals day in a week. Alternate those weeks, starting with tempo. "
    "For tempo and intervals, fill structure with one line: total distance, warmup, work, rest, cooldown. "
    "pace_low and pace_high are the work pace, not the warmup. "
    "Leave structure empty on every other day. Do not write a phase or a note."
)


def training_user_prompt(
    profile: AthleteProfile,
    slots,
    today: date,
    failures: list[str] | None = None,
    previous: TrainingPlan | None = None,
) -> str:
    """Profile, fences, and the days to fill. Rest days are checked later but not listed here."""
    mode = runner_mode(profile)
    lines = [
        f"Mode: {mode}",
        f"Today: {today.isoformat()}",
        f"Race: {profile.race_distance} on {profile.race_date.isoformat()}",
        f"Weekly distance: {_km(profile.weekly_km)} km",
        f"Run days: {', '.join(profile.run_days)}",
        f"Long run: {profile.long_run_day}",
    ]
    if profile.pb_distance is None:
        lines.append("No personal best. Use pace cues walk/run or easy. Do not schedule intervals.")
    else:
        lines.append(
            f"Personal best: {profile.pb_time} {profile.pb_distance} on {profile.pb_date.isoformat()}."
        )
        if personal_best_is_stale(profile, today):
            lines.append(
                "The personal best is older than six months, so current fitness is slower. "
                "Tempo and intervals are allowed. Their paces use the slower fences below."
            )
        else:
            lines.append("The personal best is from the last six months. Use the pace fences below.")
        lines.append(pace_limit_text(profile, today) or "")
    lines.append(_training_rules(profile, mode, today))
    # The calendar still contains rest days. The coach only sees days that need a workout.
    lines.append("Days to fill (date weekday role). Omit every other day:")
    for slot in slots:
        if slot.role == "rest":
            continue
        lines.append(f"{slot.date.isoformat()} {slot.weekday} {slot.role}")
    if failures and previous is not None:
        lines.append("The previous plan failed these checks. Fix them and keep the days that passed.")
        lines.extend(f"- {failure}" for failure in failures)
        # The revise call sees the failed plan so days that already passed can stay.
        lines.append("Previous plan:")
        lines.append(previous.short_summary)
        for workout in previous.workouts:
            lines.append(
                f"{workout.date.isoformat()} {workout.kind} "
                f"{workout.distance_km} {workout.pace_low}-{workout.pace_high} {workout.structure}"
            )
    return "\n".join(lines)


def _training_rules(profile: AthleteProfile, mode: str, today: date) -> str:
    """The same numbers the guardrails enforce. Stating them here does not replace the checks."""
    taper = TAPER_WEEKS[profile.race_distance]
    taper_label = "1 week" if taper == 1 else f"{taper} weeks"
    cap = LONG_RUN_CAP_KM[profile.race_distance]
    sentences = [
        "Do not emit rest days.",
        "Do not name a phase and do not write a note.",
        "At most one tempo or intervals day in a week.",
        "No tempo or intervals in a short opening week, the first four full weeks, or the taper.",
        f"The taper is the last {taper_label}. Aside from the race, those weeks stay at or under "
        "85% of the biggest earlier full week, and the days before the race are the lightest week.",
        _long_run_share_sentence(profile, cap),
    ]
    if mode == "new":
        sentences.append(
            "No tempo or intervals at all. The first full week is at most 2 km per run day and at most 8 km."
        )
    elif mode == "returning":
        sentences.append(
            "Start as if new: the first full week is at most 2 km per run day and at most 8 km. "
            "The old personal best is a pace ceiling, not current fitness."
        )
    else:
        sentences.append(
            "The first full week stays between 80% and 110% of the current weekly distance."
        )
    if profile.weekly_km > 0 and profile.race_distance in LONG_RUN_TARGET_KM:
        sentences.append(_long_run_rule(profile, today))
        sentences.append(
            "After the first full week, distance outside the long run rises by at most 1 km "
            "or 5% of the previous week's non-long distance, whichever is larger. "
            "It may rise by the long run's own increase only when that keeps the long run "
            "at or under half the week."
        )
    elif mode == "amateur":
        sentences.append(
            "Each later build week adds at most 1 km or 5% of the previous full week, whichever is larger."
        )
    else:
        sentences.append("Each later build week adds at most 1 km.")
    if mode != "new" and profile.pb_date is not None:
        sentences.append(
            "On the quality weeks, alternate tempo and intervals, starting with tempo. "
            "Tempo is one threshold block between a warmup and a cooldown. "
            "Intervals are repeats with a walking rest, then a cooldown."
        )
    sentences.append(
        "For tempo and intervals, put the whole session in structure as one line. "
        "pace_low and pace_high are the work pace. "
        "Shape, not paces to copy: 7.5 km, 2 km warmup at 6:45/km, 4x1 km at 4:30-4:45/km, "
        "90 sec walk, 1 km cooldown at 7:00/km. "
        "Leave structure empty on easy, long, and race days."
    )
    if profile.weekly_km == 0 and profile.race_distance in ("half", "marathon"):
        sentences.append("The goal is to finish, by run/walk if needed. Do not chase a time.")
    return " ".join(sentences)


def _long_run_share_sentence(profile: AthleteProfile, cap: float) -> str:
    """Absolute cap, plus the share. Half and marathon use a ceiling of half the week."""
    if profile.race_distance in LONG_RUN_TARGET_KM:
        return (
            f"A long run is at most {cap:g} km, and on a full week at most half of that week's distance."
        )
    share = round(LONG_RUN_SHARE[profile.race_distance] * 100)
    return (
        f"A long run is at most {cap:g} km, and on a full week at most {share}% of that week's distance."
    )


def _long_run_rule(profile: AthleteProfile, today: date) -> str:
    """Long-run start, step, and the share this calendar can hold below the 50% ceiling."""
    ceiling = first_long_ceiling(profile)
    step = long_run_step_cap(profile, today)
    target = LONG_RUN_TARGET_KM[profile.race_distance]
    share = round(long_run_share_cap(profile, today) * 100)
    if step <= 1:
        growth = "There is enough time to raise each long run by at most 1 km."
    else:
        growth = (
            f"The race is soon, so each long run may rise by up to {_km(step)} km. "
            "That is the smallest step that still reaches the target twice."
        )
    return (
        f"Start the first long run within 1 km of {_km(ceiling)} km. {growth} "
        f"At least two long runs before the taper are {_km(target)} km or longer. "
        f"Once a long run is at {_km(target)} km, keep it at or under {share}% of that full week. "
        "The first full week may still use up to half. "
        "Grow the other runs steadily so the long run is not half the week "
        "when a lower share still reaches the target."
    )


def _km(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return f"{value:g}"
