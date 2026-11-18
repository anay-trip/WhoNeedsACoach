from typing import Protocol


class ProviderAdapter(Protocol):
    name: str

    def connect(self, user_id: int, credentials: dict) -> dict:
        """Return connected, challenge_required, or error payload."""

    def complete_challenge(self, user_id: int, challenge_id: str, code: str) -> dict:
        """Finish MFA / challenge and return connected or error."""

    def disconnect(self, user_id: int) -> dict:
        """Mark disconnected and best-effort delete token files."""
