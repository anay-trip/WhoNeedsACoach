from fastapi.testclient import TestClient

from whoneedsacoach.api.app import create_app
from whoneedsacoach.auth.tokens import REFRESH_COOKIE


def _client(tmp_path):
    app = create_app(db_path=tmp_path / "coach.db", tokens_root=tmp_path / "tokens")
    return TestClient(app)


def test_register_login_refresh_logout(tmp_path):
    client = _client(tmp_path)
    registered = client.post(
        "/auth/register",
        json={"email": "anay@example.com", "password": "password1", "display_name": "Anay"},
    )
    assert registered.status_code == 200
    access = registered.json()["access_token"]
    assert access
    assert REFRESH_COOKIE in registered.cookies

    me = client.get("/me", headers={"Authorization": f"Bearer {access}"})
    assert me.status_code == 200
    assert me.json()["email"] == "anay@example.com"
    assert me.json()["plan_status"] is None

    logged_in = client.post(
        "/auth/login",
        json={"email": "anay@example.com", "password": "password1"},
    )
    assert logged_in.status_code == 200
    assert REFRESH_COOKIE in logged_in.cookies

    bad = client.post(
        "/auth/login",
        json={"email": "anay@example.com", "password": "wrong-password"},
    )
    assert bad.status_code == 401

    refreshed = client.post("/auth/refresh")
    assert refreshed.status_code == 200
    assert refreshed.json()["access_token"]

    logout = client.post("/auth/logout")
    assert logout.status_code == 204
    again = client.post("/auth/refresh")
    assert again.status_code == 401


def test_protected_routes_require_bearer(tmp_path):
    client = _client(tmp_path)
    assert client.get("/me").status_code == 401
    assert client.get("/plan").status_code == 401
    assert client.get("/integrations").status_code == 401
