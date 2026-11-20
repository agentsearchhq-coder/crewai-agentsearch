"""HTTP layer: free relay search and x402 pay-per-call. Since 0.3.0 paid calls go to AgentSearch's own
x402 API on Base by default; AGENTSEARCH_PAYMENT_ROUTE=pocket uses the Pocket Network Agentic Portal.

The wallet key is read from env and used only to sign; it is not included in tool output or error messages.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
from typing import Any, Optional

import httpx

logger = logging.getLogger("crewai_agentsearch")

FREE_RELAY_URL = "https://relay.agentsearchhq.com"
FREE_RELAY_DAILY_LIMIT = 25
DEFAULT_PORTAL_URL = "https://agent.pocket.network"
BASE_NETWORK = "eip155:8453"
USDC_BASE = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
PORTAL_PAYEE = "0xF732ea490c5766071785a2310523f7fA2CEbB829"
MAX_PER_CALL_ATOMIC = 5000  # $0.005 hard ceiling
DEFAULT_SESSION_CAP_ATOMIC = 1_000_000  # $1.00
KEY_ENV_VARS = ("AGENTSEARCH_WALLET_PRIVATE_KEY", "POCKET_PRIVATE_KEY")
# Search pays when a wallet is configured (default mode "auto"); mode="free" or AGENTSEARCH_MODE=free keeps it free.
MODE_ENV_VAR = "AGENTSEARCH_MODE"
PAID_INSTALL_HINT = "pip install 'crewai-agentsearch[paid]'"
SERVICES = {
    "search": ("agentsearch-web-search-v1", "/v1/search"),
    "extract": ("agentsearch-web-extract-v1", "/v1/extract"),
    "render": ("agentsearch-web-render-v1", "/v1/render"),
}
PACKAGE_NAME = "crewai-agentsearch"
# Extract output shorter than this (characters of text) counts as "thin": usually a JS-heavy page.
THIN_CHARS = 200
# 0.3.0: direct x402 to AgentSearch's own API on Base is the default paid route.
ROUTE_ENV_VAR = "AGENTSEARCH_PAYMENT_ROUTE"
DIRECT_ENV_VAR = "AGENTSEARCH_X402_DIRECT"  # =0/false/no/off also selects pocket (same switch as langchain-agentsearch)
DEFAULT_DIRECT_URL = "https://api.agentsearchhq.com"
DIRECT_PAYEE = "0xC49B157887e51c21CB655f39CF65D6a4c2a4C337"
DIRECT_MAX_PER_CALL_ATOMIC = 20_000  # $0.020 hard ceiling (search $0.003, news $0.003, extract $0.002, render $0.005, screenshot $0.004, search_and_read $0.005)
# 0.5.0: optional search filters (direct only) on search, news and search_and_read.
FILTER_KEYS = ("freshness", "date_from", "date_to", "country", "language", "include_domains", "exclude_domains")
DIRECT_FIELDS = {"search": ("query", "max_results") + FILTER_KEYS, "news": ("query", "max_results") + FILTER_KEYS,
                 "extract": ("url", "max_chars", "include_links"), "render": ("url",),
                 "screenshot": ("url", "format", "full_page", "viewport"),
                 "search_and_read": ("query", "num_results", "max_results", "max_chars", "render_fallback") + FILTER_KEYS}
# Tools that exist only on AgentSearch's own x402 API (not on Pocket, not on the free relay).
DIRECT_ONLY = {"search_and_read": "$0.005 per call when at least one page returns text",
               "news": "$0.003 per call", "screenshot": "$0.004 per call"}
PRICES_SENTENCE = ("paid per call in USDC on Base via x402 to AgentSearch's own API (search $0.003, news $0.003, extract $0.002, "
                   "render $0.005, screenshot $0.004, search_and_read $0.005; $1 covers about 500 extracts or 200 search-and-read calls; failed calls are not charged), or $0.005 per call through "
                   "the Pocket Network portal with AGENTSEARCH_PAYMENT_ROUTE=pocket")
DOCS = "https://agentsearchhq.com/?utm_source=crewai-agentsearch&utm_medium=package"

FREE_LIMIT_MESSAGE = (
    f"Free search limit reached ({FREE_RELAY_DAILY_LIMIT} free searches per IP in total, then pay per call, subject to shared daily capacity; the free searches do not reset). "
    "For unlimited search plus extract/render, set AGENTSEARCH_WALLET_PRIVATE_KEY to the key of a NEW wallet "
    "funded with a little USDC on Base (search $0.003, extract $0.002, render $0.005 per call via x402 to AgentSearch; capped by AGENTSEARCH_MAX_TOTAL_ATOMIC, "
    f"default $1.00; or AGENTSEARCH_WALLET_FILE=agentcash to reuse an AgentCash wallet) and install crewai-agentsearch[paid]: "
    f"with a wallet, search pays per call (unless AGENTSEARCH_MODE=free). Docs: {DOCS}"
)


def paid_only_message(name: str) -> str:
    return (
        f"{name} is paid ({PRICES_SENTENCE}). No wallet is configured, so no call was made. "
        "Set AGENTSEARCH_WALLET_PRIVATE_KEY to the key of a NEW wallet funded with a little USDC on Base and "
        f"install crewai-agentsearch[paid]. Docs: {DOCS}"
    )


class AgentSearchError(Exception):
    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status


MIN_QUERY_CHARS = 2


def check_query(query: Any) -> str:
    """Trim a search query and reject empty or too-short ones before any network request (nothing is sent or charged)."""
    q = str(query).strip() if query is not None else ""
    if not q:
        raise AgentSearchError("query must not be empty: pass a non-empty search string. Nothing was sent or charged.")
    if len(q) < MIN_QUERY_CHARS:
        raise AgentSearchError(f"query {q!r} is too short (minimum {MIN_QUERY_CHARS} characters): rewrite the query "
                               "(at least 2 characters) as a real search, e.g. a few keywords. Don't retry it unchanged. "
                               "Nothing was sent or charged.")
    return q


def payment_route() -> str:
    """'direct' (default since 0.3.0) or 'pocket'. AGENTSEARCH_PAYMENT_ROUTE wins; AGENTSEARCH_X402_DIRECT=0
    also selects 'pocket'. Any other route value raises (nothing is signed)."""
    v = (os.environ.get(ROUTE_ENV_VAR) or "").strip().lower()
    if v:
        if v in ("direct", "x402", "agentsearch"):
            return "direct"
        if v in ("pocket", "portal"):
            return "pocket"
        raise AgentSearchError(f"{ROUTE_ENV_VAR} must be 'direct' (default) or 'pocket', got {v!r}. Nothing was signed.")
    if (os.environ.get(DIRECT_ENV_VAR) or "").strip().lower() in ("0", "false", "no", "off"):
        return "pocket"
    return "direct"


def direct_enabled() -> bool:
    """True unless the Pocket route is selected (AGENTSEARCH_PAYMENT_ROUTE=pocket or AGENTSEARCH_X402_DIRECT=0)."""
    return payment_route() == "direct"


def _version() -> str:
    try:
        from importlib import metadata
        return metadata.version(PACKAGE_NAME)
    except Exception:
        return "0"


def client_headers() -> dict[str, str]:
    """Anonymous package tag so AgentSearch can count usage per integration (name/version only).
    Opt out with AGENTSEARCH_NO_CLIENT_TAG=1. AGENTSEARCH_SELF=1 marks our own test traffic."""
    h: dict[str, str] = {}
    if (os.environ.get("AGENTSEARCH_NO_CLIENT_TAG") or "").strip() != "1":
        h["X-Agent-Client"] = f"{PACKAGE_NAME}/{_version()}"
    if (os.environ.get("AGENTSEARCH_SELF") or "").strip() == "1":
        h["X-AgentSearch-Self"] = "1"
    return h


def timeout_s() -> float:
    try:
        n = int(os.environ.get("AGENTSEARCH_TIMEOUT_MS", ""))
        if 1000 <= n <= 300_000:
            return n / 1000
    except ValueError:
        pass
    return 30.0


def _strip_provider(d: Any) -> Any:
    if isinstance(d, dict):
        d.pop("provider", None)
    return d


def free_search(query: str, max_results: Optional[int] = None, client: Optional[httpx.Client] = None) -> Any:
    body: dict[str, Any] = {"query": query}
    if max_results is not None:
        body["max_results"] = max_results
    c = client or httpx.Client(timeout=timeout_s())
    try:
        r = c.post(f"{FREE_RELAY_URL}/v1/search", json=body, headers={"accept": "application/json", **client_headers()})
    finally:
        if client is None:
            c.close()
    if r.status_code == 429:
        raise AgentSearchError(FREE_LIMIT_MESSAGE, 429)
    if r.status_code >= 400:
        hint = (" This is an input error: fix the query instead of retrying it unchanged."
                if 400 <= r.status_code < 500 and r.status_code != 408 else "")
        raise AgentSearchError(f"AgentSearch relay HTTP {r.status_code}: {r.text[:500]}{hint}", r.status_code)
    try:
        return _strip_provider(r.json())
    except ValueError:
        return {"raw": r.text}


# ---------- paid mode ----------

def has_wallet_key() -> bool:
    """True when a wallet is configured (a key env var or AGENTSEARCH_WALLET_FILE)."""
    return wallet_source() is not None


def search_mode_label(resolved: str) -> str:
    """Human-readable search mode, put on every search result as agentsearch_mode."""
    if resolved == "paid":
        route = "direct"
        try:
            route = payment_route()
        except Exception:
            pass
        if route == "pocket":
            return ("paid: x402 via the Pocket portal, $0.005 per search (AGENTSEARCH_PAYMENT_ROUTE=pocket; "
                    "AGENTSEARCH_MODE=free keeps search free)")
        return ("paid: x402 to AgentSearch's API, $0.003 per search (wallet configured; "
                "AGENTSEARCH_MODE=free keeps search free)")
    if has_wallet_key():
        return ("free: AgentSearch free tier, 25 free searches per IP in total, then pay per call (mode free, or the [paid] extra is "
                "missing; a wallet is configured but search does not pay)")
    return "free: AgentSearch free tier, 25 free searches per IP in total, then pay per call (no wallet configured)"


def with_mode(out: Any, resolved: str) -> Any:
    return {"agentsearch_mode": search_mode_label(resolved), **out} if isinstance(out, dict) else out


_announced_paid = False


def announce_paid_search() -> None:
    """Log once per process that search pays, so a wallet never makes search paid silently."""
    global _announced_paid
    if not _announced_paid:
        _announced_paid = True
        logger.warning("AgentSearch search mode: %s; wallet from %s.", search_mode_label("paid"), wallet_source())


def env_mode() -> str:
    """AGENTSEARCH_MODE as "paid", "free", "auto" or "" (unset or unrecognised). Only affects mode="auto"."""
    v = (os.environ.get(MODE_ENV_VAR) or "").strip().lower()
    return v if v in ("paid", "free", "auto") else ""


def paid_extra_installed() -> bool:
    """True if the [paid] extra (x402 SDK + eth-account) is importable. Imports nothing that signs."""
    try:
        import eth_account  # noqa: F401
        from x402 import x402ClientSync  # noqa: F401
        from x402.http import x402HTTPClientSync  # noqa: F401
        from x402.mechanisms.evm.exact import register_exact_evm_client  # noqa: F401
    except ImportError:
        return False
    return True


# Reuse an existing wallet file instead of pasting a raw key: a file holding a 64-hex key (for example a
# ClawRouter-style wallet.key) or JSON with a "privateKey" field (AgentCash's ~/.agentcash/wallet.json).
# The value "agentcash" means ~/.agentcash/wallet.json. Read only when signing; contents are never logged.
# Encrypted keystores and remote signers (CDP server wallets) are not supported yet.
WALLET_FILE_ENV_VAR = "AGENTSEARCH_WALLET_FILE"


def wallet_file_path() -> Optional[str]:
    raw = (os.environ.get(WALLET_FILE_ENV_VAR) or "").strip()
    if not raw:
        return None
    if raw.lower() == "agentcash":
        return os.path.join(os.path.expanduser("~"), ".agentcash", "wallet.json")
    return os.path.expanduser(raw)


def wallet_source() -> Optional[str]:
    """Name of the env var the wallet comes from, or None when no wallet is configured. Never the key."""
    for name in KEY_ENV_VARS:
        if (os.environ.get(name) or "").strip():
            return name
    return WALLET_FILE_ENV_VAR if wallet_file_path() else None


def _key_from_wallet_file(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            content = fh.read().strip()
    except OSError as e:
        raise AgentSearchError(f"{WALLET_FILE_ENV_VAR} points to a file that could not be read "
                               f"({type(e).__name__}): {path}. Nothing was signed.") from None
    if not content.startswith("{"):
        return content
    try:
        data = json.loads(content)
    except ValueError:
        raise AgentSearchError(f"{WALLET_FILE_ENV_VAR} ({path}) is not valid JSON. The contents are not shown. "
                               "Nothing was signed.") from None
    pk = data.get("privateKey", data.get("private_key")) if isinstance(data, dict) else None
    if not isinstance(pk, str):
        raise AgentSearchError(f'{WALLET_FILE_ENV_VAR} ({path}) has no "privateKey" field (encrypted keystores are '
                               "not supported). The contents are not shown. Nothing was signed.")
    return pk.strip()


def _normalize_key(raw: str, name: str) -> str:
    if not re.fullmatch(r"(0x)?[0-9a-fA-F]{64}", raw):
        raise AgentSearchError(
            f"{name} is set but is not a private key (expected 64 hex characters, optional 0x prefix). "
            "The value is not shown. Nothing was signed."
        )
    return raw if raw.startswith("0x") else "0x" + raw


def _read_wallet_key() -> Optional[str]:
    for name in KEY_ENV_VARS:
        raw = (os.environ.get(name) or "").strip()
        if raw:
            return _normalize_key(raw, name)
    path = wallet_file_path()
    if path:
        return _normalize_key(_key_from_wallet_file(path), f"{WALLET_FILE_ENV_VAR} ({path})")
    return None


def _atomic_env(names: tuple[str, ...], fallback: int) -> int:
    for name in names:
        raw = (os.environ.get(name) or "").strip()
        if not raw:
            continue
        if not raw.isdigit():
            raise AgentSearchError(f"{name} must be a whole number of USDC atomic units (1000000 = $1.00). Nothing was signed.")
        return int(raw)
    return fallback


def usd(atomic: int) -> str:
    return f"${atomic // 1_000_000}.{atomic % 1_000_000:06d}"


class _Budget:
    def __init__(self) -> None:
        self.spent = 0
        self.lock = threading.Lock()


_budget = _Budget()


def reset_session_budget() -> None:
    global _budget
    _budget = _Budget()


def session_spent_atomic() -> int:
    return _budget.spent


def _eq(a: Any, b: str) -> bool:
    return isinstance(a, str) and a.lower() == b.lower()


def select_accept(accepts: list[Any], ceiling: int, payee: str = PORTAL_PAYEE) -> Any:
    why = []
    for a in accepts or []:
        if a.scheme != "exact":
            why.append(f"{a.scheme} scheme"); continue
        if a.network != BASE_NETWORK:
            why.append(f"network {a.network}"); continue
        if not _eq(a.asset, USDC_BASE):
            why.append(f"asset {a.asset} is not USDC on Base"); continue
        if not _eq(a.pay_to, payee):
            why.append(f"payee {a.pay_to} is not {'AgentSearch' if payee == DIRECT_PAYEE else 'the portal'}'s"); continue
        if not str(a.amount).isdigit() or int(a.amount) <= 0:
            why.append(f"amount {a.amount}"); continue
        if int(a.amount) > ceiling:
            why.append(f"amount {a.amount} exceeds the cap of {ceiling} atomic units"); continue
        return a
    raise AgentSearchError(f"No acceptable payment option ({'; '.join(why) or 'none offered'}). Nothing was signed.")


def call_portal(op: str, body: dict[str, Any], client: Optional[httpx.Client] = None) -> dict[str, Any]:
    """Unpaid POST -> 402 -> limits checked -> sign (x402 SDK) -> retry once with PAYMENT-SIGNATURE."""
    try:
        from eth_account import Account
        from x402 import x402ClientSync
        from x402.http import x402HTTPClientSync
        from x402.mechanisms.evm.exact import register_exact_evm_client
    except ImportError as e:  # pragma: no cover
        raise AgentSearchError(
            f"Paid calls need the [paid] extra (x402 SDK): {PAID_INSTALL_HINT}. Nothing was signed."
        ) from e

    key = _read_wallet_key()
    if not key:
        raise AgentSearchError(paid_only_message(f"agentsearch_{op}"))
    direct = direct_enabled()
    if op in DIRECT_ONLY and not direct:
        tool = "agentsearch_news_search" if op == "news" else f"agentsearch_{op}"
        raise AgentSearchError(
            f"{tool} is available only on AgentSearch's own x402 API ({DIRECT_ONLY[op]}). "
            "Unset AGENTSEARCH_PAYMENT_ROUTE=pocket (and AGENTSEARCH_X402_DIRECT=0) to use the default direct route. "
            "Pocket does not offer this tool. Nothing was signed."
        )
    url_env = "AGENTSEARCH_X402_DIRECT_URL" if direct else "AGENTSEARCH_PORTAL_URL"
    portal = (os.environ.get(url_env) or (DEFAULT_DIRECT_URL if direct else DEFAULT_PORTAL_URL)).strip().rstrip("/")
    if not portal.startswith("https://") and not re.match(r"http://(localhost|127\.)", portal):
        raise AgentSearchError(f"{url_env} must be https://. Nothing was signed.")
    hard_cap = DIRECT_MAX_PER_CALL_ATOMIC if direct else MAX_PER_CALL_ATOMIC
    payee = DIRECT_PAYEE if direct else PORTAL_PAYEE
    session_cap = _atomic_env(("AGENTSEARCH_MAX_TOTAL_ATOMIC", "POCKET_MAX_TOTAL_ATOMIC"), DEFAULT_SESSION_CAP_ATOMIC)
    per_call = min(_atomic_env(("AGENTSEARCH_MAX_PER_CALL_ATOMIC", "POCKET_MAX_PER_CALL_ATOMIC"), hard_cap), hard_cap)
    service_id, path = (None, None) if op in DIRECT_ONLY else SERVICES[op]
    dropped: list[str] = []
    if direct:
        url, expect_res = f"{portal}/x402/v1/{op}", f"/x402/v1/{op}"
        dropped = [k for k, v in body.items() if v is not None and k not in DIRECT_FIELDS[op]]
        body = {k: v for k, v in body.items() if v is not None and k in DIRECT_FIELDS[op]}
    else:
        url, expect_res = f"{portal}/v1/{service_id}{path}", f"/v1/{service_id}"
        dropped = [k for k, v in body.items() if v is not None and k in FILTER_KEYS + ("include_links",)]
        body = {k: v for k, v in body.items() if k not in dropped}

    c = client or httpx.Client(timeout=timeout_s())
    try:
        unpaid = c.post(url, json=body, headers=client_headers())
        if unpaid.status_code != 402:
            raise AgentSearchError(f"Expected 402 from {'AgentSearch' if direct else 'the portal'}, got {unpaid.status_code}: {unpaid.text[:300]}. Nothing was signed.", unpaid.status_code)
        http = x402HTTPClientSync(x402ClientSync())
        try:
            required = http.get_payment_required_response(lambda n: unpaid.headers.get(n), unpaid.content)
        except Exception as e:
            raise AgentSearchError(f"The portal's 402 is not valid x402 v2 ({e}). Nothing was signed.")
        if getattr(required, "x402_version", None) != 2:
            raise AgentSearchError("Unsupported x402 version. Nothing was signed.")
        res_url = (getattr(getattr(required, "resource", None), "url", "") or "").rstrip("/")
        if not res_url.endswith(expect_res):
            raise AgentSearchError(f"The 402 is for resource {res_url}, not {expect_res}. Nothing was signed.")

        with _budget.lock:
            remaining = max(session_cap - _budget.spent, 0)
            ceiling = min(per_call, remaining)
            if ceiling <= 0:
                raise AgentSearchError(
                    f"Session spend cap reached: {usd(_budget.spent)} of {usd(session_cap)} signed. "
                    "Raise AGENTSEARCH_MAX_TOTAL_ATOMIC to spend more. Nothing was signed."
                )
            try:
                chosen = select_accept(list(required.accepts), ceiling, payee)
            except AgentSearchError as e:
                if direct and per_call < hard_cap and ceiling == per_call:
                    raise AgentSearchError(
                        f"{e} Your per-call cap (AGENTSEARCH_MAX_PER_CALL_ATOMIC={per_call}) is below this route's price; since 0.3.0 "
                        "paid calls go to AgentSearch's own x402 API (search $0.003, news $0.003, extract $0.002, render $0.005, screenshot $0.004, search_and_read $0.005). Raise the cap "
                        "to 20000, remove it, or set AGENTSEARCH_PAYMENT_ROUTE=pocket for the $0.005 Pocket route (search, extract and render only)."
                    ) from None
                raise
            amount = int(chosen.amount)

            def selector(_v: int, options: list[Any]) -> Any:
                for o in options:
                    if o.scheme == chosen.scheme and o.network == chosen.network and _eq(o.asset, chosen.asset) and _eq(o.pay_to, chosen.pay_to) and str(o.amount) == str(chosen.amount):
                        return o
                raise AgentSearchError("Selected option disappeared. Nothing was signed.")

            account = Account.from_key(key)
            signer_client = register_exact_evm_client(x402ClientSync(selector), account, networks=BASE_NETWORK)
            payer = x402HTTPClientSync(signer_client)
            signed = payer.create_payment_payload(required)
            auth = (signed.payload or {}).get("authorization") or {}
            if not _eq(auth.get("to"), payee) or int(auth.get("value", 0)) != amount:
                raise AgentSearchError("The signed authorization does not match the approved terms; it was discarded and not sent.")
            _budget.spent += amount  # counted at signing

        try:
            paid = c.post(url, json=body, headers={**client_headers(), **payer.encode_payment_signature_header(signed)})
        except Exception as e:
            raise AgentSearchError(f"A payment of {usd(amount)} was signed but the paid request failed ({e}). Check the wallet before retrying.")
        if not 200 <= paid.status_code < 300:
            raise AgentSearchError(
                f"{'AgentSearch' if direct else 'The portal'} answered {paid.status_code}: {paid.text[:300]}. Non-2xx answers are not settled; "
                f"the signed {usd(amount)} still counts against this session's cap.", paid.status_code)
        receipt = None
        try:
            receipt = payer.get_payment_settle_response(lambda n: paid.headers.get(n))
        except Exception:
            pass
        tx = getattr(receipt, "transaction", None) if receipt else None
        payment = {
            "amountAtomic": str(amount), "amountUsd": usd(amount), "asset": "USDC", "network": BASE_NETWORK,
            "payTo": payee, "payer": account.address, "serviceId": service_id,
            "settled": bool(getattr(receipt, "success", False)), "transaction": tx,
        }
        if direct:
            payment["rail"] = "agentsearch-x402-direct"
        if dropped:
            payment["droppedFields"] = dropped
        if tx:
            payment["explorer"] = f"https://basescan.org/tx/{tx}"
        try:
            env = paid.json()
        except ValueError:
            env = {"raw": paid.text}
        data = env.get("data", env) if isinstance(env, dict) else env
        out = _strip_provider(data) if isinstance(data, dict) else {"data": data}
        return {**out, "payment": payment}
    finally:
        if client is None:
            c.close()


def _text_len(v: Any) -> int:
    """Characters of page text in an extract/render result (markdown/text/content fields, any depth)."""
    if isinstance(v, dict):
        return sum(len(x) if k in ("markdown", "text", "content") and isinstance(x, str) else _text_len(x)
                   for k, x in v.items() if k != "payment")
    if isinstance(v, list):
        return sum(_text_len(x) for x in v)
    return 0


def fallback_enabled(flag: Optional[bool]) -> bool:
    if flag is not None:
        return bool(flag)
    return (os.environ.get("AGENTSEARCH_EXTRACT_RENDER_FALLBACK") or "").strip() == "1"


def extract_with_fallback(body: dict[str, Any], render_fallback: Optional[bool] = None,
                          client: Optional[httpx.Client] = None) -> dict[str, Any]:
    """Extract; if the result is thin (< THIN_CHARS of text) and fallback is on, render the same URL.
    Off by default because render is a second paid call ($0.005 direct) (still bounded by the session cap)."""
    out = call_portal("extract", body, client)
    if not fallback_enabled(render_fallback) or _text_len(out) >= THIN_CHARS:
        return out
    rbody: dict[str, Any] = {"url": body["url"]}
    if body.get("max_chars"):
        rbody["max_chars"] = body["max_chars"]
    fm = [f for f in (body.get("formats") or ["markdown"]) if f in ("markdown", "text", "html", "links")]
    rbody["formats"] = fm or ["markdown"]
    try:
        r = call_portal("render", rbody, client)
    except AgentSearchError as e:
        return {**out, "render_fallback": {"used": False, "error": str(e)}}
    return {**r, "render_fallback": {"used": True, "reason": f"extract returned under {THIN_CHARS} chars",
                                     "extract_payment": out.get("payment")}}


def dumps(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False)
