import json
import os

import httpx
import pytest


def mock(monkeypatch, mod, status, body):
    real = httpx.Client
    seen = []

    def handler(r):
        seen.append(r)
        return httpx.Response(status, json=body)
    monkeypatch.setattr(mod.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler)))
    for n in ("AGENTSEARCH_WALLET_PRIVATE_KEY", "POCKET_PRIVATE_KEY", "AGENTSEARCH_MODE"):
        monkeypatch.delenv(n, raising=False)
    return seen

from crewai_agentsearch import AgentSearchExtractTool, AgentSearchTool, _client, _ops

# A syntactically valid but throwaway key (never funded, never used to sign in these tests).
DUMMY_KEY = "0x" + "11" * 32
RELAY = "https://relay.agentsearchhq.com/v1/search"


def no_portal(monkeypatch):
    """Fail the test if anything tries the paid path."""
    def boom(*a, **k):
        raise AssertionError("paid portal must not be called")
    monkeypatch.setattr(_client, "call_portal", boom)


def test_free_search(monkeypatch):
    seen = mock(monkeypatch, _client, 200, {"results": [{"title": "t", "url": "https://a", "content": "c"}], "provider": "x"})
    out = json.loads(AgentSearchTool().run(query="hi", max_results=2))
    assert out["results"][0]["url"] == "https://a" and "provider" not in out
    assert str(seen[0].url) == "https://relay.agentsearchhq.com/v1/search"


def test_free_limit(monkeypatch):
    mock(monkeypatch, _client, 429, {})
    assert "Free search limit reached" in AgentSearchTool().run(query="hi")


def test_paid_without_wallet(monkeypatch):
    seen = mock(monkeypatch, _client, 200, {})
    assert "no call was made" in AgentSearchExtractTool().run(url="https://example.com") and not seen


def test_free_limit_message_wording(monkeypatch):
    mock(monkeypatch, _client, 429, {})
    out = AgentSearchTool().run(query="hi")
    assert "up to 25 searches/day per IP" in out and "per user" not in out


@pytest.mark.parametrize("env", ["POCKET_PRIVATE_KEY", "AGENTSEARCH_WALLET_PRIVATE_KEY"])
def test_auto_with_env_key_stays_free(monkeypatch, env):
    seen = mock(monkeypatch, _client, 200, {"results": [{"title": "t", "url": "https://a", "content": "c"}]})
    no_portal(monkeypatch)
    monkeypatch.setenv(env, DUMMY_KEY)
    monkeypatch.setattr(_client, "paid_extra_installed", lambda: True)
    out = json.loads(AgentSearchTool().run(query="hi"))
    assert out["results"][0]["url"] == "https://a" and "payment" not in out
    assert [str(r.url) for r in seen] == [RELAY]


def test_auto_with_env_opt_in_goes_paid(monkeypatch):
    mock(monkeypatch, _client, 200, {})
    monkeypatch.setenv("POCKET_PRIVATE_KEY", DUMMY_KEY)
    monkeypatch.setenv("AGENTSEARCH_MODE", "paid")
    monkeypatch.setattr(_client, "paid_extra_installed", lambda: True)
    calls = []
    monkeypatch.setattr(_client, "call_portal", lambda op, body, client=None: calls.append((op, body)) or {"results": [], "payment": {}})
    json.loads(AgentSearchTool().run(query="hi"))
    assert calls == [("search", {"query": "hi"})]


def test_explicit_paid_unchanged(monkeypatch):
    mock(monkeypatch, _client, 200, {})
    monkeypatch.setenv("POCKET_PRIVATE_KEY", DUMMY_KEY)
    calls = []
    monkeypatch.setattr(_client, "call_portal", lambda op, body, client=None: calls.append((op, body)) or {"results": []})
    AgentSearchTool(mode="paid").run(query="hi", max_results=2)
    assert calls == [("search", {"query": "hi", "max_results": 2})]


def test_explicit_free_ignores_env_opt_in(monkeypatch):
    seen = mock(monkeypatch, _client, 200, {"results": []})
    no_portal(monkeypatch)
    monkeypatch.setenv("POCKET_PRIVATE_KEY", DUMMY_KEY)
    monkeypatch.setenv("AGENTSEARCH_MODE", "paid")
    AgentSearchTool(mode="free").run(query="hi")
    assert [str(r.url) for r in seen] == [RELAY]


@pytest.mark.parametrize("opt_in", [True, False])
def test_auto_missing_extra_falls_back_to_free(monkeypatch, caplog, opt_in):
    seen = mock(monkeypatch, _client, 200, {"results": [{"title": "t", "url": "https://a", "content": "c"}]})
    no_portal(monkeypatch)
    monkeypatch.setenv("POCKET_PRIVATE_KEY", DUMMY_KEY)
    if opt_in:
        monkeypatch.setenv("AGENTSEARCH_MODE", "paid")
    monkeypatch.setattr(_client, "paid_extra_installed", lambda: False)
    with caplog.at_level("WARNING", logger="crewai_agentsearch"):
        out = AgentSearchTool().run(query="hi")
    assert not out.startswith("Error") and json.loads(out)["results"][0]["url"] == "https://a"
    assert [str(r.url) for r in seen] == [RELAY]
    assert any("[paid] extra is not installed" in r.getMessage() for r in caplog.records)
    assert DUMMY_KEY not in caplog.text


def test_explicit_paid_missing_extra_errors(monkeypatch):
    import builtins
    seen = mock(monkeypatch, _client, 200, {})
    monkeypatch.setenv("POCKET_PRIVATE_KEY", DUMMY_KEY)
    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name.split(".")[0] in ("x402", "eth_account"):
            raise ImportError(f"No module named {name!r}")
        return real_import(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", fake_import)
    out = AgentSearchTool(mode="paid").run(query="hi")
    assert out.startswith("Error") and "pip install 'crewai-agentsearch[paid]'" in out
    assert not seen


@pytest.mark.skipif(not os.environ.get("AGENTSEARCH_LIVE"), reason="set AGENTSEARCH_LIVE=1")
def test_live_free_search():
    out = json.loads(AgentSearchTool(mode="free").run(query="CrewAI custom tools", max_results=2))
    assert out["results"][0]["url"].startswith("http")
