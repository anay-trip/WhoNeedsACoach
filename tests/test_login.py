from pathlib import Path

from whoneedsacoach.auth.login import LoginService
from whoneedsacoach.store.repo import Repo


class _Client:
    def __init__(self, root_holder):
        self.root_holder = root_holder

    def dump(self, path):
        token_dir = Path(path)
        token_dir.mkdir(parents=True, exist_ok=True)
        (token_dir / "garmin_tokens.json").write_text("{}")
        self.root_holder.append(token_dir)


class _Garmin:
    def __init__(self):
        self.client = _Client([])


class _Backend:
    def __init__(self, garmin):
        self.garmin = garmin
        self.finished = None

    def start(self, email, password):
        assert password == "secret"
        return "mfa", (self.garmin, "ticket")

    def finish(self, garmin, ticket, code):
        self.finished = code
        return garmin


def test_mfa_then_saves_the_token_path(tmp_path):
    repo = Repo(tmp_path / "coach.db")
    garmin = _Garmin()
    backend = _Backend(garmin)
    service = LoginService(repo, tmp_path / "tokens", backend)
    started = service.begin("Anay", "anay@example.com", "secret")
    assert started["status"] == "mfa_required"
    ready = service.submit_mfa(started["attempt_id"], "123456")
    assert backend.finished == "123456"
    assert ready["status"] == "ready"
    user = repo.get_user(ready["user_id"])
    assert user["name"] == "Anay"
    assert Path(user["garmin_token_dir"], "garmin_tokens.json").is_file()
