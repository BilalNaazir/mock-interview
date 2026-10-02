def test_profile_requires_login(client):
    assert client.get("/users/me").status_code == 401


def test_profile_returns_only_public_fields(logged_in_client):
    response = logged_in_client.get("/users/me")
    assert response.status_code == 200
    assert response.json() == {
        "email": "tester@example.com",
        "name": "Test User",
        "share_answers_by_default": False,
    }


def test_first_login_creates_profile_and_later_logins_reuse_it(monkeypatch):
    """
    Runs the REAL get_current_user, with only the outside world faked:
    the token check (Cognito's keys) and the userInfo call (Cognito's API).
    """
    from fastapi.testclient import TestClient

    import app.auth as auth
    from app.main import create_app

    class FakeVerifier:
        def verify(self, token):
            return {"sub": "brand-new-user", "token_use": "access"}

    calls = []

    async def fake_fetch_user_info(settings, access_token):
        calls.append(access_token)
        return {"email": "newbie@example.com"}  # Cognito gave no name

    monkeypatch.setattr(auth, "fetch_user_info", fake_fetch_user_info)

    app = create_app()
    app.dependency_overrides[auth.get_token_verifier] = lambda: FakeVerifier()
    headers = {"Authorization": "Bearer any-token"}

    with TestClient(app) as client:
        first = client.get("/users/me", headers=headers)
        second = client.get("/users/me", headers=headers)

    assert first.status_code == 200
    # With no name from Cognito, the name falls back to the start of the email.
    assert first.json()["name"] == "newbie"
    assert first.json()["share_answers_by_default"] is False  # private by default
    assert second.json() == first.json()
    # Cognito's userInfo was only called once: after that, our database knows them.
    assert len(calls) == 1
