import asyncio
from datetime import date

from whoneedsacoach.planner.garmin_workouts import workout_json
from whoneedsacoach.planner.schedule import (
    reschedule_changed_week,
    schedule_current_week,
    sessions_due,
    sync_completed,
)


def _plan():
    return {
        "weeks": [
            {
                "week_start": "2026-11-02",
                "target_distance_km": 18,
                "long_run_km": 10,
                "sessions": [
                    {"date": "2026-11-04", "type": "easy", "distance_km": 8, "pace_low": "6:00", "pace_high": "6:30", "structure": ""},
                    {"date": "2026-11-06", "type": "long", "distance_km": 10, "pace_low": "easy", "pace_high": "easy", "structure": ""},
                ],
            },
            {
                "week_start": "2026-11-09",
                "target_distance_km": 12,
                "long_run_km": 12,
                "sessions": [
                    {"date": "2026-11-11", "type": "tempo", "distance_km": 12, "pace_low": "5:00", "pace_high": "5:15", "structure": "2 km warmup, 4x1 km, 2 min rest, 3 km cooldown"},
                ],
            },
        ]
    }


def test_easy_workout_is_one_distance_step_with_a_pace_range():
    workout = workout_json(_plan()["weeks"][0]["sessions"][0])
    step = workout["workoutSegments"][0]["workoutSteps"][0]
    assert step["endCondition"]["conditionTypeKey"] == "distance"
    assert step["endConditionValue"] == 8000
    assert step["targetType"]["workoutTargetTypeKey"] == "pace.zone"
    assert step["targetValueOne"] < step["targetValueTwo"]


def test_effort_cue_has_no_pace_target():
    workout = workout_json(_plan()["weeks"][0]["sessions"][1])
    step = workout["workoutSegments"][0]["workoutSteps"][0]
    assert step["targetType"]["workoutTargetTypeKey"] == "no.target"


def test_intervals_use_a_repeat_group():
    workout = workout_json(_plan()["weeks"][1]["sessions"][0])
    steps = workout["workoutSegments"][0]["workoutSteps"]
    assert steps[0]["stepType"]["stepTypeKey"] == "warmup"
    assert steps[1]["type"] == "RepeatGroupDTO"
    assert steps[1]["numberOfIterations"] == 4
    assert steps[1]["workoutSteps"][1]["endConditionValue"] == 120
    assert steps[2]["stepType"]["stepTypeKey"] == "cooldown"


def test_sessions_due_are_only_the_rest_of_this_week():
    due = sessions_due(_plan(), date(2026, 11, 4))
    assert [session["date"] for session in due] == ["2026-11-04", "2026-11-06"]


def test_a_finished_week_schedules_the_next_week():
    due = sessions_due(_plan(), date(2026, 11, 8))
    assert [session["date"] for session in due] == ["2026-11-11"]


class FakeGarmin:
    def __init__(self, runs=None, listed=None):
        self.sent = []
        self.removed = []
        self.runs = runs or []
        self.listed = listed

    async def schedule_workouts(self, schedules):
        self.sent.extend(schedules)
        return {
            "results": [
                {"status": "success", "workout_id": 100 + index, "scheduled_date": item["calendar_date"]}
                for index, item in enumerate(schedules, start=1)
            ]
        }

    async def scheduled_workouts(self, start, end):
        if self.listed is not None:
            return self.listed
        return [
            {
                "date": item["calendar_date"],
                "workout_id": 100 + index,
                "scheduled_workout_id": 500 + index,
                "completed": False,
            }
            for index, item in enumerate(self.sent, start=1)
        ]

    async def unschedule_workout(self, scheduled_workout_id):
        self.removed.append(scheduled_workout_id)

    async def runs_between(self, start, end):
        return self.runs


def test_schedule_current_week_stores_ids_and_leaves_later_weeks():
    plan = _plan()
    garmin = FakeGarmin()
    asyncio.run(schedule_current_week(garmin, plan, date(2026, 11, 4)))
    assert [item["calendar_date"] for item in garmin.sent] == ["2026-11-04", "2026-11-06"]
    assert plan["weeks"][0]["sessions"][0]["workout_id"] == 101
    assert plan["weeks"][0]["sessions"][0]["scheduled_workout_id"] == 501
    assert "workout_id" not in plan["weeks"][1]["sessions"][0]


def test_sync_stores_the_linked_activity(tmp_path):
    from whoneedsacoach.store.repo import Repo

    repo = Repo(tmp_path / "coach.db")
    user = repo.get_or_create_user("anay")
    saved = repo.create_plan(user["id"])
    plan = _plan()
    plan["weeks"][0]["sessions"][0]["workout_id"] = 101
    saved["plan"] = plan
    garmin = FakeGarmin(
        runs=[{"id": 900, "date": "2026-11-04", "distance_km": 8.2, "duration_seconds": 3000}],
        listed=[{"date": "2026-11-04", "workout_id": 101, "completed": True, "activity_id": 900}],
    )
    asyncio.run(sync_completed(garmin, repo, user["id"], saved, date(2026, 11, 6)))
    rows = repo.activities_between(user["id"], date(2026, 11, 2), date(2026, 11, 8))
    assert rows[0]["garmin_activity_id"] == 900
    assert rows[0]["session_date"] == "2026-11-04"
    assert rows[0]["distance_km"] == 8.2


def test_reschedule_unschedules_only_a_changed_week_that_was_already_on_the_calendar():
    plan = _plan()
    plan["weeks"][0]["sessions"][0]["workout_id"] = 101
    plan["weeks"][0]["sessions"][0]["scheduled_workout_id"] = 501
    plan["weeks"][0]["sessions"][1]["workout_id"] = 102
    plan["weeks"][0]["sessions"][1]["scheduled_workout_id"] = 502
    old = {
        "week_start": "2026-11-02",
        "sessions": [
            dict(plan["weeks"][0]["sessions"][0]),
            dict(plan["weeks"][0]["sessions"][1]),
        ],
    }
    plan["weeks"][0]["sessions"][0]["distance_km"] = 6
    garmin = FakeGarmin()
    asyncio.run(reschedule_changed_week(garmin, plan, old, date(2026, 11, 4)))
    assert garmin.removed == [501, 502]
    assert plan["weeks"][0]["sessions"][0]["workout_id"] == 101
    assert [item["calendar_date"] for item in garmin.sent] == ["2026-11-04", "2026-11-06"]
