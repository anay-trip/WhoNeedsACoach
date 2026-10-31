from datetime import date

from agents import Agent, ModelSettings

from whoneedsacoach.models.llm import model
from whoneedsacoach.prompts.states import instructions
from whoneedsacoach.tools.plan_tools import tools_for


def make_agent(plan: dict, today: date) -> Agent:
    return Agent(
        name="Coach",
        instructions=instructions(plan, today),
        model=model,
        tools=tools_for(plan["status"]),
        model_settings=ModelSettings(max_tokens=4096),
    )
