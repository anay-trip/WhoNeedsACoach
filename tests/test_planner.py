from datetime import date

from whoneedsacoach.planner.build import build_plan, progression, snapshot_from_runs
from whoneedsacoach.planner.revise import apply_revision, propose_next_week


def test_progression_ramps_cuts_back_and_caps():
    rows = progression(20, 8, 8, 30, 14)
    targets = [row["target_distance_km"] for row in rows]
    longs = [row["long_run_km"] for row in rows]
    cutbacks = [row["cutback"] for row in rows]
    assert targets == [20, 22, 24, 22, 24, 26, 24, 12]
    assert longs[0] == 8
    assert longs[2] == 9
    assert longs[3] == 9
    assert cutbacks[3] is True
    assert cutbacks[6] is True
    assert rows[-1]["phase"] == "race"


def test_progression_does_not_grow_past_peak():
    rows = progression(28, 10, 5, 30, 10)
    assert [row["target_distance_km"] for row in rows] == [28, 30, 30, 28, 14]
    assert all(row["long_run_km"] == 10 for row in rows if row["phase"] == "build")


def test_build_plan_paces_and_strides():
    plan = build_plan(
        baseline_weekly_km=20,
        baseline_long_run_km=8,
        distance="10k",
        start=date(2026, 10, 19),
        race_date=date(2026, 11, 15),
        run_days=["tue", "thu", "sun"],
        long_run_day="sun",
        pr_time_seconds=3000,
    )
    assert plan["plan_start"] == "2026-10-19"
    assert len(plan["weeks"]) == 4
    first = plan["weeks"][0]
    assert first["cutback"] is False
    assert [session["type"] for session in first["sessions"]] == ["easy", "easy", "long"]
    assert first["sessions"][0]["pace_sec_per_km"] == 375
    strides_week = plan["weeks"][2]
    assert any(session["type"] == "strides" and session["note"] == "fast and relaxed, 4 x 20s" for session in strides_week["sessions"])
    race_week = plan["weeks"][-1]
    race = next(session for session in race_week["sessions"] if session["type"] == "race")
    assert race["date"] == "2026-11-15"
    assert race["distance_km"] == 10.0
    assert race["pace_sec_per_km"] == 300


def test_snapshot_uses_four_complete_weeks_and_median():
    runs = [
        {"date": "2026-09-15", "distance_km": 10},
        {"date": "2026-09-20", "distance_km": 8},
        {"date": "2026-09-22", "distance_km": 20},
        {"date": "2026-10-01", "distance_km": 12},
        {"date": "2026-10-13", "distance_km": 99},
    ]
    snapshot = snapshot_from_runs(runs, date(2026, 10, 14), {"time_seconds": 3000, "date": "2025-11-02"}, "10k")
    assert [week["week_start"] for week in snapshot["weeks"]] == [
        "2026-09-14",
        "2026-09-21",
        "2026-09-28",
        "2026-10-05",
    ]
    assert snapshot["baseline_weekly_km"] == 15.0
    assert snapshot["baseline_long_run_km"] == 20.0
    assert snapshot["need_baseline"] is False
    assert snapshot["pr"]["pace_sec_per_km"] == 300


def test_monday_hold_uses_the_lower_target_and_actual_long_run():
    plan = {
        "weeks": [
            {"week_start": "2026-10-12", "target_distance_km": 26, "long_run_km": 12, "sessions": []},
            {
                "week_start": "2026-10-19",
                "phase": "build",
                "cutback": True,
                "target_distance_km": 22,
                "long_run_km": 12,
                "sessions": [
                    {"date": "2026-10-20", "weekday": "tue", "type": "easy", "distance_km": 5, "pace_sec_per_km": 375, "note": None},
                    {"date": "2026-10-22", "weekday": "thu", "type": "easy", "distance_km": 5, "pace_sec_per_km": 375, "note": None},
                    {"date": "2026-10-25", "weekday": "sun", "type": "long", "distance_km": 12, "pace_sec_per_km": 375, "note": None},
                ],
            },
        ]
    }
    pending = propose_next_week(plan, "2026-10-12", 24, 10, [{"date": "2026-10-14", "distance_km": 10}])
    assert pending["changed"] is True
    assert pending["week"]["target_distance_km"] == 22
    assert pending["week"]["long_run_km"] == 10
    assert pending["week"]["sessions"][0]["pace_sec_per_km"] == 375


def test_monday_leaves_the_week_when_the_plan_was_met():
    plan = build_plan(20, 8, "5k", date(2026, 10, 12), date(2026, 11, 8), ["tue", "sun"], "sun", 1500)
    reviewed = plan["weeks"][0]
    pending = propose_next_week(
        plan,
        reviewed["week_start"],
        reviewed["target_distance_km"],
        reviewed["long_run_km"],
        [],
    )
    assert pending["changed"] is False
    assert pending["week"] == plan["weeks"][1]


def test_apply_revision_replaces_only_the_upcoming_week():
    plan = build_plan(20, 8, "5k", date(2026, 10, 12), date(2026, 11, 8), ["tue", "sun"], "sun", 1500)
    pending = propose_next_week(plan, plan["weeks"][0]["week_start"], 10, 6, [])
    updated = apply_revision(plan, pending)
    assert updated["weeks"][1] == pending["week"]
    assert updated["weeks"][2] == plan["weeks"][2]
