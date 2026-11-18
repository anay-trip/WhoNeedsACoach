import shutil
import time
from pathlib import Path

from whoneedsacoach.auth.login import ATTEMPT_SECONDS, LoginService


class GarminAdapter:
    name = "garmin"

    def __init__(self, repo, tokens_root: Path, login_service: LoginService | None = None):
        self.repo = repo
        self.tokens_root = Path(tokens_root)
        self.login = login_service or LoginService(repo, tokens_root)
        # challenge_id -> {user_id, attempt_id, created}
        self.challenges: dict[str, dict] = {}

    def connect(self, user_id: int, credentials: dict) -> dict:
        email = (credentials.get("email") or "").strip()
        password = credentials.get("password") or ""
        user = self.repo.get_user(user_id)
        name = user["display_name"] or user["email"] if user else str(user_id)
        result = self.login.begin(name, email, password, user_id=user_id)
        if result.get("error"):
            return {"status": "error", "error": result["error"]}
        if result.get("status") == "mfa_required":
            challenge_id = result["attempt_id"]
            self.challenges[challenge_id] = {
                "user_id": user_id,
                "attempt_id": result["attempt_id"],
                "created": time.time(),
            }
            return {
                "status": "challenge_required",
                "challenge_id": challenge_id,
                "challenge_type": "mfa",
                "provider": self.name,
            }
        return {
            "status": "connected",
            "provider": self.name,
            "connected_at": self.repo.get_provider_connection(user_id, self.name)["connected_at"],
        }

    def complete_challenge(self, user_id: int, challenge_id: str, code: str) -> dict:
        challenge = self.challenges.get(challenge_id)
        if (
            challenge is None
            or challenge["user_id"] != user_id
            or time.time() - challenge["created"] > ATTEMPT_SECONDS
        ):
            self.challenges.pop(challenge_id, None)
            return {"status": "error", "error": "That login code expired. Start connect again."}
        result = self.login.submit_mfa(challenge["attempt_id"], code)
        self.challenges.pop(challenge_id, None)
        if result.get("error"):
            return {"status": "error", "error": result["error"]}
        connection = self.repo.get_provider_connection(user_id, self.name)
        return {
            "status": "connected",
            "provider": self.name,
            "connected_at": connection["connected_at"] if connection else None,
        }

    def disconnect(self, user_id: int) -> dict:
        connection = self.repo.get_provider_connection(user_id, self.name)
        token_dir = connection["token_dir"] if connection else None
        self.repo.disconnect_provider(user_id, self.name)
        if token_dir:
            try:
                shutil.rmtree(token_dir, ignore_errors=True)
            except OSError:
                pass
        return {"status": "disconnected", "provider": self.name}
