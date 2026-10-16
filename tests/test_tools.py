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
    for n in ("AGENTSEARCH_WALLET_PRIVATE_KEY", "POCKET_PRIVATE_KEY"):
        monkeypatch.delenv(n, raising=False)
    return seen

from crewai_agentsearch import AgentSearchExtractTool, AgentSearchTool, _client


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


@pytest.mark.skipif(not os.environ.get("AGENTSEARCH_LIVE"), reason="set AGENTSEARCH_LIVE=1")
def test_live_free_search():
    out = json.loads(AgentSearchTool(mode="free").run(query="CrewAI custom tools", max_results=2))
    assert out["results"][0]["url"].startswith("http")
