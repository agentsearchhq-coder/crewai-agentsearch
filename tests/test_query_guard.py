"""0.5.1: short-query guard and relay 4xx fix-input hint."""
import json

import httpx
import pytest

from crewai_agentsearch import _client, _ops
from crewai_agentsearch import AgentSearchTool

def framework_search(q):
    return AgentSearchTool().run(query=q)


DUMMY_KEY = "0x" + "11" * 32


def no_network(monkeypatch):
    monkeypatch.setattr(_client.httpx, "Client", lambda **kw: pytest.fail("no network call expected"))
    monkeypatch.setattr(_client, "call_portal", lambda *a, **k: pytest.fail("no paid call expected"))


def relay(monkeypatch, status, body):
    real = httpx.Client
    seen = []

    def handler(r):
        seen.append(json.loads(r.content))
        return httpx.Response(status, json=body)
    monkeypatch.setattr(_client.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler)))
    for n in _client.KEY_ENV_VARS + ("AGENTSEARCH_MODE",):
        monkeypatch.delenv(n, raising=False)
    return seen


@pytest.mark.parametrize("q", ["a", " a ", "\tZ\n", "?"])
@pytest.mark.parametrize("op", ["search", "news", "search_and_read"])
def test_short_query_rejected_before_any_request(monkeypatch, op, q):
    monkeypatch.setenv("AGENTSEARCH_WALLET_PRIVATE_KEY", DUMMY_KEY)
    no_network(monkeypatch)
    fn = getattr(_ops, op)
    out = fn(q, mode="paid") if op == "search" else fn(q)
    assert out.startswith("Error:")
    assert "too short" in out and "rewrite the query (at least 2 characters)" in out
    assert "Nothing was sent or charged" in out


def test_short_query_rejected_in_free_mode(monkeypatch):
    no_network(monkeypatch)
    out = _ops.search("x", mode="free")
    assert "rewrite the query (at least 2 characters)" in out


def test_empty_query_still_rejected(monkeypatch):
    no_network(monkeypatch)
    for q in ("", "   ", None):
        assert "must not be empty" in _ops.search(q)


def test_framework_tool_short_query(monkeypatch):
    no_network(monkeypatch)
    out = framework_search("k")
    assert "rewrite the query (at least 2 characters)" in str(out)


def test_two_char_query_is_trimmed_and_sent(monkeypatch):
    seen = relay(monkeypatch, 200, {"results": []})
    json.loads(_ops.search("  ai  ", mode="free"))
    assert seen == [{"query": "ai"}]


def test_relay_4xx_says_fix_input(monkeypatch):
    relay(monkeypatch, 400, {"error": "QUERY_TOO_SHORT", "retryable": False})
    out = _ops.search("ok query", mode="free")
    assert "HTTP 400" in out and "fix the query instead of retrying it unchanged" in out


@pytest.mark.parametrize("status", [408, 500, 502])
def test_relay_non_input_errors_have_no_fix_hint(monkeypatch, status):
    relay(monkeypatch, status, {"error": "x"})
    out = _ops.search("ok query", mode="free")
    assert f"HTTP {status}" in out and "fix the query" not in out


def test_relay_429_keeps_limit_message(monkeypatch):
    relay(monkeypatch, 429, {"error": "limit"})
    out = _ops.search("ok query", mode="free")
    assert _client.FREE_LIMIT_MESSAGE in out and "fix the query" not in out
