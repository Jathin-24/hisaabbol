import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "t.db"))
    for k in ("GNANI_API_KEY", "GEMINI_API_KEY", "GEMINI_MODEL", "REGISTRATION_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "rules")
    monkeypatch.setenv("GNANI_MOCK", "false")
    monkeypatch.setenv("DEMO_ENABLED", "true")
    from app import auth, gnani, llm
    auth.reset_rate_limits(); gnani._transport = None; llm._transport = None; gnani._sem = None


@pytest.fixture
def client():
    from app.main import app
    return TestClient(app, raise_server_exceptions=False)


def make_user(client, name="t"):
    r = client.post("/api/v1/auth/register", json={"name": name}).json()
    return {"Authorization": "Bearer " + r["token"]}


@pytest.fixture
def user(client):
    return make_user(client)


@pytest.fixture
def mock_gnani(monkeypatch):
    monkeypatch.setenv("GNANI_MOCK", "true")
