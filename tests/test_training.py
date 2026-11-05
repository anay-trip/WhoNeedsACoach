from datetime import date

from whoneedsacoach.models.training import DaySlot, TrainingPlan, Workout
from whoneedsacoach.planner.training import (
    TrainingResult,
    athlete_profile,
    check_profile,
    plan_document,
    plan_markdown,
    write_plan,
)


def test_profile_maps_half_marathon_and_pr():
    profile = athlete_profile(
        {"distance": "half_marathon", "date": "2026-12-25"},
        {"run_days": ["tue", "thu", "sun"], "long_run_day": "sun"},
        {
            "baseline_weekly_km": 20,
            "baseline_long_run_km": 12,
            "pr": {"time_seconds": 2944, "date": "2026-06-01", "pace_sec_per_km": 139},
        },
    )
    assert profile.race_distance == "half"
    assert profile.race_date == date(2026, 12, 25)
    assert profile.weekly_km == 20
    assert profile.pb_distance == "half"
    assert profile.pb_time == "49:04"
    assert profile.pb_date == date(2026, 6, 1)
    assert profile.run_days == ["tue", "thu", "sun"]
    assert profile.long_run_day == "sun"
    assert not hasattr(profile, "baseline_long_run_km")


def test_plan_document_groups_weeks_and_keeps_pace_text():
    result = TrainingResult(
        plan=TrainingPlan(
            short_summary="Easy miles, then a half.",
            workouts=[
                Workout(
                    date=date(2026, 10, 6),
                    kind="easy",
                    distance_km=6,
                    pace_low="6:30",
                    pace_high="7:00",
                ),
                Workout(
                    date=date(2026, 10, 8),
                    kind="tempo",
                    distance_km=8,
                    pace_low="5:10",
                    pace_high="5:20",
                    structure="8 km, 2 km warmup, 3 km tempo, 1 km cooldown",
                ),
                Workout(
                    date=date(2026, 10, 13),
                    kind="long",
                    distance_km=12,
                    pace_low="6:45",
                    pace_high="7:15",
                ),
            ],
        ),
        warnings=["Long run is a bit short."],
    )
    document = plan_document(result, date(2026, 10, 6))
    assert document["plan_start"] == "2026-10-06"
    assert document["short_summary"] == "Easy miles, then a half."
    assert document["warnings"] == ["Long run is a bit short."]
    assert [week["week_start"] for week in document["weeks"]] == ["2026-10-05", "2026-10-12"]
    first = document["weeks"][0]["sessions"]
    assert first[0]["weekday"] == "tue"
    assert first[0]["type"] == "easy"
    assert first[0]["pace_low"] == "6:30"
    assert first[0]["pace_high"] == "7:00"
    assert first[1]["type"] == "tempo"
    assert first[1]["structure"].startswith("8 km")
    assert document["weeks"][1]["sessions"][0]["type"] == "long"
    assert document["weeks"][0]["target_distance_km"] == 14
    assert document["weeks"][0]["long_run_km"] == 0
    assert document["weeks"][1]["target_distance_km"] == 12
    assert document["weeks"][1]["long_run_km"] == 12


def test_plan_markdown_skips_rest_and_prints_structure():
    result = TrainingResult(
        plan=TrainingPlan(
            short_summary="Easy miles, then a half.",
            workouts=[
                Workout(date=date(2026, 10, 6), kind="easy", distance_km=6, pace_low="6:30", pace_high="7:00"),
                Workout(
                    date=date(2026, 10, 8),
                    kind="tempo",
                    distance_km=8,
                    pace_low="5:10",
                    pace_high="5:20",
                    structure="8 km, 2 km warmup, 3 km tempo, 1 km cooldown",
                ),
            ],
        ),
        warnings=["Long run is a bit short."],
    )
    slots = [
        DaySlot(date=date(2026, 10, 5), weekday="mon", role="rest"),
        DaySlot(date=date(2026, 10, 6), weekday="tue", role="run"),
        DaySlot(date=date(2026, 10, 8), weekday="thu", role="run"),
    ]
    text = plan_markdown(slots, result.plan, result.warnings)
    assert text.startswith("## Warnings\n\n- Long run is a bit short.\n\nEasy miles, then a half.\n")
    assert "## Week of 05 Oct 2026 (14 km)" in text
    assert "2026-10-05 mon" not in text
    assert "- 2026-10-06 tue: easy, 6 km, 6:30–7:00/km" in text
    assert "- 2026-10-08 thu: tempo, 8 km, 2 km warmup, 3 km tempo, 1 km cooldown" in text


def test_write_plan_uses_the_race_name(tmp_path):
    profile = athlete_profile(
        {"distance": "half_marathon", "date": "2026-12-25"},
        {"run_days": ["tue", "sun"], "long_run_day": "sun"},
        {"baseline_weekly_km": 20, "pr": None},
    )
    result = TrainingResult(
        plan=TrainingPlan(
            short_summary="Finish the half.",
            workouts=[
                Workout(date=date(2026, 10, 6), kind="easy", distance_km=5, pace_low="easy", pace_high="easy"),
            ],
        ),
        warnings=[],
    )
    path = write_plan(profile, result, date(2026, 10, 6), directory=tmp_path)
    text = path.read_text(encoding="utf-8")
    assert path.name == "half-2026-12-25.md"
    assert text.startswith("Finish the half.\n\nStarting from 20 km per week, peaking at 5 km.")


def test_near_race_is_an_error_payload():
    profile = athlete_profile(
        {"distance": "10k", "date": "2026-11-01"},
        {"run_days": ["tue", "sun"], "long_run_day": "sun"},
        {"baseline_weekly_km": 20, "pr": None},
    )
    payload = check_profile(profile, date(2026, 10, 1))
    assert payload == {"error": "The race must be at least 8 weeks (56 days) after today."}
