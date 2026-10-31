import asyncio
from datetime import date, timedelta

from agents import Runner

from whoneedsacoach.agent.agent import make_agent
from whoneedsacoach.agent.state import CoachContext
from whoneedsacoach.planner.build import monday_of
from whoneedsacoach.planner.revise import propose_next_week
from whoneedsacoach.store.repo import Repo
from whoneedsacoach.tools.garmin import garmin_session
from whoneedsacoach.utils.config import DB_PATH, LOG_PATH
from whoneedsacoach.utils.log import show, write_log


async def chat(user_name: str) -> None:
    repo = Repo(DB_PATH)
    user = repo.get_or_create_user(user_name)
    if repo.get_plan(user["id"]) is None:
        repo.create_plan(user["id"])
    ctx = CoachContext(repo=repo, user_id=user["id"])
    print(f"Garmin responses and plan data are appended to {LOG_PATH}", flush=True)
    async with garmin_session(user["garmin_token_dir"]) as garmin:
        ctx.garmin = garmin
        items: list = []
        pending_input = "Begin."
        while True:
            plan = repo.get_plan(user["id"])
            agent = make_agent(plan, date.today())
            items.append({"role": "user", "content": pending_input})
            result = await Runner.run(agent, items, context=ctx)
            reply = result.final_output or ""
            write_log("coach reply", reply)
            print(f"\ncoach: {reply}\n", flush=True)
            items = result.to_input_list()
            try:
                pending_input = input("you: ")
            except EOFError:
                break
            if pending_input.strip().lower() in {"exit", "quit"}:
                break


async def checkin() -> None:
    repo = Repo(DB_PATH)
    reviewed = monday_of(date.today()) - timedelta(days=7)
    reviewed_key = reviewed.isoformat()
    pairs = repo.plans_with_status("active")
    if not pairs:
        print("no active plans")
        return
    for user, plan in pairs:
        weeks = (plan["plan"] or {}).get("weeks", [])
        index = next((i for i, week in enumerate(weeks) if week["week_start"] == reviewed_key), None)
        if index is None or index + 1 >= len(weeks):
            print(f"{user['name']}: no week to revise")
            continue
        async with garmin_session(user["garmin_token_dir"]) as garmin:
            runs = await garmin.runs_between(reviewed, reviewed + timedelta(days=6))
        show(f"garmin data for {user['name']} week {reviewed_key}", runs)
        actual = sum(run["distance_km"] for run in runs)
        actual_long = max((run["distance_km"] for run in runs), default=0)
        pending = propose_next_week(plan["plan"], reviewed_key, actual, actual_long, runs)
        plan["pending"] = pending
        plan["status"] = "review_revision"
        repo.save_plan(plan)
        label = "changed" if pending["changed"] else "unchanged"
        print(f"{user['name']}: {pending['week']['week_start']} {label}")


def run_chat(user_name: str) -> None:
    asyncio.run(chat(user_name))


def run_checkin() -> None:
    asyncio.run(checkin())
