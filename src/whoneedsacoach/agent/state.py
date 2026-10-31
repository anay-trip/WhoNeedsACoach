from dataclasses import dataclass
from typing import Any

TOOLS = {
    "intake": ["set_race", "set_schedule", "set_baseline", "set_pr"],
    "review": ["accept_plan"],
    "active": ["show_week"],
    "review_revision": ["accept_revision", "reject_revision"],
}


@dataclass
class CoachContext:
    repo: Any
    user_id: int
    garmin: Any = None
