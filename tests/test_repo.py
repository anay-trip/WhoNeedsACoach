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
