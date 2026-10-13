import asyncio
from datetime import date
from pathlib import Path

from openai import AsyncOpenAI

from agents import Agent, OpenAIChatCompletionsModel, Runner, set_tracing_disabled
from agents.mcp import MCPServerStdio, create_static_tool_filter

GARMIN_REPO = Path("/Users/anay-trip/Documents/AI/projects/garmin_mcp")
OLLAMA_BASE_URL = "http://localhost:11434/v1"
OLLAMA_MODEL = "gemma4:latest"

set_tracing_disabled(True)

ollama = AsyncOpenAI(base_url=OLLAMA_BASE_URL, api_key="ollama")
ollama_model = OpenAIChatCompletionsModel(
    model=OLLAMA_MODEL,
    openai_client=ollama,
)

async def main() -> None:
    async with MCPServerStdio(
        name="garmin",
        params={
            "command": "uv",
            "args": ["run", "garmin-mcp"],
            "cwd": str(GARMIN_REPO),
            # Optional: shrink the 110+ tool list on the server side
            "env": {
                "GARMIN_ENABLED_TOOLS": (
                    "get_activities,get_activity,get_sleep_data,"
                    "get_stats,get_hrv_data,get_training_readiness"
                ),
            },
        },
        cache_tools_list=True,
        # Default is 5s; Garmin tool calls can take much longer
        client_session_timeout_seconds=120,
        # Extra filter in the SDK (in addition to GARMIN_ENABLED_TOOLS)
        tool_filter=create_static_tool_filter(
            allowed_tool_names=[
                "get_activities",
                "get_activity",
                "get_sleep_data",
                "get_stats",
                "get_hrv_data",
                "get_training_readiness",
            ]
        ),
        # Require a click-through for write tools if you expose them later
        require_approval={
            "always": {
                "tool_names": [
                    "upload_workout",
                    "schedule_workout",
                    "create_walk_run_workout",
                ]
            }
        },
    ) as garmin:
        today = date.today().isoformat()
        agent = Agent(
            name="Garmin coach",
            instructions=(
                f"Today's date is {today}. "
                "You have Garmin Connect tools. Use them to answer "
                "questions about the user's training, sleep, and recovery. "
                "When the user says last night, today, or yesterday, convert "
                "that to YYYY-MM-DD using today's date and pass that exact "
                "date to the Garmin tools. Do not invent dates or numbers."
            ),
            model=ollama_model,
            mcp_servers=[garmin],
        )
        result = await Runner.run(agent, "What was the average distance of my last 5 runs?")
        print(f"YOUR SLEEP! : {result.final_output}")

if __name__ == "__main__":
    asyncio.run(main())