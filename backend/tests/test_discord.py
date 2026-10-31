import httpx

from app.utils import discord


def test_settings_prefer_saved_row_and_fall_back_to_env():
    env = {"DISCORD_WEBHOOK_URL": "https://env"}
    assert discord.resolve_settings(None, env)["webhook_url"] == "https://env"
    assert discord.resolve_settings({"enabled": True, "webhook_url": ""}, env)["webhook_url"] == "https://env"
    saved = discord.resolve_settings({"enabled": True, "webhook_url": "https://saved", "threshold": 5.0}, env)
    assert saved["webhook_url"] == "https://saved" and saved["threshold"] == 5.0
    assert saved["added_threshold"] == discord.DEFAULT_SETTINGS["added_threshold"]


def test_disabled_settings_have_no_webhook():
    assert discord.resolve_settings({"enabled": False, "webhook_url": "https://saved"}, {})["webhook_url"] is None


def _client(monkeypatch, handler):
    real = httpx.Client
    monkeypatch.setattr(discord.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))


def test_post_messages_reports_how_far_it_got(monkeypatch):
    sent = []

    def handler(request):
        content = request.read().decode()
        if "3" in content:
            return httpx.Response(500)
        sent.append(content)
        return httpx.Response(204)

    _client(monkeypatch, handler)
    count, error = discord.post_messages("https://hook", ["1", "2", "3", "4"])
    assert (count, error) == (2, "HTTPStatusError status=500")
    assert len(sent) == 2


def test_post_messages_resumes_from_start(monkeypatch):
    sent = []
    _client(monkeypatch, lambda request: sent.append(request.read().decode()) or httpx.Response(204))
    assert discord.post_messages("https://hook", ["1", "2", "3"], start=2) == (3, None)
    assert len(sent) == 1 and "3" in sent[0]


def test_post_messages_waits_once_on_rate_limit(monkeypatch):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(429, json={"retry_after": 0}) if len(calls) == 1 else httpx.Response(204)

    _client(monkeypatch, handler)
    assert discord.post_messages("https://hook", ["1"]) == (1, None)
    assert len(calls) == 2
