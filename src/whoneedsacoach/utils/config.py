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

AUTH_JWT_SECRET = os.environ.get("AUTH_JWT_SECRET", "dev-only-change-me-please-set-in-prod")
AUTH_ACCESS_TTL_SECONDS = int(os.environ.get("AUTH_ACCESS_TTL_SECONDS", "900"))
AUTH_COOKIE_SECURE = os.environ.get("AUTH_COOKIE_SECURE", "false").lower() in {"1", "true", "yes"}
CORS_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",")
    if origin.strip()
]

# The only account until a UI collects credentials. The CLI passes these into
# LoginService.begin. A later UI calls that same function with form values.
ANAY_NAME = "Anay"
ANAY_EMAIL = os.environ.get("GARMIN_EMAIL", "")
ANAY_PASSWORD = os.environ.get("GARMIN_PASSWORD", "")
