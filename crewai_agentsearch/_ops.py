"""Framework-neutral operations. Each returns a JSON string, or an "Error: ..." string (never raises)."""
from __future__ import annotations

from typing import Any, Optional

from . import _client as c


_noted_key_without_opt_in = False


def resolve_search_mode(mode: str = "auto") -> str:
    """Return "paid" or "free" for a search call.

    mode="paid" and mode="free" are explicit and returned as-is (explicit paid without the [paid] extra
    still errors with install instructions, in call_portal). mode="auto" is free unless paid is opted in
    with AGENTSEARCH_MODE=paid; a wallet key in the environment alone does NOT switch to paid. If paid is
    opted in (or a key is set) but the [paid] extra is missing, auto falls back to free with a warning.
    """
    global _noted_key_without_opt_in
    if mode in ("paid", "free"):
        return mode
    wants_paid = c.env_mode() == "paid"
    if (wants_paid or c.has_wallet_key()) and not c.paid_extra_installed():
        c.logger.warning(
            "AgentSearch: %s, but the [paid] extra is not installed; using free search instead. "
            "To enable paid search: %s",
            "AGENTSEARCH_MODE=paid is set" if wants_paid else "a wallet key is set", c.PAID_INSTALL_HINT,
        )
        return "free"
    if wants_paid:
        return "paid"
    if c.has_wallet_key() and not _noted_key_without_opt_in:
        _noted_key_without_opt_in = True
        c.logger.info(
            "AgentSearch: a wallet key is set, but search stays free in mode='auto'. "
            "Use mode='paid' or AGENTSEARCH_MODE=paid to opt in to paid search."
        )
    return "free"


def search(query: str, max_results: Optional[int] = None, mode: str = "auto") -> str:
    try:
        if not query or not str(query).strip():
            raise c.AgentSearchError("query must not be empty")
        if max_results is not None:
            max_results = max(1, min(int(max_results), 5))
        if resolve_search_mode(mode) == "paid":
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

def search_and_read(query: str, num_results: Optional[int] = None, max_chars: Optional[int] = None,
                    render_fallback: Optional[bool] = None) -> str:
    """Search the live web and read the top pages in one paid call ($0.015, direct x402 only)."""
    try:
        if not query or not str(query).strip():
            raise c.AgentSearchError("query must not be empty")
        body: dict[str, Any] = {"query": query}
        if num_results is not None:
            body["num_results"] = int(num_results)
        if max_chars is not None:
            body["max_chars"] = int(max_chars)
        if render_fallback is not None:
            body["render_fallback"] = bool(render_fallback)
        return c.dumps(c.call_portal("search_and_read", body))
    except Exception as e:
        return f"Error: {e}"
