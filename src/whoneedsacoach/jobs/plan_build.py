"""In-process plan build: pending → building → active|failed."""

from datetime import date, timedelta
from uuid import uuid4

from whoneedsacoach.planner.build import (
    DISTANCES,
    RACE_KM,
    four_complete_weeks,
    normalize_day,
    parse_pace_time,
    snapshot_from_runs,
)
from whoneedsacoach.planner.schedule import schedule_current_week
from whoneedsacoach.planner.training import (
    athlete_profile,
    build_training_plan,
    check_profile,
    plan_document,
    write_plan,
)
from whoneedsacoach.tools.garmin import garmin_session
from whoneedsacoach.utils.log import note


def validate_plan_request(body: dict, today: date | None = None) -> dict:
    """Return normalized inputs or raise ValueError with a client-facing message."""
    today = today or date.today()
    race = body.get("race") or {}
    schedule = body.get("schedule") or {}
    baseline = body.get("baseline") or {}
    pr = body.get("pr")

    distance = race.get("distance")
    if distance not in DISTANCES:
        raise ValueError("race.distance must be 5k, 10k, half_marathon, or marathon")
    try:
        race_date = date.fromisoformat(race["date"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("race.date must be YYYY-MM-DD") from exc

    try:
        run_days = [normalize_day(day) for day in schedule["run_days"]]
        long_run_day = normalize_day(schedule["long_run_day"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"schedule invalid: {exc}") from exc
    if long_run_day not in run_days:
        raise ValueError("long_run_day must be one of run_days")

    try:
        weekly_km = float(baseline["weekly_km"])
        long_run_km = float(baseline["long_run_km"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("baseline.weekly_km and baseline.long_run_km are required numbers") from exc

    snapshot = {
        "baseline_weekly_km": weekly_km,
        "baseline_long_run_km": long_run_km,
        "need_baseline": False,
        "need_pr": False,
        "pr_declined": pr is None,
        "pr": None,
    }
    if pr is not None:
        try:
            seconds = parse_pace_time(pr["time"])
            pr_date = date.fromisoformat(pr["date"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("pr.time and pr.date are required when pr is set") from exc
        snapshot["pr"] = {
            "time_seconds": seconds,
            "date": pr_date.isoformat(),
            "pace_sec_per_km": int(seconds / RACE_KM[distance]),
        }
        snapshot["pr_declined"] = False
        snapshot["need_pr"] = False

    race_out = {"distance": distance, "date": race_date.isoformat()}
    schedule_out = {"run_days": run_days, "long_run_day": long_run_day}

    # Fail fast on profile rules before enqueueing.
    profile = athlete_profile(race_out, schedule_out, snapshot)
    failed = check_profile(profile, today)
    if failed:
        raise ValueError(failed["error"])

    return {
        "race": race_out,
        "schedule": schedule_out,
        "snapshot": snapshot,
        "generation_id": uuid4().hex,
    }


async def run_plan_build(repo, user_id: int, generation_id: str, *, today: date | None = None) -> None:
    today = today or date.today()
    plan = repo.get_plan(user_id)
    if plan is None:
        return
    current_gen = (plan.get("snapshot") or {}).get("generation_id")
    if current_gen != generation_id:
        note(f"plan build {generation_id} superseded for user {user_id}")
        return

    repo.set_plan_status(user_id, "building", clear_error=True)
    plan = repo.get_plan(user_id)
    try:
        snapshot = dict(plan["snapshot"] or {})
        connection = repo.get_provider_connection(user_id, "garmin")
        token_dir = (
            connection["token_dir"]
            if connection and connection["status"] == "connected" and connection.get("token_dir")
            else None
        )

        if token_dir:
            weeks = four_complete_weeks(today)
            async with garmin_session(token_dir) as garmin:
                runs = await garmin.runs_between(weeks[0], weeks[-1] + timedelta(days=6))
                record = await garmin.personal_record(plan["race"]["distance"])
            enriched = snapshot_from_runs(runs, today, record, plan["race"]["distance"])
            # Client baseline/PR win when provided.
            if snapshot.get("baseline_weekly_km") is not None:
                enriched["baseline_weekly_km"] = snapshot["baseline_weekly_km"]
                enriched["baseline_long_run_km"] = snapshot.get("baseline_long_run_km")
                enriched["need_baseline"] = False
            if snapshot.get("pr") is not None:
                enriched["pr"] = snapshot["pr"]
                enriched["need_pr"] = False
                enriched["pr_declined"] = False
            elif snapshot.get("pr_declined"):
                enriched["pr"] = None
                enriched["need_pr"] = False
                enriched["pr_declined"] = True
            enriched["generation_id"] = generation_id
            snapshot = enriched
            repo.set_plan_status(user_id, "building", snapshot=snapshot, clear_error=True)

        # Re-check supersession after optional provider I/O.
        plan = repo.get_plan(user_id)
        if (plan.get("snapshot") or {}).get("generation_id") != generation_id:
            note(f"plan build {generation_id} superseded after snapshot for user {user_id}")
            return

        profile = athlete_profile(plan["race"], plan["schedule"], snapshot)
        failed = check_profile(profile, today)
        if failed:
            repo.set_plan_status(user_id, "failed", error_message=failed["error"])
            return

        result = await build_training_plan(profile, today)
        document = plan_document(result, today)
        write_plan(profile, result, today)

        plan = repo.get_plan(user_id)
        if (plan.get("snapshot") or {}).get("generation_id") != generation_id:
            note(f"plan build {generation_id} superseded after LLM for user {user_id}")
            return

        if token_dir:
            try:
                async with garmin_session(token_dir) as garmin:
                    await schedule_current_week(garmin, document, today)
            except Exception as exc:
                note(f"schedule_current_week failed for user {user_id}: {exc}")

        # Final supersession check before writing active.
        plan = repo.get_plan(user_id)
        if (plan.get("snapshot") or {}).get("generation_id") != generation_id:
            note(f"plan build {generation_id} superseded before active for user {user_id}")
            return

        repo.set_plan_status(
            user_id,
            "active",
            plan_json=document,
            snapshot=snapshot,
            clear_error=True,
        )
    except Exception as exc:
        plan = repo.get_plan(user_id)
        if plan and (plan.get("snapshot") or {}).get("generation_id") == generation_id:
            repo.set_plan_status(user_id, "failed", error_message=str(exc))
        note(f"plan build failed for user {user_id}: {exc}")
