import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
GARMIN_REPO = Path(os.environ.get("GARMIN_REPO", "/Users/anay-trip/Documents/AI/projects/garmin_mcp"))
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "gemma4:latest")
DB_PATH = Path(os.environ.get("COACH_DB", ROOT / "data" / "coach.db"))
LOG_PATH = Path(os.environ.get("COACH_LOG", ROOT / "logs" / "coach.log"))
