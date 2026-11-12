"""Direct x402 is the default paid route (since 0.3.0). Unit tests use a mock transport; the e2e test needs the local
mock direct API (x402-direct/scripts/mock_mainnet_server.py, mainnet terms + MockFacilitator, no chain)."""
import base64
import json
import os

import httpx
import pytest

from crewai_agentsearch import _client

pytest.importorskip("x402")
from eth_account import Account  # noqa: E402

PRICES = {"search": "8000", "extract": "4000", "render": "10000", "search_and_read": "9000", "news": "8000", "screenshot": "10000"}
BODIES = {"search": {"query": "q", "max_results": 3}, "extract": {"url": "https://example.com", "formats": ["markdown"], "max_chars": 500},
          "render": {"url": "https://example.com", "formats": ["markdown"]},
          "search_and_read": {"query": "q", "num_results": 3, "freshness": "week"},
          "news": {"query": "q", "max_results": 7, "freshness": "day", "include_domains": ["reuters.com"]},
          "screenshot": {"url": "https://example.com", "format": "jpeg", "full_page": True, "viewport": {"width": 390, "height": 844}}}
API = "https://api.agentsearchhq.com"
_REAL_CLIENT = httpx.Client
Err = _client.AgentSearchError


@pytest.fixture(autouse=True)
def env(monkeypatch):
    for k in (*_client.KEY_ENV_VARS, "AGENTSEARCH_MODE", "AGENTSEARCH_X402_DIRECT", "AGENTSEARCH_X402_DIRECT_URL",
              "AGENTSEARCH_PAYMENT_ROUTE", "AGENTSEARCH_MAX_PER_CALL_ATOMIC", "AGENTSEARCH_MAX_TOTAL_ATOMIC",
              "POCKET_MAX_PER_CALL_ATOMIC", "POCKET_MAX_TOTAL_ATOMIC", "AGENTSEARCH_PORTAL_URL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("AGENTSEARCH_WALLET_PRIVATE_KEY", Account.create().key.hex())  # throwaway, unfunded
    _client.reset_session_budget()


def terms(op, **over):
    return {"x402Version": 2, "resource": {"url": f"{API}/x402/v1/{op}", "mimeType": "application/json"},
            "accepts": [{"scheme": "exact", "network": "eip155:8453", "amount": PRICES[op], "asset": _client.USDC_BASE,
                         "payTo": _client.DIRECT_PAYEE, "maxTimeoutSeconds": 300, "extra": {"name": "USD Coin", "version": "2"}, **over}]}


def mock_api(monkeypatch, op, over=None, paid_status=200):
    seen = {"calls": []}

    def handler(req):
        sig = req.headers.get("payment-signature")
        seen["calls"].append({"url": str(req.url), "body": json.loads(req.content), "sig": sig})
        if not sig:
            t = terms(op, **(over or {}))
            return httpx.Response(402, json=t, headers={"PAYMENT-REQUIRED": base64.b64encode(json.dumps(t).encode()).decode()})
        seen["signed"] = json.loads(base64.b64decode(sig))
        rcpt = base64.b64encode(json.dumps({"success": True, "transaction": "0x" + "cd" * 32, "network": "eip155:8453",
                                            "payer": seen["signed"]["payload"]["authorization"]["from"]}).encode()).decode()
        return httpx.Response(paid_status, json={"markdown": "x" * 300, "ok": op}, headers={"PAYMENT-RESPONSE": rcpt})

    monkeypatch.setattr(_client.httpx, "Client", lambda **kw: _REAL_CLIENT(transport=httpx.MockTransport(handler)))
    return seen


def test_default_route_is_direct_pocket_selectable(monkeypatch):
    assert _client.direct_enabled()
    monkeypatch.setenv("AGENTSEARCH_PAYMENT_ROUTE", "pocket")
    assert not _client.direct_enabled()
    monkeypatch.setenv("AGENTSEARCH_PAYMENT_ROUTE", "portal")
    assert not _client.direct_enabled()
    monkeypatch.delenv("AGENTSEARCH_PAYMENT_ROUTE")
    monkeypatch.setenv("AGENTSEARCH_X402_DIRECT", "0")
    assert not _client.direct_enabled()
    monkeypatch.setenv("AGENTSEARCH_PAYMENT_ROUTE", "direct")
    assert _client.direct_enabled()


def test_pocket_route_hits_portal(monkeypatch):
    monkeypatch.setenv("AGENTSEARCH_PAYMENT_ROUTE", "pocket")
    seen = {}

    def handler(req):
        seen["url"] = str(req.url)
        return httpx.Response(500, text="stop")

    monkeypatch.setattr(_client.httpx, "Client", lambda **kw: _REAL_CLIENT(transport=httpx.MockTransport(handler)))
    with pytest.raises(Err):
        _client.call_portal("extract", dict(BODIES["extract"]))
    assert seen["url"].startswith("https://agent.pocket.network/v1/agentsearch-web-extract-v1")


def test_invalid_route_refuses(monkeypatch):
    monkeypatch.setenv("AGENTSEARCH_PAYMENT_ROUTE", "bogus")
    monkeypatch.setattr(_client.httpx, "Client", lambda **kw: pytest.fail("no network call expected"))
    with pytest.raises(Err, match="AGENTSEARCH_PAYMENT_ROUTE must be"):
        _client.call_portal("extract", dict(BODIES["extract"]))


def test_old_pocket_per_call_cap_gets_hint(monkeypatch):
    monkeypatch.setenv("AGENTSEARCH_MAX_PER_CALL_ATOMIC", "5000")
    seen = mock_api(monkeypatch, "render")
    with pytest.raises(Err, match="AGENTSEARCH_PAYMENT_ROUTE=pocket"):
        _client.call_portal("render", dict(BODIES["render"]))
    assert all(c["sig"] is None for c in seen["calls"])


@pytest.mark.parametrize("op", ["search", "extract", "render", "search_and_read", "news", "screenshot"])
def test_direct_signs_for_agentsearch_payee(monkeypatch, op):
    seen = mock_api(monkeypatch, op)
    out = _client.call_portal(op, dict(BODIES[op]))
    assert seen["calls"][0]["url"] == f"{API}/x402/v1/{op}"
    assert set(seen["calls"][1]["body"]) <= set(_client.DIRECT_FIELDS[op])
    a = seen["signed"]["payload"]["authorization"]
    assert a["to"].lower() == _client.DIRECT_PAYEE.lower() and a["value"] == PRICES[op]
    assert out["payment"]["payTo"] == _client.DIRECT_PAYEE and out["payment"]["rail"] == "agentsearch-x402-direct"
    assert out["payment"]["settled"] is True


@pytest.mark.parametrize("over", [{"payTo": _client.PORTAL_PAYEE}, {"amount": "20001"}, {"network": "eip155:84532"},
                                  {"asset": "0x" + "11" * 20}])
def test_direct_refuses_bad_terms(monkeypatch, over):
    seen = mock_api(monkeypatch, "extract", over)
    with pytest.raises(Err, match="Nothing was signed"):
        _client.call_portal("extract", dict(BODIES["extract"]))
    assert len(seen["calls"]) == 1


def test_direct_per_call_cap_can_only_lower(monkeypatch):
    monkeypatch.setenv("AGENTSEARCH_MAX_PER_CALL_ATOMIC", "999999")
    mock_api(monkeypatch, "render", {"amount": "20001"})
    with pytest.raises(Err, match="Nothing was signed"):
        _client.call_portal("render", dict(BODIES["render"]))


def test_direct_url_must_be_https(monkeypatch):
    monkeypatch.setenv("AGENTSEARCH_X402_DIRECT_URL", "http://evil.example")
    with pytest.raises(Err, match="must be https"):
        _client.call_portal("extract", dict(BODIES["extract"]))


def test_no_wallet_message_quotes_direct_prices(monkeypatch):
    for k in _client.KEY_ENV_VARS:
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(Err) as e:
        _client.call_portal("extract", dict(BODIES["extract"]))
    assert "$0.004" in str(e.value) and "AGENTSEARCH_PAYMENT_ROUTE=pocket" in str(e.value)


MOCK = os.environ.get("AGENTSEARCH_TEST_DIRECT_MOCK")  # e.g. http://127.0.0.1:8397


@pytest.mark.skipif(not MOCK, reason="local mock direct API not running")
def test_e2e_against_local_mock(monkeypatch):
    monkeypatch.setenv("AGENTSEARCH_X402_DIRECT_URL", MOCK)
    outs = [_client.call_portal(op, dict(BODIES[op])) for op in ("search", "extract", "render")]
    assert [x["payment"]["amountAtomic"] for x in outs] == ["8000", "4000", "10000"]
    assert all(x["payment"]["settled"] for x in outs)


def test_search_and_read_is_direct_only(monkeypatch):
    monkeypatch.setenv("AGENTSEARCH_PAYMENT_ROUTE", "pocket")
    with pytest.raises(Err, match="own x402 API"):
        _client.call_portal("search_and_read", dict(BODIES["search_and_read"]))


def test_search_and_read_low_cap_needs_20000(monkeypatch):
    monkeypatch.setenv("AGENTSEARCH_MAX_PER_CALL_ATOMIC", "8000")
    seen = mock_api(monkeypatch, "search_and_read")
    with pytest.raises(Err, match="to 20000"):
        _client.call_portal("search_and_read", dict(BODIES["search_and_read"]))
    assert all(c["sig"] is None for c in seen["calls"])


def test_search_and_read_no_key(monkeypatch):
    for k in _client.KEY_ENV_VARS:
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(Err, match="No wallet is configured"):
        _client.call_portal("search_and_read", dict(BODIES["search_and_read"]))


@pytest.mark.parametrize("op", ["news", "screenshot"])
def test_news_and_screenshot_are_direct_only(monkeypatch, op):
    monkeypatch.setenv("AGENTSEARCH_PAYMENT_ROUTE", "pocket")
    monkeypatch.setattr(_client.httpx, "Client", lambda **kw: pytest.fail("no network call expected"))
    with pytest.raises(Err, match="own x402 API"):
        _client.call_portal(op, dict(BODIES[op]))


def test_filters_and_extract_options_forwarded_on_direct(monkeypatch):
    seen = mock_api(monkeypatch, "news")
    _client.call_portal("news", dict(BODIES["news"]))
    assert seen["calls"][1]["body"] == BODIES["news"]
    seen = mock_api(monkeypatch, "extract")
    out = _client.call_portal("extract", {"url": "https://example.com", "max_chars": 900, "include_links": True, "formats": ["markdown"]})
    assert seen["calls"][1]["body"] == {"url": "https://example.com", "max_chars": 900, "include_links": True}
    assert out["payment"]["droppedFields"] == ["formats"]


def test_filters_dropped_on_pocket(monkeypatch):
    monkeypatch.setenv("AGENTSEARCH_PAYMENT_ROUTE", "pocket")
    seen = {}

    def handler(req):
        seen["body"] = json.loads(req.content)
        return httpx.Response(500, text="stop")

    monkeypatch.setattr(_client.httpx, "Client", lambda **kw: _REAL_CLIENT(transport=httpx.MockTransport(handler)))
    with pytest.raises(Err):
        _client.call_portal("search", {"query": "q", "freshness": "day", "country": "us"})
    assert seen["body"] == {"query": "q"}


def test_screenshot_tool_saves_file_not_base64(monkeypatch, tmp_path):
    from crewai_agentsearch import AgentSearchScreenshotTool
    monkeypatch.setenv("AGENTSEARCH_SCREENSHOT_DIR", str(tmp_path))
    png = b"\x89PNG\r\n\x1a\nfake"
    monkeypatch.setattr(_client, "call_portal", lambda op, body, client=None: {
        "url": body["url"], "screenshot": {"format": "png", "width": 1280, "height": 800, "bytes": len(png),
                                           "base64": base64.b64encode(png).decode()}, "payment": {"amountUsd": "$0.010"}})
    out = json.loads(AgentSearchScreenshotTool().run(url="https://example.com"))
    path = out["screenshot"]["path"]
    assert path.startswith(str(tmp_path)) and path.endswith(".png") and open(path, "rb").read() == png
    assert "omitted" in out["screenshot"]["base64"]


def test_news_tool_passes_filters(monkeypatch):
    from crewai_agentsearch import AgentSearchNewsTool
    got = {}
    monkeypatch.setattr(_client, "call_portal", lambda op, body, client=None: got.update(op=op, body=body) or {"results": []})
    AgentSearchNewsTool().run(query="base usdc", max_results=8, freshness="week", language="en")
    assert got == {"op": "news", "body": {"query": "base usdc", "max_results": 8, "freshness": "week", "language": "en"}}


def test_news_and_screenshot_need_wallet(monkeypatch):
    from crewai_agentsearch import AgentSearchNewsTool, AgentSearchScreenshotTool
    for k in _client.KEY_ENV_VARS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(_client.httpx, "Client", lambda **kw: pytest.fail("no network call expected"))
    assert "No wallet is configured" in AgentSearchNewsTool().run(query="x")
    assert "No wallet is configured" in AgentSearchScreenshotTool().run(url="https://example.com")
