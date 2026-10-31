"""One coach agent. Python owns the calendar and the checks."""

from agents import Agent, ModelSettings

from whoneedsacoach.models.llm import model
from whoneedsacoach.models.training import TrainingPlan
from whoneedsacoach.prompts.training import COACH_INSTRUCTIONS

training_coach = Agent(
    name="Training Coach",
    instructions=COACH_INSTRUCTIONS,
    model=model,
    output_type=TrainingPlan,
    model_settings=ModelSettings(max_tokens=16384),
)
