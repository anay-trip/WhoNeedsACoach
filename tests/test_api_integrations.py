from fastapi.testclient import TestClient

from whoneedsacoach.api.app import create_app
from whoneedsacoach.integrations.registry import ProviderRegistry


class FakeGarmin:
    name = "garmin"

    def __init__(self, repo):
        self.repo = repo
        self.challenges = {}

    def connect(self, user_id: int, credentials: dict) -> dict:
        if credentials.get("password") == "need-mfa":
            challenge_id = f"ch-{user_id}"
            self.challenges[challenge_id] = user_id
            return {
                "status": "challenge_required",
                "challenge_id": challenge_id,
                "challenge_type": "mfa",
                "provider": self.name,
            }
        if credentials.get("password") != "secret":
            return {"status": "error", "error": "bad credentials"}
        row = self.repo.upsert_provider_connection(
            user_id, self.name, token_dir="/tmp/fake-garmin", status="connected"
        )
        return {"status": "connected", "provider": self.name, "connected_at": row["connected_at"]}

    def complete_challenge(self, user_id: int, challenge_id: str, code: str) -> dict:
        if self.challenges.get(challenge_id) != user_id or code != "123456":
            return {"status": "error", "error": "bad code"}
        self.challenges.pop(challenge_id, None)
        row = self.repo.upsert_provider_connection(
            user_id, self.name, token_dir="/tmp/fake-garmin", status="connected"
        )
        return {"status": "connected", "provider": self.name, "connected_at": row["connected_at"]}

    def disconnect(self, user_id: int) -> dict:
        self.repo.disconnect_provider(user_id, self.name)
        return {"status": "disconnected", "provider": self.name}


def _authed(tmp_path):
    app = create_app(db_path=tmp_path / "coach.db", tokens_root=tmp_path / "tokens")
    fake = FakeGarmin(app.state.repo)
    app.state.registry = ProviderRegistry(app.state.repo, tmp_path / "tokens", adapters={fake.name: fake})
    client = TestClient(app)
    reg = client.post(
        "/auth/register",
        json={"email": "anay@example.com", "password": "password1"},
    )
    token = reg.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    return client, headers


def test_connect_challenge_list_disconnect(tmp_path):
    client, headers = _authed(tmp_path)

    challenged = client.post(
        "/integrations/connect",
        headers=headers,
        json={"provider": "garmin", "email": "g@example.com", "password": "need-mfa"},
    )
    assert challenged.status_code == 200
    body = challenged.json()
    assert body["status"] == "challenge_required"
    assert body["challenge_type"] == "mfa"

    done = client.post(
        "/integrations/challenge",
        headers=headers,
        json={"provider": "garmin", "challenge_id": body["challenge_id"], "code": "123456"},
    )
    assert done.status_code == 200
    assert done.json()["status"] == "connected"

    listed = client.get("/integrations", headers=headers)
    assert listed.status_code == 200
    assert listed.json()[0]["provider"] == "garmin"
    assert listed.json()[0]["status"] == "connected"

    removed = client.delete("/integrations/garmin", headers=headers)
    assert removed.status_code == 200
    assert removed.json()["status"] == "disconnected"
    listed_again = client.get("/integrations", headers=headers)
    assert listed_again.json()[0]["status"] == "disconnected"


def test_unknown_provider(tmp_path):
    client, headers = _authed(tmp_path)
    response = client.post(
        "/integrations/connect",
        headers=headers,
        json={"provider": "strava", "email": "a@b.com", "password": "x"},
    )
    assert response.status_code == 400
