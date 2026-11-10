from __future__ import annotations

from typing import Any, Literal, Optional, Type

from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from . import _ops


class SearchInput(BaseModel):
    query: str = Field(description="Search query", min_length=1)
    max_results: Optional[int] = Field(default=None, ge=1, le=5, description="1-5, default 5")


class ExtractInput(BaseModel):
    url: str = Field(description="http(s) URL to extract")
    formats: Optional[list[str]] = Field(default=None, description='e.g. ["markdown"]')
    max_chars: Optional[int] = Field(default=None, gt=0)
    render_fallback: Optional[bool] = Field(default=None, description="If extract returns thin content, retry with render (a second paid call, $0.010)")


class RenderInput(BaseModel):
    url: str = Field(description="http(s) URL to render")
    formats: Optional[list[Literal["markdown", "text", "html", "links"]]] = None
    max_chars: Optional[int] = Field(default=None, gt=0)
    wait_until: Optional[Literal["domcontentloaded", "load", "networkidle"]] = None
    wait_for_selector: Optional[str] = None
    wait_ms: Optional[int] = Field(default=None, ge=0)


class AgentSearchTool(BaseTool):
    """Live web search. Free by default (up to 25 searches/day per IP).

    Paid, unlimited search is opt-in only: mode="paid", or mode="auto" with AGENTSEARCH_MODE=paid
    (needs the [paid] extra and a wallet key). A wallet key alone does not switch search to paid."""

    name: str = "agentsearch_search"
    description: str = "Live web search. Returns up to 5 ranked results (title, url, content). Use for current facts or finding URLs."
    args_schema: Type[BaseModel] = SearchInput
    mode: Literal["auto", "free", "paid"] = "auto"

    def _run(self, query: str, max_results: Optional[int] = None, **_: Any) -> str:
        return _ops.search(query, max_results, self.mode)


class AgentSearchExtractTool(BaseTool):
    name: str = "agentsearch_extract"
    description: str = "Fetch a URL and return its main content as clean text/markdown. Fast and best for articles, docs and static pages. If the result is empty or thin (JavaScript-heavy page, SPA, app shell), call agentsearch_render on the same URL, or pass render_fallback=true to do that automatically (a second paid call). Paid: $0.007 per call via AgentSearch's x402 API (needs a wallet)."
    args_schema: Type[BaseModel] = ExtractInput

    def _run(self, url: str, formats: Optional[list[str]] = None, max_chars: Optional[int] = None,
             render_fallback: Optional[bool] = None, **_: Any) -> str:
        return _ops.paid("extract", url=url, formats=formats, max_chars=max_chars, render_fallback=render_fallback)


class SearchAndReadInput(BaseModel):
    query: str = Field(description="Search query", min_length=1)
    num_results: Optional[int] = Field(default=None, ge=1, le=5, description="How many top results to read, default 3, max 5")
    max_chars: Optional[int] = Field(default=None, gt=0, le=20000, description="Max characters of page text per result, default 8000, max 20000")
    render_fallback: Optional[bool] = Field(default=None, description="If extract is thin, render at most one page in the same $0.015 call")


class AgentSearchRenderTool(BaseTool):
    name: str = "agentsearch_render"
    description: str = "Render a page in a real headless browser and return markdown/text/html/links. Use when agentsearch_extract returns empty or thin content, or for JavaScript-heavy pages (SPAs, dashboards, content loaded by scripts). Paid: $0.010 per call via AgentSearch's x402 API (needs a wallet)."
    args_schema: Type[BaseModel] = RenderInput

    def _run(self, url: str, formats: Optional[list[str]] = None, max_chars: Optional[int] = None,
             wait_until: Optional[str] = None, wait_for_selector: Optional[str] = None, wait_ms: Optional[int] = None, **_: Any) -> str:
        return _ops.paid("render", url=url, formats=formats, max_chars=max_chars, wait_until=wait_until,
                         wait_for_selector=wait_for_selector, wait_ms=wait_ms)


class AgentSearchSearchAndReadTool(BaseTool):
    """Search the live web and read the top pages in one paid call ($0.015). Direct x402 only."""

    name: str = "agentsearch_search_and_read"
    description: str = (
        "Search the live web and return the top results with each page's main text in one paid call ($0.015 USDC on Base, charged only when at least one page returns text). "
        "Cheaper than a $0.008 search plus three $0.007 extracts ($0.029) and one payment instead of four. Default 3 results (max 5), default 8000 characters per page (max 20000). "
        "Pass render_fallback=true to render at most one thin page in the same call. Direct x402 only — not available on Pocket. Search itself stays free by default."
    )
    args_schema: Type[BaseModel] = SearchAndReadInput

    def _run(self, query: str, num_results: Optional[int] = None, max_chars: Optional[int] = None,
             render_fallback: Optional[bool] = None, **_: Any) -> str:
        return _ops.search_and_read(query, num_results=num_results, max_chars=max_chars, render_fallback=render_fallback)
