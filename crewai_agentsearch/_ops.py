"""Framework-neutral operations. Each returns a JSON string, or an "Error: ..." string (never raises)."""
from __future__ import annotations

from typing import Any, Optional

from . import _client as c


def search(query: str, max_results: Optional[int] = None, mode: str = "auto") -> str:
    try:
        if not query or not str(query).strip():
            raise c.AgentSearchError("query must not be empty")
        if max_results is not None:
            max_results = max(1, min(int(max_results), 5))
        if mode == "paid" or (mode == "auto" and c.has_wallet_key()):
            body: dict[str, Any] = {"query": query}
            if max_results:
                body["max_results"] = max_results
            return c.dumps(c.call_portal("search", body))
        return c.dumps(c.free_search(query, max_results))
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
