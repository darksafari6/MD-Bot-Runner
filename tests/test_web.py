"""End-to-end HTTP tests against the real FastAPI app (no browser needed)."""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from wamanager.api import _qr_svg, create_app
from wamanager.config import Settings


@pytest.fixture()
def client(settings: Settings, monkeypatch):
    # Never touch a real WhatsApp socket during tests.
    from wamanager.engine import EngineUnavailable

    monkeypatch.setattr(
        "wamanager.engine.Engine._require_neonize",
        lambda self: (_ for _ in ()).throw(EngineUnavailable("neonize disabled in tests")),
    )
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client


def test_dashboard_renders(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Create bot" in response.text


def test_static_assets_are_served(client):
    for path in ("/static/app.css", "/static/app.js", "/static/htmx.min.js"):
        assert client.get(path).status_code == 200, path


def test_health_reports_engine_state(client):
    payload = client.get("/api/health").json()
    assert payload["status"] == "ok"
    assert payload["version"] == "3.0.0"
    assert payload["engine"]["limit"] > 0


def test_create_bot_via_api(client):
    response = client.post("/api/bots", data={"name": "Support Bot"})
    assert response.status_code == 201
    bot = response.json()["bot"]
    assert bot["id"] == "support-bot"
    assert bot["status"] == "stopped"
    assert {c["name"] for c in bot["commands"]} >= {"ping", "help"}


def test_duplicate_names_get_unique_ids(client):
    first = client.post("/api/bots", data={"name": "Same"}).json()["bot"]["id"]
    second = client.post("/api/bots", data={"name": "Same"}).json()["bot"]["id"]
    assert first != second


def test_empty_name_is_rejected(client):
    assert client.post("/api/bots", data={"name": "   "}).status_code == 400


def test_unknown_bot_returns_404(client):
    assert client.get("/api/bots/ghost").status_code == 404


def test_invalid_id_is_rejected(client):
    assert client.get("/api/bots/..%2f..%2fetc").status_code in (400, 404)


def test_patch_config_clamps_pacing(client):
    client.post("/api/bots", data={"name": "Clamp Bot"})
    response = client.patch(
        "/api/bots/clamp-bot",
        json={"config": {"outbound_per_minute": 9999, "outbound_min_gap_ms": 1}},
    )
    config = response.json()["bot"]["config"]
    assert config["outbound_per_minute"] == 60
    assert config["outbound_min_gap_ms"] == 250


def test_patch_commands_validates(client):
    client.post("/api/bots", data={"name": "Cmd Bot"})
    bad = client.patch(
        "/api/bots/cmd-bot", json={"commands": [{"name": "bad name!", "response": "x"}]}
    )
    assert bad.status_code == 400
    dupes = client.patch(
        "/api/bots/cmd-bot",
        json={"commands": [{"name": "a", "response": "1"}, {"name": "a", "response": "2"}]},
    )
    assert dupes.status_code == 400

    good = client.patch(
        "/api/bots/cmd-bot", json={"commands": [{"name": "hours", "response": "9-5"}]}
    )
    assert good.status_code == 200
    assert good.json()["bot"]["commands"] == [
        {"name": "hours", "response": "9-5", "enabled": True, "exact": False}
    ]


def test_send_validation_order(client):
    client.post("/api/bots", data={"name": "Send Bot"})
    # Bad recipient is 400 even though the bot is stopped.
    bad_to = client.post("/api/bots/send-bot/messages", json={"to": "nope", "text": "hi"})
    assert bad_to.status_code == 400
    # Valid request but stopped is 409.
    stopped = client.post("/api/bots/send-bot/messages", json={"to": "923001234567", "text": "hi"})
    assert stopped.status_code == 409


def test_start_reports_missing_engine(client):
    client.post("/api/bots", data={"name": "Engine Bot"})
    response = client.post("/api/bots/engine-bot/start")
    # 503: the engine dependency is unavailable, which is not a server bug.
    assert response.status_code == 503
    assert "neonize disabled" in response.json()["error"]


def test_messages_and_conversations_are_empty_initially(client):
    client.post("/api/bots", data={"name": "Inbox Bot"})
    assert client.get("/api/bots/inbox-bot/messages").json()["messages"] == []
    assert client.get("/api/bots/inbox-bot/conversations").json()["conversations"] == []


def test_ui_create_returns_partial(client):
    response = client.post("/ui/bots", data={"name": "UI Bot"})
    assert response.status_code == 200
    assert "UI Bot" in response.text
    assert "<html" not in response.text.lower()


def test_ui_action_start_renders_error_not_crash(client):
    client.post("/ui/bots", data={"name": "Act Bot"})
    response = client.post("/ui/bots/act-bot/start")
    assert response.status_code == 200
    assert "error-line" in response.text


def test_ui_delete_removes_bot(client):
    client.post("/ui/bots", data={"name": "Gone Bot"})
    client.post("/ui/bots/gone-bot/delete")
    assert client.get("/api/bots/gone-bot").status_code == 404


def test_behaviour_form_saves(client):
    client.post("/api/bots", data={"name": "Form Bot"})
    response = client.post(
        "/bots/form-bot/behaviour",
        data={
            "name": "Renamed Bot",
            "command_prefix": ".",
            "respond_to_groups": "on",
            "outbound_per_minute": "5",
            "outbound_min_gap_ms": "3000",
            "allowed_numbers": "+92 300 1234567, junk",
            "blocked_numbers": "",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    bot = client.get("/api/bots/form-bot").json()["bot"]
    assert bot["name"] == "Renamed Bot"
    assert bot["config"]["command_prefix"] == "."
    assert bot["config"]["outbound_per_minute"] == 5
    assert bot["config"]["allowed_numbers"] == ["923001234567"]
    assert bot["config"]["respond_to_dms"] is False  # unchecked box


def test_commands_form_saves(client):
    client.post("/api/bots", data={"name": "Cmd Form"})
    response = client.post(
        "/bots/cmd-form/commands",
        data={"name[]": ["hours", "location"], "response[]": ["9-5", "Islamabad"]},
        follow_redirects=False,
    )
    assert response.status_code == 303
    names = [c["name"] for c in client.get("/api/bots/cmd-form").json()["bot"]["commands"]]
    assert names == ["hours", "location"]


def test_ai_settings_form_saves(client):
    client.post("/api/bots", data={"name": "AI Bot"})
    client.post(
        "/bots/ai-bot/ai",
        data={
            "ai_enabled": "on",
            "ai_model": "llama3.1",
            "ai_base_url": "http://127.0.0.1:11434/v1",
            "ai_persona": "Be terse.",
            "ai_history_turns": "4",
        },
        follow_redirects=False,
    )
    config = client.get("/api/bots/ai-bot").json()["bot"]["config"]
    assert config["ai_enabled"] is True
    assert config["ai_model"] == "llama3.1"
    assert config["ai_history_turns"] == 4


def test_ai_check_reports_missing_provider(client):
    client.post("/api/bots", data={"name": "No AI Bot"})
    response = client.post("/ui/bots/no-ai-bot/ai-check")
    assert response.status_code == 200
    assert "error-line" in response.text


def test_qr_partial_without_session(client):
    client.post("/api/bots", data={"name": "QR Bot"})
    response = client.get("/partials/bots/qr-bot/qr")
    assert response.status_code == 200
    assert "Start the bot" in response.text


def test_qr_svg_renders_locally():
    svg = _qr_svg("whatsapp-qr-payload")
    assert svg is not None
    # Inline-safe: no XML prolog, starts with the svg root element.
    assert svg.startswith("<svg")
    assert not svg.startswith("<?xml")
    # Only the required SVG namespace may appear as a URL — no image/CDN calls,
    # because the QR payload is a login credential.
    urls = set(re.findall(r"https?://[^\s\"'<>)]+", svg))
    assert urls <= {"http://www.w3.org/2000/svg"}
    assert "<image" not in svg
    assert _qr_svg(None) is None


def test_api_token_is_enforced(settings: Settings, monkeypatch):
    from wamanager.engine import EngineUnavailable

    monkeypatch.setattr(
        "wamanager.engine.Engine._require_neonize",
        lambda self: (_ for _ in ()).throw(EngineUnavailable("disabled")),
    )
    object.__setattr__(settings, "api_token", "s3cret")
    app = create_app(settings)
    with TestClient(app) as secured:
        assert secured.get("/api/bots").status_code == 401
        assert (
            secured.get("/api/bots", headers={"Authorization": "Bearer s3cret"}).status_code == 200
        )
        # Health stays open for container healthchecks.
        assert secured.get("/api/health").status_code == 200
        # Pages remain viewable; only the API is protected.
        assert secured.get("/").status_code == 200
