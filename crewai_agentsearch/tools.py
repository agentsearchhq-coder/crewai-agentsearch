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
    render_fallback: Optional[bool] = Field(default=None, description="If extract returns thin content, retry with render (extra $0.005)")


class RenderInput(BaseModel):
    url: str = Field(description="http(s) URL to render")
    formats: Optional[list[Literal["markdown", "text", "html", "links"]]] = None
    max_chars: Optional[int] = Field(default=None, gt=0)
    wait_until: Optional[Literal["domcontentloaded", "load", "networkidle"]] = None
    wait_for_selector: Optional[str] = None
    wait_ms: Optional[int] = Field(default=None, ge=0)


class AgentSearchTool(BaseTool):
    """Live web search. Free by default (25/day per user); paid and unlimited when a wallet key is set."""

    name: str = "agentsearch_search"
    description: str = "Live web search. Returns up to 5 ranked results (title, url, content). Use for current facts or finding URLs."
    args_schema: Type[BaseModel] = SearchInput
    mode: Literal["auto", "free", "paid"] = "auto"

    def _run(self, query: str, max_results: Optional[int] = None, **_: Any) -> str:
        return _ops.search(query, max_results, self.mode)


class AgentSearchExtractTool(BaseTool):
    name: str = "agentsearch_extract"
    description: str = "Fetch a URL and return its main content as clean text/markdown. Fast and best for articles, docs and static pages. If the result is empty or thin (JavaScript-heavy page, SPA, app shell), call agentsearch_render on the same URL, or pass render_fallback=true to do that automatically (a second $0.005 call). Paid: $0.005 per call (needs a wallet)."
    args_schema: Type[BaseModel] = ExtractInput

    def _run(self, url: str, formats: Optional[list[str]] = None, max_chars: Optional[int] = None,
             render_fallback: Optional[bool] = None, **_: Any) -> str:
        return _ops.paid("extract", url=url, formats=formats, max_chars=max_chars, render_fallback=render_fallback)


class AgentSearchRenderTool(BaseTool):
    name: str = "agentsearch_render"
    description: str = "Render a page in a real headless browser and return markdown/text/html/links. Use when agentsearch_extract returns empty or thin content, or for JavaScript-heavy pages (SPAs, dashboards, content loaded by scripts). Paid: $0.005 per call (needs a wallet)."
    args_schema: Type[BaseModel] = RenderInput

    def _run(self, url: str, formats: Optional[list[str]] = None, max_chars: Optional[int] = None,
             wait_until: Optional[str] = None, wait_for_selector: Optional[str] = None, wait_ms: Optional[int] = None, **_: Any) -> str:
        return _ops.paid("render", url=url, formats=formats, max_chars=max_chars, wait_until=wait_until,
                         wait_for_selector=wait_for_selector, wait_ms=wait_ms)
