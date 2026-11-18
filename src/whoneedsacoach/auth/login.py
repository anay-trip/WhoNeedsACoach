"""Garmin login in two calls. The CLI and the Garmin integration adapter both use this."""

import os
import time
import uuid
from pathlib import Path

ATTEMPT_SECONDS = 300


class GarminConnectBackend:
    """Starts a Garmin login and resumes it when a code is required."""

    def start(self, email: str, password: str):
        if not email or not password:
            raise ValueError("email and password are required")
        from garminconnect import (
            Garmin,
            GarminConnectAuthenticationError,
            GarminConnectConnectionError,
            GarminConnectTooManyRequestsError,
        )

        try:
            garmin = Garmin(email=email, password=password, prompt_mfa=lambda: "", return_on_mfa=True)
            outcome = garmin.login()
        except (GarminConnectAuthenticationError, GarminConnectConnectionError) as exc:
            raise RuntimeError(str(exc).split(":")[0].strip() or "Garmin login failed") from exc
        except GarminConnectTooManyRequestsError as exc:
            raise RuntimeError("Garmin asked us to wait before trying again") from exc
        if isinstance(outcome, tuple) and outcome and outcome[0] == "needs_mfa":
            return "mfa", (garmin, outcome[1])
        return "ready", garmin

    def finish(self, garmin, ticket, code: str):
        garmin.resume_login(ticket, code)
        return garmin


class LoginService:
    def __init__(self, repo, tokens_root: Path, backend=None, attempts: dict | None = None):
        self.repo = repo
        self.tokens_root = Path(tokens_root)
        self.backend = backend or GarminConnectBackend()
        self.attempts = attempts if attempts is not None else {}

    def begin(self, name: str, email: str, password: str, *, user_id: int | None = None) -> dict:
        """CLI path uses name. API path can pass an existing user_id."""
        try:
            status, payload = self.backend.start(email, password)
        except (ValueError, RuntimeError) as exc:
            return {"error": str(exc)}
        if status == "mfa":
            attempt_id = uuid.uuid4().hex
            self.attempts[attempt_id] = {
                "payload": payload,
                "name": name,
                "user_id": user_id,
                "created": time.time(),
            }
            return {"status": "mfa_required", "attempt_id": attempt_id}
        return self._store(name, payload, user_id=user_id)

    def submit_mfa(self, attempt_id: str, code: str) -> dict:
        attempt = self.attempts.get(attempt_id)
        if attempt is None or time.time() - attempt["created"] > ATTEMPT_SECONDS:
            self.attempts.pop(attempt_id, None)
            return {"error": "That login code expired. Start login again."}
        garmin, ticket = attempt["payload"]
        try:
            self.backend.finish(garmin, ticket, code)
        except Exception as exc:
            return {"error": str(exc).split(":")[0].strip() or "Garmin rejected the code"}
        self.attempts.pop(attempt_id, None)
        return self._store(attempt["name"], garmin, user_id=attempt.get("user_id"))

    def _store(self, name: str, garmin, *, user_id: int | None = None) -> dict:
        if user_id is None:
            user = self.repo.get_or_create_user(name)
            user_id = user["id"]
        else:
            user = self.repo.get_user(user_id)
            if user is None:
                return {"error": "user not found"}
        token_dir = self.tokens_root / str(user_id) / "garmin"
        token_dir.mkdir(parents=True, exist_ok=True)
        garmin.client.dump(str(token_dir))
        _secure(token_dir)
        self.repo.upsert_provider_connection(
            user_id,
            "garmin",
            token_dir=str(token_dir),
            status="connected",
        )
        user = self.repo.get_user(user_id)
        return {
            "status": "ready",
            "user_id": user["id"],
            "garmin_token_dir": user["garmin_token_dir"],
        }


def _secure(path: Path) -> None:
    os.chmod(path, 0o700)
    for entry in path.iterdir():
        if entry.is_file():
            os.chmod(entry, 0o600)
