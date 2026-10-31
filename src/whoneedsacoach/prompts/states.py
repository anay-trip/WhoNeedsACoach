import json
from datetime import date

from whoneedsacoach.prompts.persona import PERSONA

BLOCKS = {
    "intake": (
        "Ask for whatever the state card is missing: race distance "
        "(5k, 10k, half_marathon, or marathon), race date, run days, and long-run day. "
        "Call set_race or set_schedule when the user provides them. "
        "If need_baseline is true, ask for weekly kilometres and a recent long run, then call set_baseline. "
        "If need_pr is true, ask for a best time and date. Call set_pr when they have one, "
        "or decline_pr when they do not. "
        "If a tool returns a plan, walk the summary, any warnings, and each week: "
        "the run days, kind, distance, and pace or structure. "
        "Ask them to accept it."
    ),
    "review": (
        "Show the weekly kilometres, the personal record when there is one, the summary, "
        "any warnings, and each week: run days, kind, distance, and pace or structure. "
        "When they accept, call accept_plan."
    ),
    "active": (
        "Answer from show_week. Leave mileage changes for Monday."
    ),
    "review_revision": (
        "Show last week planned, last week recorded, and the proposed next week from the state card. "
        "Call accept_revision or reject_revision."
    ),
}


def instructions(plan: dict, today: date) -> str:
    card = {
        "status": plan["status"],
        "today": today.isoformat(),
        "race": plan["race"],
        "schedule": plan["schedule"],
        "snapshot": plan["snapshot"],
        "plan": plan["plan"],
        "pending": plan["pending"],
    }
    return (
        PERSONA.format(today=today.isoformat())
        + "\nState card:\n"
        + json.dumps(card, indent=2)
        + "\n\n"
        + BLOCKS[plan["status"]]
    )
