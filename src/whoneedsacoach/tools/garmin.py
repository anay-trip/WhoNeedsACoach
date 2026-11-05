import json
import os
from contextlib import asynccontextmanager
from datetime import date

from agents.mcp import MCPServerStdio

from whoneedsacoach.utils.config import GARMIN_REPO
from whoneedsacoach.utils.log import write_log

PR_NAMES = {
    "5k": "Fastest 5K",
    "10k": "Fastest 10K",
    "half_marathon": "Fastest Half Marathon",
    "marathon": "Fastest Marathon",
}


def _text(result) -> str:
    chunks = []
    for block in result.content:
        text = getattr(block, "text", None)
        if text:
            chunks.append(text)
    return "\n".join(chunks)


class Garmin:
    def __init__(self, server: MCPServerStdio):
        self.server = server

    async def _call(self, name: str, arguments: dict) -> str:
        result = await self.server.call_tool(name, arguments)
        text = _text(result)
        write_log(f"garmin_mcp {name}", {"arguments": arguments, "response": text})
        if getattr(result, "isError", False):
            raise RuntimeError(text)
        return text

    async def runs_between(self, start: date, end: date) -> list[dict]:
        runs = []
        page = 0
        while True:
            text = await self._call(
                "get_activities_by_date",
                {
                    "start_date": start.isoformat(),
                    "end_date": end.isoformat(),
                    "activity_type": "running",
                    "page": page,
                    "page_size": 100,
                },
            )
            payload = json.loads(text)
            for activity in payload.get("activities", []):
                if activity.get("type") not in (None, "running"):
                    continue
                run = {
                    "id": activity.get("id"),
                    "date": activity["start_time"][:10],
                    "distance_km": round(activity.get("distance_meters", 0) / 1000, 3),
                }
                if activity.get("duration_seconds") is not None:
                    run["duration_seconds"] = activity["duration_seconds"]
                runs.append(run)
            if not payload.get("has_more"):
                break
            page = payload.get("next_page", page + 1)
        return runs

    async def personal_record(self, distance: str) -> dict | None:
        text = await self._call("get_personal_record", {})
        stripped = text.strip()
        if not stripped.startswith("["):
            return None
        wanted = PR_NAMES[distance]
        for record in json.loads(stripped):
            if record.get("record_type") == wanted and record.get("raw_value") is not None:
                return {
                    "time_seconds": int(record["raw_value"]),
                    "date": record.get("date"),
                }
        return None

    async def schedule_workouts(self, schedules: list[dict]) -> dict:
        text = await self._call("schedule_workouts", {"schedules": schedules})
        payload = _json_object(text)
        if payload is None:
            raise RuntimeError(text)
        return payload

    async def scheduled_workouts(self, start: date, end: date) -> list[dict]:
        text = await self._call(
            "get_scheduled_workouts",
            {"start_date": start.isoformat(), "end_date": end.isoformat()},
        )
        payload = _json_object(text)
        if payload is None:
            return []
        return payload.get("scheduled_workouts", [])

    async def unschedule_workout(self, scheduled_workout_id: int) -> None:
        await self._call("unschedule_workout", {"scheduled_workout_id": scheduled_workout_id})


def _json_object(text: str) -> dict | None:
    stripped = text.strip()
    if not stripped.startswith("{"):
        return None
    return json.loads(stripped)


@asynccontextmanager
async def garmin_session(token_dir: str | None):
    env = os.environ.copy()
    env["GARMIN_ENABLED_TOOLS"] = (
        "get_activities_by_date,get_personal_record,"
        "schedule_workouts,get_scheduled_workouts,unschedule_workout"
    )
    if token_dir:
        env["GARMINTOKENS"] = token_dir
    server = MCPServerStdio(
        name="garmin",
        params={
            "command": "uv",
            "args": ["run", "garmin-mcp"],
            "cwd": str(GARMIN_REPO),
            "env": env,
        },
        cache_tools_list=True,
        client_session_timeout_seconds=120,
    )
    async with server:
        yield Garmin(server)
