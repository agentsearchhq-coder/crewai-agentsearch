from __future__ import annotations

from typing import Any, Literal, Optional, Type

from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from . import _ops


class _Filters(BaseModel):
    freshness: Optional[Literal["day", "week", "month", "year"]] = Field(default=None, description="Only results from the past day/week/month/year (paid only)")
    date_from: Optional[str] = Field(default=None, description="Earliest publish date YYYY-MM-DD (paid only)")
    date_to: Optional[str] = Field(default=None, description="Latest publish date YYYY-MM-DD (paid only)")
    country: Optional[str] = Field(default=None, min_length=2, max_length=2, description="2-letter country code, e.g. us, gb (paid only)")
    language: Optional[str] = Field(default=None, description="Language code, e.g. en, es, pt-BR (paid only)")
    include_domains: Optional[list[str]] = Field(default=None, max_length=5, description="Only these domains, up to 5 (paid only)")
    exclude_domains: Optional[list[str]] = Field(default=None, max_length=5, description="Never these domains, up to 5 (paid only)")


def _filters(kw: dict[str, Any]) -> dict[str, Any]:
    return {k: kw[k] for k in _Filters.model_fields if kw.get(k) is not None}


class SearchInput(_Filters):
    query: str = Field(description="Search query", min_length=1)
    max_results: Optional[int] = Field(default=None, ge=1, le=5, description="1-5, default 5")


class NewsInput(_Filters):
    query: str = Field(description="News search query", min_length=1)
    max_results: Optional[int] = Field(default=None, ge=1, le=10, description="1-10, default 5")


class ScreenshotViewport(BaseModel):
    width: int = Field(ge=320, le=1920)
    height: int = Field(ge=320, le=1920)


class ScreenshotInput(BaseModel):
    url: str = Field(description="Full public http(s) URL to capture")
    format: Optional[Literal["png", "jpeg"]] = Field(default=None, description="Image format, default png")
    full_page: Optional[bool] = Field(default=None, description="Capture the whole page (clipped at 4000 px tall) instead of the viewport")
    viewport: Optional[ScreenshotViewport] = Field(default=None, description="Viewport in CSS pixels, e.g. 390x844 for mobile; default 1280x800")


class ExtractInput(BaseModel):
    url: str = Field(description="http(s) URL to extract")
    formats: Optional[list[str]] = Field(default=None, description='e.g. ["markdown"]')
    max_chars: Optional[int] = Field(default=None, gt=0, le=50000, description="Max characters of page text, up to 50000")
    include_links: Optional[bool] = Field(default=None, description="Also return the page's links")
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
    description: str = ("Live web search. Returns up to 5 ranked results (title, url, content). Use for current facts or finding URLs. "
                        "Free by default; paid mode ($0.008) also honors freshness/date range, country, language and include/exclude domain filters. "
                        "For recent news use agentsearch_news_search.")
    args_schema: Type[BaseModel] = SearchInput
    mode: Literal["auto", "free", "paid"] = "auto"

    def _run(self, query: str, max_results: Optional[int] = None, **kw: Any) -> str:
        return _ops.search(query, max_results, self.mode, **_filters(kw))


class AgentSearchExtractTool(BaseTool):
    name: str = "agentsearch_extract"
    description: str = "Fetch a URL and return its main content as clean text/markdown. Fast and best for articles, docs and static pages. If the result is empty or thin (JavaScript-heavy page, SPA, app shell), call agentsearch_render on the same URL, or pass render_fallback=true to do that automatically (a second paid call). Paid: $0.004 per call via AgentSearch's x402 API (needs a wallet)."
    args_schema: Type[BaseModel] = ExtractInput

    def _run(self, url: str, formats: Optional[list[str]] = None, max_chars: Optional[int] = None,
             include_links: Optional[bool] = None, render_fallback: Optional[bool] = None, **_: Any) -> str:
        return _ops.paid("extract", url=url, formats=formats, max_chars=max_chars, include_links=include_links,
                         render_fallback=render_fallback)


class SearchAndReadInput(_Filters):
    query: str = Field(description="Search query", min_length=1)
    num_results: Optional[int] = Field(default=None, ge=1, le=5, description="How many top results to read, default 3, max 5")
    max_chars: Optional[int] = Field(default=None, gt=0, le=20000, description="Max characters of page text per result, default 8000, max 20000")
    render_fallback: Optional[bool] = Field(default=None, description="If extract is thin, render at most one page in the same $0.009 call")


class AgentSearchRenderTool(BaseTool):
    name: str = "agentsearch_render"
    description: str = "Render a page in a real headless browser and return markdown/text/html/links. Use when agentsearch_extract returns empty or thin content, or for JavaScript-heavy pages (SPAs, dashboards, content loaded by scripts). Paid: $0.010 per call via AgentSearch's x402 API (needs a wallet)."
    args_schema: Type[BaseModel] = RenderInput

    def _run(self, url: str, formats: Optional[list[str]] = None, max_chars: Optional[int] = None,
             wait_until: Optional[str] = None, wait_for_selector: Optional[str] = None, wait_ms: Optional[int] = None, **_: Any) -> str:
        return _ops.paid("render", url=url, formats=formats, max_chars=max_chars, wait_until=wait_until,
                         wait_for_selector=wait_for_selector, wait_ms=wait_ms)


class AgentSearchSearchAndReadTool(BaseTool):
    """Search the live web and read the top pages in one paid call ($0.009). Direct x402 only."""

    name: str = "agentsearch_search_and_read"
    description: str = (
        "Search the live web and return the top results with each page's main text in one paid call ($0.009 USDC on Base, charged only when at least one page returns text). "
        "Cheaper than a $0.008 search plus three $0.004 extracts ($0.020) and one payment instead of four. Optional freshness, dates, country, language and domain filters. Default 3 results (max 5), default 8000 characters per page (max 20000). "
        "Pass render_fallback=true to render at most one thin page in the same call. Direct x402 only — not available on Pocket. Search itself stays free by default."
    )
    args_schema: Type[BaseModel] = SearchAndReadInput

    def _run(self, query: str, num_results: Optional[int] = None, max_chars: Optional[int] = None,
             render_fallback: Optional[bool] = None, **kw: Any) -> str:
        return _ops.search_and_read(query, num_results=num_results, max_chars=max_chars, render_fallback=render_fallback, **_filters(kw))


class AgentSearchNewsTool(BaseTool):
    """Recent news articles in one paid call on AgentSearch's direct x402 API ($0.008; no results, no charge). Direct only."""

    name: str = "agentsearch_news_search"
    description: str = (
        "Search recent news articles and return title, URL, snippet, source domain and publish date for each (1-10, default 5). "
        "Use for current events, company or product news, and anything where recency matters; optional freshness (day/week/month/year) "
        "or date_from/date_to, country, language, include/exclude domains. To read an article in full, pass its URL to agentsearch_extract. "
        "Paid: $0.008 per call (USDC on Base via x402 to AgentSearch's own API; calls with no results are not charged). Needs a wallet."
    )
    args_schema: Type[BaseModel] = NewsInput

    def _run(self, query: str, max_results: Optional[int] = None, **kw: Any) -> str:
        return _ops.news(query, max_results, **_filters(kw))


class AgentSearchScreenshotTool(BaseTool):
    """Website screenshot in one paid call on AgentSearch's direct x402 API ($0.010). Direct only.
    The image is saved to a file (AGENTSEARCH_SCREENSHOT_DIR, default a temp folder); the tool output has its path, not the bytes."""

    name: str = "agentsearch_screenshot"
    description: str = (
        "Load a public URL in a real headless browser and capture a PNG or JPEG screenshot of the viewport or the full page "
        "(up to 4000 px tall), plus title, final URL and HTTP status. Use for visual checks, layout or UI questions, and pages "
        "where the look matters; for page text use agentsearch_extract. Set viewport (e.g. 390x844) for mobile. "
        "The image is saved to a local file and its path is returned. Paid: $0.010 per call (USDC on Base via x402 to AgentSearch's own API). Needs a wallet."
    )
    args_schema: Type[BaseModel] = ScreenshotInput

    def _run(self, url: str, format: Optional[str] = None, full_page: Optional[bool] = None, viewport: Any = None, **_: Any) -> str:
        vp = viewport.model_dump() if hasattr(viewport, "model_dump") else viewport
        return _ops.screenshot(url, format=format, full_page=full_page, viewport=vp)
