# crewai-agentsearch

[CrewAI](https://www.crewai.com/) tools for [AgentSearch](https://agentsearchhq.com/?utm_source=crewai-agentsearch&utm_medium=package): live web search for agents. Free search needs no API key.

| Tool | Name | Cost |
|---|---|---|
| `AgentSearchTool` | `agentsearch_search` | **Free** (up to 25 searches/day per IP, up to 5 results, no key). Paid and unlimited only when you opt in (see Paid mode). |
| `AgentSearchExtractTool` | `agentsearch_extract` | $0.005/call (USDC on Base via x402) |
| `AgentSearchRenderTool` | `agentsearch_render` | $0.005/call (headless browser for JS pages) |

## Install

```bash
pip install -U crewai-agentsearch
```

## Quickstart

```python
from crewai import Agent, Crew, Task
from crewai_agentsearch import AgentSearchTool

search = AgentSearchTool()
print(search.run(query="latest CrewAI release", max_results=3))  # JSON string

researcher = Agent(role="Researcher", goal="Find current facts with sources",
                   backstory="You always cite URLs.", tools=[search])
task = Task(description="What changed in the latest CrewAI release?", expected_output="3 bullets with URLs", agent=researcher)
print(Crew(agents=[researcher], tasks=[task]).kickoff())
```

Add `AgentSearchExtractTool()` and `AgentSearchRenderTool()` to `tools` once paid mode is set up.

## Paid mode

Install the `paid` extra (`pip install "crewai-agentsearch[paid]"`) and set `AGENTSEARCH_WALLET_PRIVATE_KEY` (or `POCKET_PRIVATE_KEY`) to the private key of a **new wallet made only for this**, funded with a little USDC on Base (e.g. $1; no ETH needed). Each call costs $0.005 and is paid over x402 through the Pocket Network Agentic Portal using the official x402 Python SDK.

`AgentSearchExtractTool` and `AgentSearchRenderTool` are always paid and need the key.

**Paid search is opt-in (changed in 0.2.1).** Setting a wallet key does *not* make search paid. `AgentSearchTool` (default `mode="auto"`) stays on free search until you opt in in one of two ways:

```python
AgentSearchTool(mode="paid")   # always paid search
```

```bash
export AGENTSEARCH_MODE=paid   # opt in for AgentSearchTool in the default mode="auto"
```

| Setup | `AgentSearchTool` search |
|---|---|
| `mode="auto"` (default), no `AGENTSEARCH_MODE` | Free, even if a wallet key is set |
| `mode="auto"` + `AGENTSEARCH_MODE=paid` | Paid |
| `mode="auto"` + paid opted in or a key set, but `[paid]` extra not installed | Free, with a logged warning |
| `mode="paid"` | Paid; without the `[paid]` extra it returns an error that tells you how to install it |
| `mode="free"` | Always free |

| Env var | Default |
|---|---|
| `AGENTSEARCH_MODE` | unset (`paid` opts `mode="auto"` in to paid search; `free` forces free) |
| `AGENTSEARCH_MAX_TOTAL_ATOMIC` | `1000000` ($1.00 per process) |
| `AGENTSEARCH_MAX_PER_CALL_ATOMIC` | `5000` ($0.005; can only be lowered) |
| `AGENTSEARCH_TIMEOUT_MS` | `30000` |
| `AGENTSEARCH_EXTRACT_RENDER_FALLBACK` | unset (`1` turns on render fallback for extract, see below) |

Limits are checked before anything is signed. The key is never returned in tool output. Paid results include a `payment` object.

### Extract to render fallback

Set `AGENTSEARCH_EXTRACT_RENDER_FALLBACK=1` to make `AgentSearchExtractTool` automatically retry a URL with render when extract returns thin content (under 200 characters of text, typical for JavaScript-heavy pages). It is off by default because the render retry is a second $0.005 call (so up to $0.010 for that URL), still bounded by `AGENTSEARCH_MAX_TOTAL_ATOMIC`. You can also turn it on or off per call with the tool's `render_fallback` argument, which overrides the env var. When the fallback runs, the result includes a `render_fallback` object.

## Errors

Tools return `"Error: ..."` strings instead of raising. A 429 from the free relay means the free daily limit (up to 25 searches/day per IP) was hit, and the message explains how to upgrade.

See [CHANGELOG.md](CHANGELOG.md) for release notes.

## Development

```bash
pip install -e ".[test]" && pytest     # unit tests (mocked)
AGENTSEARCH_LIVE=1 pytest -k live       # one real free search
```

Docs: https://agentsearchhq.com/agents.md?utm_source=crewai-agentsearch&utm_medium=package

MIT
