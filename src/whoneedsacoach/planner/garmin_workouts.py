"""Turn one saved session into the workout JSON Garmin Connect accepts."""

import re

from whoneedsacoach.planner.build import parse_pace_time

RUNNING = {"sportTypeId": 1, "sportTypeKey": "running"}
NO_TARGET = {"targetType": {"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target"}}
EFFORT_CUES = {"easy", "walk/run"}


def workout_json(session: dict) -> dict:
    label = session["type"].replace("_", " ").title()
    description = session.get("structure") or f"{session['distance_km']:g} km {session['type']}"
    return {
        "workoutName": f"{label} {session['distance_km']:g} km",
        "description": description,
        "sportType": dict(RUNNING),
        "workoutSegments": [
            {
                "segmentOrder": 1,
                "sportType": dict(RUNNING),
                "workoutSteps": _steps(session),
            }
        ],
    }


def _steps(session: dict) -> list[dict]:
    parsed = None
    if session["type"] in ("tempo", "intervals") and session.get("structure"):
        parsed = parse_structure(session["structure"])
    if parsed:
        return _structured_steps(session, parsed)
    meters = round(float(session["distance_km"]) * 1000, 1)
    description = session.get("structure") or f"{session['distance_km']:g} km"
    return [_distance_step(1, 3, "interval", meters, description, _pace_fields(session))]


def parse_structure(structure: str) -> dict | None:
    """Warmup, work, and cooldown from the coach's one-line structure. None when it cannot be read."""
    warmup_km = None
    cooldown_km = None
    work_km = None
    repeats = None
    rest_seconds = None
    for part in structure.split(","):
        piece = part.strip()
        lower = piece.lower()
        repeat_match = re.search(r"(\d+)\s*x\s*(\d+(?:\.\d+)?)\s*km", lower)
        km_match = re.search(r"(\d+(?:\.\d+)?)\s*km", lower)
        if "warmup" in lower and km_match:
            warmup_km = float(km_match.group(1))
        elif "cooldown" in lower and km_match:
            cooldown_km = float(km_match.group(1))
        elif repeat_match:
            repeats = (int(repeat_match.group(1)), float(repeat_match.group(2)))
        elif "no rest" in lower:
            rest_seconds = None
        elif re.search(r"\d+(?:\.\d+)?\s*min", lower):
            minutes = float(re.search(r"(\d+(?:\.\d+)?)\s*min", lower).group(1))
            rest_seconds = int(minutes * 60)
        elif km_match and "warmup" not in lower and "cooldown" not in lower:
            work_km = float(km_match.group(1))
    if warmup_km is None or cooldown_km is None:
        return None
    if repeats is None and work_km is None:
        return None
    return {
        "warmup_km": warmup_km,
        "cooldown_km": cooldown_km,
        "work_km": work_km,
        "repeats": repeats,
        "rest_seconds": rest_seconds,
    }


def _structured_steps(session: dict, parsed: dict) -> list[dict]:
    target = _pace_fields(session)
    steps = [
        _distance_step(
            1,
            1,
            "warmup",
            round(parsed["warmup_km"] * 1000, 1),
            f"{parsed['warmup_km']:g} km warmup",
            NO_TARGET,
        )
    ]
    if parsed["repeats"]:
        count, rep_km = parsed["repeats"]
        work = _distance_step(1, 3, "interval", round(rep_km * 1000, 1), f"{rep_km:g} km", target)
        nested = [work]
        if parsed["rest_seconds"]:
            nested.append(_time_step(2, 4, "recovery", parsed["rest_seconds"], "recovery"))
        steps.append(
            {
                "type": "RepeatGroupDTO",
                "stepOrder": 2,
                "numberOfIterations": count,
                "endCondition": {"conditionTypeId": 7, "conditionTypeKey": "iterations"},
                "endConditionValue": float(count),
                "workoutSteps": nested,
            }
        )
        next_order = 3
    else:
        steps.append(
            _distance_step(
                2,
                3,
                "interval",
                round(parsed["work_km"] * 1000, 1),
                f"{parsed['work_km']:g} km",
                target,
            )
        )
        next_order = 3
        if parsed["rest_seconds"]:
            steps.append(_time_step(next_order, 4, "recovery", parsed["rest_seconds"], "recovery"))
            next_order += 1
    steps.append(
        _distance_step(
            next_order,
            2,
            "cooldown",
            round(parsed["cooldown_km"] * 1000, 1),
            f"{parsed['cooldown_km']:g} km cooldown",
            NO_TARGET,
        )
    )
    return steps


def _pace_fields(session: dict) -> dict:
    low = (session.get("pace_low") or "").strip()
    high = (session.get("pace_high") or "").strip()
    if low.lower() in EFFORT_CUES or high.lower() in EFFORT_CUES or not low or not high:
        return dict(NO_TARGET)
    try:
        speeds = sorted({round(1000 / parse_pace_time(low), 3), round(1000 / parse_pace_time(high), 3)})
    except ValueError:
        return dict(NO_TARGET)
    return {
        "targetType": {"workoutTargetTypeId": 6, "workoutTargetTypeKey": "pace.zone"},
        "targetValueOne": speeds[0],
        "targetValueTwo": speeds[-1],
    }


def _distance_step(order: int, type_id: int, type_key: str, meters: float, description: str, target: dict) -> dict:
    return {
        "type": "ExecutableStepDTO",
        "stepOrder": order,
        "stepType": {"stepTypeId": type_id, "stepTypeKey": type_key},
        "description": description,
        "endCondition": {"conditionTypeId": 3, "conditionTypeKey": "distance"},
        "endConditionValue": float(meters),
        **target,
    }


def _time_step(order: int, type_id: int, type_key: str, seconds: int, description: str) -> dict:
    return {
        "type": "ExecutableStepDTO",
        "stepOrder": order,
        "stepType": {"stepTypeId": type_id, "stepTypeKey": type_key},
        "description": description,
        "endCondition": {"conditionTypeId": 2, "conditionTypeKey": "time"},
        "endConditionValue": float(seconds),
        **NO_TARGET,
    }
