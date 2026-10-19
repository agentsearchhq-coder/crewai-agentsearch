# Changelog

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
