from whoneedsacoach.store.repo import Repo


def test_user_plan_round_trip(tmp_path):
    repo = Repo(tmp_path / "coach.db")
    user = repo.get_or_create_user("anay")
    plan = repo.create_plan(user["id"])
    plan["status"] = "review"
    plan["race"] = {"distance": "10k", "date": "2026-12-06"}
    plan["schedule"] = {"run_days": ["sun"], "long_run_day": "sun"}
    saved = repo.save_plan(plan)
    again = repo.get_or_create_user("anay")
    assert again["id"] == user["id"]
    loaded = repo.get_plan(again["id"])
    assert loaded["status"] == "review"
    assert loaded["race"]["distance"] == "10k"
    assert saved["id"] == plan["id"]
    assert repo.plans_with_status("review")[0][0]["name"] == "anay"


def test_login_updates_the_token_directory(tmp_path):
    repo = Repo(tmp_path / "coach.db")
    user = repo.get_or_create_user("anay", str(tmp_path / "old"))
    updated = repo.get_or_create_user("anay", str(tmp_path / "new"))
    assert updated["id"] == user["id"]
    assert updated["garmin_token_dir"] == str(tmp_path / "new")


def test_activity_upsert_keeps_one_row_per_garmin_id(tmp_path):
    from datetime import date

    repo = Repo(tmp_path / "coach.db")
    user = repo.get_or_create_user("anay")
    plan = repo.create_plan(user["id"])
    activity = {
        "user_id": user["id"],
        "plan_id": plan["id"],
        "session_date": "2026-11-04",
        "garmin_activity_id": 42,
        "distance_km": 8.0,
        "duration_seconds": 3000,
        "workout_id": 7,
    }
    repo.upsert_activity(activity)
    activity["distance_km"] = 8.4
    repo.upsert_activity(activity)
    rows = repo.activities_between(user["id"], date(2026, 11, 4), date(2026, 11, 4))
    assert len(rows) == 1
    assert rows[0]["distance_km"] == 8.4
    assert rows[0]["workout_id"] == 7
