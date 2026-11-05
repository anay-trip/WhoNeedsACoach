import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[3]
load_dotenv(ROOT / ".env", override=True)

GARMIN_REPO = Path(os.environ.get("GARMIN_REPO", "/Users/anay-trip/Documents/AI/projects/garmin_mcp"))
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "gemma4:latest")
DB_PATH = Path(os.environ.get("COACH_DB", ROOT / "data" / "coach.db"))
LOG_PATH = Path(os.environ.get("COACH_LOG", ROOT / "logs" / "coach.log"))
TOKEN_ROOT = Path(os.environ.get("COACH_TOKENS", ROOT / "data" / "tokens"))

# The only account until a UI collects credentials. The CLI passes these into
# LoginService.begin. A later UI calls that same function with form values.
ANAY_NAME = "Anay"
ANAY_EMAIL = os.environ.get("GARMIN_EMAIL", "")
ANAY_PASSWORD = os.environ.get("GARMIN_PASSWORD", "")
