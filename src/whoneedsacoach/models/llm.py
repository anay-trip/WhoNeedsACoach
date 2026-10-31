from agents import OpenAIChatCompletionsModel, set_tracing_disabled
from openai import AsyncOpenAI

from whoneedsacoach.utils.config import OLLAMA_BASE_URL, OLLAMA_MODEL

set_tracing_disabled(True)

_client = AsyncOpenAI(base_url=OLLAMA_BASE_URL, api_key="ollama")
model = OpenAIChatCompletionsModel(model=OLLAMA_MODEL, openai_client=_client)
