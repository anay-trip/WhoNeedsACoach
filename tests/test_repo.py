from whoneedsacoach.auth.passwords import hash_password
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


def test_email_user_and_refresh_token(tmp_path):
    repo = Repo(tmp_path / "coach.db")
    user = repo.create_user("anay@example.com", hash_password("password1"), "Anay")
    assert user["email"] == "anay@example.com"
    assert repo.get_user_by_email("ANAY@example.com")["id"] == user["id"]
    repo.store_refresh_token(user["id"], "abc")
    row = repo.get_refresh_token("abc")
    assert row["user_id"] == user["id"]
    assert row["revoked_at"] is None
    assert repo.revoke_refresh_token("abc")
    assert repo.get_refresh_token("abc")["revoked_at"] is not None


def test_upsert_plan_for_build_overwrites(tmp_path):
    repo = Repo(tmp_path / "coach.db")
    user = repo.create_user("a@example.com", hash_password("password1"))
    first = repo.upsert_plan_for_build(
        user["id"],
        race={"distance": "10k", "date": "2027-06-01"},
        schedule={"run_days": ["sun"], "long_run_day": "sun"},
        snapshot={"baseline_weekly_km": 20},
        generation_id="gen1",
    )
    assert first["status"] == "pending"
    second = repo.upsert_plan_for_build(
        user["id"],
        race={"distance": "half_marathon", "date": "2027-08-01"},
        schedule={"run_days": ["wed", "sun"], "long_run_day": "sun"},
        snapshot={"baseline_weekly_km": 30},
        generation_id="gen2",
    )
    assert second["id"] == first["id"]
    assert second["status"] == "pending"
    assert second["race"]["distance"] == "half_marathon"
    assert second["plan"] is None
    assert second["error_message"] is None
    assert second["snapshot"]["generation_id"] == "gen2"
