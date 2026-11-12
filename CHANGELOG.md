# Changelog

## 0.5.0 (2026-11-12)
- **News search.** New `AgentSearchNewsTool` (`agentsearch_news_search`, $0.008): recent articles with title, URL, snippet, source and publish date (1-10, default 5); calls with no results are not charged.
- **Screenshots.** New `AgentSearchScreenshotTool` (`agentsearch_screenshot`, $0.010): PNG or JPEG of the viewport or full page (up to 4000 px), optional mobile `viewport`. The image is saved to a file (`AGENTSEARCH_SCREENSHOT_DIR`, default a temp folder) and the tool returns its path and metadata, not base64, so it doesn't flood the model's context.
- **Search filters** on paid search, news and search-and-read: `freshness`, `date_from`/`date_to`, `country`, `language`, `include_domains`/`exclude_domains` (up to 5). Free search ignores them; the Pocket route drops them (listed in `payment.droppedFields`).
- **Extract options on direct:** `max_chars` (up to 50000) and `include_links` are now forwarded (0.4.0 dropped them).
- **Lower prices:** extract $0.004 (was $0.007), search-and-read $0.009 (was $0.015). Search $0.008 and render $0.010 unchanged. News, screenshot and search-and-read are direct-only. Matches `@agentsearchhq/agentsearch-mcp` 1.8.0 and `langchain-agentsearch` 0.7.0.

## 0.4.0 (2026-11-10)
- **Search + Read in one paid call.** New `AgentSearchSearchAndReadTool (`agentsearch_search_and_read`)` posts to `https://api.agentsearchhq.com/x402/v1/search_and_read` at **$0.015**, charged only when at least one page returns text. Default 3 results (max 5), default 8000 characters per page (max 20000); `render_fallback=true` renders at most one thin page in the same call. About 48% less than a $0.008 search plus three $0.007 extracts ($0.029), and one payment instead of four.
- Direct-only: not on the Pocket route, not on a self-hosted base URL. A Pocket or no-wallet call refuses with nothing signed. Search itself stays free by default.
- Direct per-call ceiling raised to **$0.020** (`DIRECT_MAX_PER_CALL_ATOMIC = 20000`) so a $0.015 search-and-read can settle. An old `10000` cap now refuses with a hint to raise it to `20000`. Matches `@agentsearchhq/agentsearch-mcp` 1.7.0.

## 0.3.0 (2026-11-09)

### Changed: paid calls go directly to AgentSearch's x402 API by default

- With a wallet key, paid calls now go to AgentSearch's own x402 API on Base (`https://api.agentsearchhq.com/x402/v1/...`, payee `0xC49B157887e51c21CB655f39CF65D6a4c2a4C337`) instead of the Pocket Network Agentic Portal.
- **Price change for wallet users:** search $0.008, extract $0.007, render $0.010 per call (was $0.005 on Pocket). Failed and empty calls are not charged on the direct API.
- To keep the Pocket route and its $0.005 price, set `AGENTSEARCH_PAYMENT_ROUTE=pocket` (`AGENTSEARCH_X402_DIRECT=0` also works). Any other value refuses paid calls with nothing signed.
- Per-call hard cap is now `10000` atomic units ($0.010) on the direct route; it stays `5000` on Pocket. If you set `AGENTSEARCH_MAX_PER_CALL_ATOMIC` below the direct price, the refusal tells you how to fix it.
- On the direct route, extract and render take only `url` (and search `query`, `max_results`); other options are dropped and listed in `payment.droppedFields`. Use the Pocket route for options like `formats`, `max_chars` or screenshots.
- Free search with no wallet is unchanged.

## 0.2.1 (2026-10-19)

### Changed: paid search is now explicit opt-in (safety)

- In the default `mode="auto"`, `AgentSearchTool` **no longer switches to paid search just because a wallet key** (`AGENTSEARCH_WALLET_PRIVATE_KEY` or `POCKET_PRIVATE_KEY`) is set in the environment. It stays on free search.
- To use paid search, opt in explicitly: `AgentSearchTool(mode="paid")`, or set `AGENTSEARCH_MODE=paid` for the default `mode="auto"`.
- Explicit `mode="paid"` behaves exactly as before.
- If you relied on 0.2.0 auto-switching to paid when a key was set, add `AGENTSEARCH_MODE=paid` (or `mode="paid"`) to keep paid search.
- Extract and render are unchanged: they are paid tools and still need the wallet key.

### Fixed

- In `mode="auto"`, if paid is opted in (or a key is set) but the `[paid]` extra is not installed, search now falls back to free search with a logged warning instead of returning an error. Explicit `mode="paid"` without the extra still returns a clear error with the install command (`pip install 'crewai-agentsearch[paid]'`).

### Docs

- The free tier is described as up to 25 searches/day per IP (README, code comments, and the free-limit message the agent sees).
- Documented `AGENTSEARCH_EXTRACT_RENDER_FALLBACK=1` and `AGENTSEARCH_MODE`.
- Pricing is unchanged: $0.005 per paid call.

## 0.2.0 (2026-10-16)

- Client tag header, render guidance for extract/render, repository metadata.

## 0.1.0 (2026-10-16)

- First release.
