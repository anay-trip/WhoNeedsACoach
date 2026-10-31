import os

from agents import OpenAIChatCompletionsModel, set_tracing_disabled
from openai import AsyncOpenAI

from whoneedsacoach.utils.config import OLLAMA_BASE_URL, OLLAMA_MODEL

set_tracing_disabled(True)

XAI_BASE_URL = "https://api.x.ai/v1"
DEFAULT_GROK_MODEL = "grok-4.7"


def create_model() -> OpenAIChatCompletionsModel:
    """Use xAI when XAI_API_KEY is set. Otherwise talk to the local Ollama server."""
    api_key = os.getenv("XAI_API_KEY")
    if api_key:
        client = AsyncOpenAI(base_url=XAI_BASE_URL, api_key=api_key)
        model_name = os.getenv("GROK_MODEL", DEFAULT_GROK_MODEL)
    else:
        client = AsyncOpenAI(base_url=OLLAMA_BASE_URL, api_key="ollama")
        model_name = OLLAMA_MODEL
    return OpenAIChatCompletionsModel(model=model_name, openai_client=client)


model = create_model()
