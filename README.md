# crewai-agentsearch

[CrewAI](https://www.crewai.com/) tools for [AgentSearch](https://agentsearchhq.com/?utm_source=crewai-agentsearch&utm_medium=package): live web search for agents. Free search needs no API key.

| Tool | Name | Cost |
|---|---|---|
| `AgentSearchTool` | `agentsearch_search` | **Free** (25 searches/day per user, up to 5 results, no key). Paid and unlimited if a wallet is set. |
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

Install the `paid` extra (`pip install "crewai-agentsearch[paid]"`) and set `AGENTSEARCH_WALLET_PRIVATE_KEY` to the private key of a **new wallet made only for this**, funded with a little USDC on Base (e.g. $1; no ETH needed). Each call costs $0.005 and is paid over x402 through the Pocket Network Agentic Portal using the official x402 Python SDK. With a key set, search also goes paid and unlimited.

| Env var | Default |
|---|---|
| `AGENTSEARCH_MAX_TOTAL_ATOMIC` | `1000000` ($1.00 per process) |
| `AGENTSEARCH_MAX_PER_CALL_ATOMIC` | `5000` ($0.005; can only be lowered) |
| `AGENTSEARCH_TIMEOUT_MS` | `30000` |

Limits are checked before anything is signed. The key is never logged or returned. Paid results include a `payment` object.

## Errors

Tools return `"Error: ..."` strings instead of raising. A 429 from the free relay means the daily limit (25 searches/day per user) was hit, and the message explains how to upgrade.

## Development

```bash
pip install -e ".[test]" && pytest     # unit tests (mocked)
AGENTSEARCH_LIVE=1 pytest -k live       # one real free search
```

Docs: https://agentsearchhq.com/agents.md?utm_source=crewai-agentsearch&utm_medium=package

MIT
