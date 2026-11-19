"""Framework-neutral operations. Each returns a JSON string, or an "Error: ..." string (never raises)."""
from __future__ import annotations

import base64
import os
import tempfile
import time
from typing import Any, Optional

from . import _client as c


def resolve_search_mode(mode: str = "auto") -> str:
    """Return "paid" or "free" for a search call.

    mode="paid" and mode="free" are explicit and returned as-is. mode="auto" (the default) pays for search when a
    wallet is configured (AGENTSEARCH_WALLET_PRIVATE_KEY, POCKET_PRIVATE_KEY or AGENTSEARCH_WALLET_FILE) or
    AGENTSEARCH_MODE=paid, and is free otherwise; AGENTSEARCH_MODE=free keeps it free (the opt-out). Before this
    release a wallet key alone never made search paid. If paid is wanted but the [paid] extra is missing, auto
    falls back to free with a warning.
    """
    if mode in ("paid", "free"):
        return mode
    env = c.env_mode()
    if env == "free":
        return "free"
    if env == "paid" or c.has_wallet_key():
        if not c.paid_extra_installed():
            c.logger.warning(
                "AgentSearch: %s, but the [paid] extra is not installed; using free search instead. "
                "To enable paid search: %s",
                "AGENTSEARCH_MODE=paid is set" if env == "paid" else "a wallet is configured", c.PAID_INSTALL_HINT,
            )
            return "free"
        c.announce_paid_search()
        return "paid"
    return "free"


def _filters(kw: dict[str, Any]) -> dict[str, Any]:
    return {k: kw[k] for k in c.FILTER_KEYS if kw.get(k) is not None}


def search(query: str, max_results: Optional[int] = None, mode: str = "auto", **filters: Any) -> str:
    try:
        query = c.check_query(query)
        if max_results is not None:
            max_results = max(1, min(int(max_results), 5))
        if resolve_search_mode(mode) == "paid":
            body: dict[str, Any] = {"query": query, **_filters(filters)}
            if max_results:
                body["max_results"] = max_results
            return c.dumps(c.with_mode(c.call_portal("search", body), "paid"))
        out = c.with_mode(c.free_search(query, max_results), "free")
        if _filters(filters) and isinstance(out, dict):
            out = {**out, "note": "Filters (freshness, dates, country, language, domains) apply only to paid search; free search ignored them."}
        return c.dumps(out)
    except Exception as e:
        return f"Error: {e}"


def paid(op: str, **kwargs: Any) -> str:
    try:
        if not c.has_wallet_key():
            raise c.AgentSearchError(c.paid_only_message(f"agentsearch_{op}"))
        fb = kwargs.pop("render_fallback", None)
        body = {k: v for k, v in kwargs.items() if v is not None}
        if op == "extract":
            return c.dumps(c.extract_with_fallback(body, fb))
        return c.dumps(c.call_portal(op, body))
    except Exception as e:
        return f"Error: {e}"

def search_and_read(query: str, num_results: Optional[int] = None, max_chars: Optional[int] = None,
                    render_fallback: Optional[bool] = None, **filters: Any) -> str:
    """Search the live web and read the top pages in one paid call ($0.005, direct x402 only)."""
    try:
        query = c.check_query(query)
        body: dict[str, Any] = {"query": query, **_filters(filters)}
        if num_results is not None:
            body["num_results"] = int(num_results)
        if max_chars is not None:
            body["max_chars"] = int(max_chars)
        if render_fallback is not None:
            body["render_fallback"] = bool(render_fallback)
        return c.dumps(c.call_portal("search_and_read", body))
    except Exception as e:
        return f"Error: {e}"


def news(query: str, max_results: Optional[int] = None, **filters: Any) -> str:
    """Recent news articles in one paid call ($0.003, direct x402 only; no results, no charge)."""
    try:
        query = c.check_query(query)
        if not c.has_wallet_key():
            raise c.AgentSearchError(c.paid_only_message("agentsearch_news_search"))
        body: dict[str, Any] = {"query": query, **_filters(filters)}
        if max_results is not None:
            body["max_results"] = max(1, min(int(max_results), 10))
        return c.dumps(c.call_portal("news", body))
    except Exception as e:
        return f"Error: {e}"


def _shot_dir() -> str:
    d = (os.environ.get("AGENTSEARCH_SCREENSHOT_DIR") or "").strip() or os.path.join(tempfile.gettempdir(), "agentsearch-screenshots")
    os.makedirs(d, exist_ok=True)
    return d


def screenshot(url: str, format: Optional[str] = None, full_page: Optional[bool] = None,
               viewport: Optional[dict[str, int]] = None) -> str:
    """Website screenshot in one paid call ($0.004, direct x402 only).

    The image is saved to a file (AGENTSEARCH_SCREENSHOT_DIR, default a temp folder) and the returned JSON holds
    its path plus metadata, not the base64 bytes, so the image does not flood the model's context."""
    try:
        if not url or not str(url).strip().lower().startswith(("http://", "https://")):
            raise c.AgentSearchError("url must be a full http(s) URL")
        if not c.has_wallet_key():
            raise c.AgentSearchError(c.paid_only_message("agentsearch_screenshot"))
        body: dict[str, Any] = {"url": str(url).strip()}
        if format is not None:
            body["format"] = format
        if full_page is not None:
            body["full_page"] = bool(full_page)
        if viewport is not None:
            body["viewport"] = {"width": int(viewport["width"]), "height": int(viewport["height"])}
        out = c.call_portal("screenshot", body)
        shot = out.get("screenshot") if isinstance(out, dict) else None
        if isinstance(shot, dict) and isinstance(shot.get("base64"), str):
            ext = "jpg" if str(shot.get("format") or format or "png").lower() in ("jpeg", "jpg") else "png"
            path = os.path.join(_shot_dir(), f"agentsearch-{int(time.time() * 1000)}.{ext}")
            with open(path, "wb") as f:
                f.write(base64.b64decode(shot["base64"]))
            out = {**out, "screenshot": {**{k: v for k, v in shot.items() if k != "base64"}, "path": path,
                                         "base64": "(omitted from text; image saved at path)"}}
        return c.dumps(out)
    except Exception as e:
        return f"Error: {e}"
